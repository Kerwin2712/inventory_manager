"""La ventana "Deudas por Cobrar" dentro de la Cartera de Clientes.

Lo que estas pruebas protegen es lo que el PDF del 17/10/2026 pide de forma
explícita y que un refactor de la vista rompería en silencio: el orden de
columnas del boceto, el signo de exclamación (!) sobre las deudas pasadas de
fecha, y que la columna "Monto a Cobrar" muestre el SALDO VIVO —lo que queda
por cobrar hoy— y no el monto original de la venta a crédito.

La vista se ejerce headless: se construye `CarteraView` contra la base
temporal y se recorre el árbol de controles. `BaseView.setup_layout()` envuelve
la construcción en un try/except que ante cualquier excepción pinta "Error al
Cargar Módulo", así que un fallo de construcción no se nota si no se busca.

La `PageFalsa` emula la API de pila de diálogos de Flet 0.86 (`show_dialog` /
`pop_dialog`) para que los diálogos de Cobrar, Editar y Borrar recorran el
mismo camino que en la aplicación: con el patrón heredado (`page.overlay` más
la bandera `open`) Flet no llega a dibujar el cierre.
"""
import asyncio

import flet as ft
import pytest

from services.cartera_service import crear_cliente
from services.deudas_service import crear_deuda, obtener_deuda, registrar_abono

HOY = "2026-10-18"
PASADO = "10/10/2026"
FUTURO = "31/12/2027"

ITEMS = [
    {"producto_codigo": "P-001", "descripcion_corta": "Filtro de aceite", "cantidad": 2, "subtotal_usd": 20.0},
]


# ─── Utilidades de recorrido del árbol de controles ──────────────────────────

def _aplanar(control, vistos=None) -> list:
    """Devuelve todos los controles del subárbol. Flet no expone un iterador
    de hijos, así que se recorren los atributos que contienen controles."""
    if control is None or isinstance(control, (str, int, float, bool)):
        return []
    vistos = set() if vistos is None else vistos
    if id(control) in vistos:
        return []
    vistos.add(id(control))

    encontrados = [control]
    for atributo in ("controls", "content", "actions", "title", "label", "segments", "rows", "cells"):
        hijo = getattr(control, atributo, None)
        if isinstance(hijo, (list, tuple)):
            for h in hijo:
                encontrados += _aplanar(h, vistos)
        elif hijo is not None and not isinstance(hijo, (str, int, float, bool)):
            encontrados += _aplanar(hijo, vistos)
    return encontrados


def _textos(control) -> list[str]:
    return [str(c.value) for c in _aplanar(control) if isinstance(c, ft.Text) and c.value]


def _etiquetas_columnas(vista) -> list[str]:
    return [col.label.value for col in vista.dt_deudas.columns]


def _fila(vista, indice: int):
    return vista.dt_deudas.rows[indice]


def _textos_celda(fila, columna: int) -> list[str]:
    return _textos(fila.cells[columna].content)


def _boton_fila(fila, fragmento_tooltip: str):
    """Localiza un botón de la columna de acciones por su tooltip."""
    for control in _aplanar(fila.cells[-1].content):
        tooltip = getattr(control, "tooltip", None)
        if isinstance(tooltip, str) and fragmento_tooltip.lower() in tooltip.lower():
            return control
    raise AssertionError(f"No se encontró el botón '{fragmento_tooltip}' en la fila")


def _campos_con_etiqueta(dialogo) -> dict:
    """Campos de entrada del diálogo indexados por su etiqueta. En Flet 0.86
    solo los controles de formulario tienen `label` de tipo texto."""
    campos = {}
    for control in _aplanar(dialogo.content):
        etiqueta = getattr(control, "label", None)
        if isinstance(etiqueta, str) and etiqueta:
            campos[etiqueta] = control
    return campos


def _campo(dialogo, fragmento: str):
    for etiqueta, control in _campos_con_etiqueta(dialogo).items():
        if fragmento.lower() in etiqueta.lower():
            return control
    raise AssertionError(
        f"No se encontró el campo '{fragmento}'; hay {list(_campos_con_etiqueta(dialogo))}"
    )


def _accion(dialogo, etiqueta: str):
    """En Flet 0.86 el texto de un botón vive en `content`, no en `text`."""
    for a in dialogo.actions:
        texto = getattr(a, "text", None) or getattr(a, "content", None)
        if isinstance(texto, str) and etiqueta.lower() in texto.lower():
            return a
    raise AssertionError(f"No se encontró la acción '{etiqueta}'")


def _click(dialogo, etiqueta: str, evento):
    resultado = _accion(dialogo, etiqueta).on_click(evento)
    if asyncio.iscoroutine(resultado):
        asyncio.run(resultado)


def _snacks(pagina) -> list[str]:
    """Mensajes de las notificaciones flotantes que la vista dejó en la página."""
    mensajes = []
    for control in pagina.overlay:
        if isinstance(control, ft.SnackBar):
            mensajes += _textos(control.content)
    return mensajes


class PageFalsa:
    """Emula la pila de diálogos de `flet.BasePage`."""

    def __init__(self):
        self.dialogos = []   # equivale a page._dialogs.controls
        self.overlay = []
        self.updates = 0

    def show_dialog(self, dialog):
        if dialog in self.dialogos:
            raise RuntimeError("Dialog is already opened")
        dialog.open = True
        self.dialogos.append(dialog)
        self.updates += 1

    def pop_dialog(self):
        dlg = next((d for d in reversed(self.dialogos) if d.open), None)
        if dlg is None:
            return None
        dlg.open = False
        self.updates += 1
        return dlg

    def update(self):
        self.updates += 1

    @property
    def visible(self):
        """El diálogo que Flutter pinta: el último abierto de la pila."""
        return next((d for d in reversed(self.dialogos) if d.open), None)


class EventoFalso:
    def __init__(self, page):
        self.page = page


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def cliente(db_temporal):
    return crear_cliente(
        nombre="Fulano de Tal",
        cedula_rif="V-12345678",
        direccion="Calle 1, Galpón 3",
        telefono="0414-1234567",
        correo="fulano@correo.com",
    )


@pytest.fixture
def vista(cliente):
    """La vista se construye DESPUÉS de sembrar los datos: `CarteraView.__init__`
    ya dispara `get_body()` y con él la primera carga de la tabla."""
    def _construir():
        from ui.views.cartera_view import CarteraView

        return CarteraView(user_data={"username": "cajera2", "role": "vendedor"})
    return _construir


@pytest.fixture
def pagina():
    return PageFalsa()


@pytest.fixture
def evento(pagina):
    return EventoFalso(pagina)


# ─── La pestaña existe y se renderiza ────────────────────────────────────────

def test_la_pestana_de_deudas_existe_junto_a_clientes_y_proveedores(vista):
    v = vista()
    cuerpo = v.get_body()

    segmentados = [c for c in _aplanar(cuerpo) if isinstance(c, ft.SegmentedButton)]
    assert segmentados, "la vista debe conservar el selector de pestañas"
    valores = [s.value for s in segmentados[0].segments]
    assert valores == ["clientes", "proveedores", "deudas"]
    assert "Deudas por Cobrar" in _textos(cuerpo)


def test_la_pestana_de_deudas_no_cae_al_panel_de_error(vista):
    v = vista()

    textos = _textos(v.controls[-1])
    assert not any("Error al Cargar" in t for t in textos), (
        f"la Cartera renderizó el panel de error: {[t for t in textos if 'Detalle:' in t]}"
    )


def test_alternar_a_la_pestana_de_deudas_oculta_las_otras_areas(vista):
    v = vista()

    class ControlFalso:
        selected = ["deudas"]

    class EventoFalso:
        control = ControlFalso()
        page = None

    v.handle_tab_change(EventoFalso())

    assert v._deudas_area.visible is True
    assert v._clientes_area.visible is False
    assert v._proveedores_area.visible is False


# ─── Orden de columnas del boceto ────────────────────────────────────────────

def test_el_orden_de_columnas_sigue_el_boceto_del_pdf(vista):
    """Fecha Límite | Monto a Cobrar | Cédula/Rif | Nombre | Teléfono | Etc.

    Los datos del cliente viajan agrupados de dos en dos por celda para que la
    lista entre a lo ancho sin deslizable horizontal, pero el ORDEN en que
    aparecen es el del boceto.
    """
    v = vista()
    etiquetas = _etiquetas_columnas(v)

    assert etiquetas[:7] == [
        "Fecha Límite",
        "Monto a Cobrar",
        "Cédula/RIF / Nombre o Razón Social",
        "Teléfono / Correo",
        "Dirección / Contacto Secundario",
        "Ítem Acreditado",
        "Creada / Usuario",
    ]


def test_la_fila_trae_los_datos_del_directorio_de_clientes_mas_los_de_la_deuda(vista):
    """El PDF pide "la misma información del Directorio General de Cliente" más
    el ítem acreditado, las dos fechas y el usuario que creó la deuda."""
    crear_deuda("V-12345678", 30.0, FUTURO, items=ITEMS, usuario_nombre="vendedor1")
    v = vista()
    fila = _fila(v, 0)

    assert any("V-12345678" in t for t in _textos_celda(fila, 2))
    assert any("Fulano de Tal" in t for t in _textos_celda(fila, 2))
    assert any("0414-1234567" in t for t in _textos_celda(fila, 3))
    assert any("fulano@correo.com" in t for t in _textos_celda(fila, 3))
    assert any("Calle 1" in t for t in _textos_celda(fila, 4))
    assert any("Filtro de aceite" in t for t in _textos_celda(fila, 5))
    assert any("vendedor1" in t for t in _textos_celda(fila, 6))


def test_las_filas_conservan_el_orden_por_fecha_limite_del_servicio(vista):
    """Las más urgentes primero: el orden en que hay que salir a cobrar. La
    vista no reordena lo que `listar_deudas()` ya entregó ordenado."""
    crear_deuda("V-12345678", 50.0, "15/12/2027")
    crear_deuda("V-12345678", 30.0, "01/11/2026")
    v = vista()

    assert any("01/11/2026" in t for t in _textos_celda(_fila(v, 0), 0))
    assert any("15/12/2027" in t for t in _textos_celda(_fila(v, 1), 0))


# ─── El signo de exclamación (!) de las vencidas ─────────────────────────────

def test_el_signo_de_exclamacion_marca_la_deuda_pasada_de_fecha(vista):
    crear_deuda("V-12345678", 30.0, PASADO)
    v = vista()

    textos = _textos_celda(_fila(v, 0), 0)
    assert "!" in textos
    assert any("VENCIDA" in t for t in textos)


def test_la_deuda_dentro_del_plazo_no_lleva_signo_de_exclamacion(vista):
    crear_deuda("V-12345678", 30.0, FUTURO)
    v = vista()

    textos = _textos_celda(_fila(v, 0), 0)
    assert "!" not in textos
    assert not any("VENCIDA" in t for t in textos)


def test_el_signo_aparece_solo_en_la_fila_vencida_cuando_conviven_ambas(vista):
    crear_deuda("V-12345678", 30.0, PASADO)
    crear_deuda("V-12345678", 40.0, FUTURO)
    v = vista()

    assert "!" in _textos_celda(_fila(v, 0), 0), "la vencida ordena primero y debe llevar el !"
    assert "!" not in _textos_celda(_fila(v, 1), 0)


def test_una_deuda_pagada_no_se_marca_como_vencida(vista):
    """Ya se cobró: la fecha límite dejó de importar, aunque haya pasado."""
    deuda = crear_deuda("V-12345678", 30.0, PASADO)
    registrar_abono(deuda["id"], 30.0)
    v = vista()
    v.deu_solo_abiertas.value = False
    v.refrescar_deudas()

    textos = _textos_celda(_fila(v, 0), 0)
    assert "!" not in textos
    assert any("Pagada" in t for t in textos)


# ─── "Monto a Cobrar" es el saldo vivo ───────────────────────────────────────

def test_monto_a_cobrar_muestra_el_saldo_vivo_no_el_monto_original(vista):
    """Lo que hay que cobrarle hoy al cliente es lo que queda después de los
    abonos; el monto original queda como referencia en la segunda línea."""
    deuda = crear_deuda("V-12345678", 100.0, FUTURO)
    registrar_abono(deuda["id"], 40.0)
    v = vista()

    textos = _textos_celda(_fila(v, 0), 1)
    assert "$60.00" in textos, f"se esperaba el saldo vivo, se obtuvo {textos}"
    assert any("de $100.00" in t for t in textos)
    assert any("abonado $40.00" in t for t in textos)


def test_el_total_por_cobrar_suma_solo_los_saldos_abiertos(vista):
    d1 = crear_deuda("V-12345678", 30.0, FUTURO)
    registrar_abono(d1["id"], 10.0)
    d2 = crear_deuda("V-12345678", 40.0, FUTURO)
    registrar_abono(d2["id"], 40.0)  # queda pagada
    v = vista()

    assert v.txt_deu_total.value == "$20.00"


# ─── Filtro y buscador ──────────────────────────────────────────────────────

def test_el_conmutador_solo_abiertas_oculta_las_deudas_pagadas(vista):
    pagada = crear_deuda("V-12345678", 30.0, FUTURO)
    registrar_abono(pagada["id"], 30.0)
    crear_deuda("V-12345678", 40.0, FUTURO)
    v = vista()

    assert len(v.dt_deudas.rows) == 1, "con el conmutador encendido solo se ven las abiertas"

    v.deu_solo_abiertas.value = False
    v.refrescar_deudas()
    assert len(v.dt_deudas.rows) == 2


def test_el_buscador_filtra_por_cedula_nombre_o_item_acreditado(vista):
    crear_cliente(nombre="Mengana Pérez", cedula_rif="V-87654321", telefono="0424-7654321")
    crear_deuda("V-12345678", 30.0, FUTURO, items=ITEMS)
    crear_deuda("V-87654321", 50.0, FUTURO)
    v = vista()

    assert len(v.dt_deudas.rows) == 2

    for termino, esperado in (("Mengana", 1), ("12345678", 1), ("Filtro", 1), ("no existe", 0)):
        v.deu_search.value = termino
        v.handle_buscar_deudas(None)
        assert len(v.dt_deudas.rows) == esperado, f"búsqueda '{termino}'"


def test_la_ultima_columna_es_la_de_acciones(vista):
    v = vista()
    assert _etiquetas_columnas(v)[-1] == "Acciones"


# ─── Botón Cobrar: abonos parciales ─────────────────────────────────────────

def test_cobrar_abre_el_dialogo_con_el_saldo_pendiente_a_la_vista(vista, pagina, evento):
    deuda = crear_deuda("V-12345678", 100.0, FUTURO, items=ITEMS)
    registrar_abono(deuda["id"], 40.0)
    v = vista()

    _boton_fila(_fila(v, 0), "Cobrar").on_click(evento)

    assert pagina.visible is v._dialog, "el diálogo de cobro debe ser el visible"
    textos = _textos(v._dialog.content)
    assert any("Saldo pendiente" in t for t in textos)
    assert "$60.00" in textos, f"el diálogo debe mostrar el saldo vivo: {textos}"


def test_el_dialogo_de_cobro_muestra_el_historial_de_abonos(vista, pagina, evento):
    deuda = crear_deuda("V-12345678", 100.0, FUTURO)
    registrar_abono(deuda["id"], 25.0, metodo_pago="Pago Móvil", referencia_pago="0099887766")
    v = vista()

    _boton_fila(_fila(v, 0), "Cobrar").on_click(evento)

    textos = _textos(v._dialog.content)
    assert any("Historial de abonos" in t for t in textos)
    assert any("Pago Móvil" in t and "25.00" in t for t in textos)
    assert any("0099887766" in t for t in textos)


def test_el_dialogo_de_cobro_pide_monto_metodo_y_referencia(vista, pagina, evento):
    crear_deuda("V-12345678", 100.0, FUTURO)
    v = vista()

    _boton_fila(_fila(v, 0), "Cobrar").on_click(evento)
    etiquetas = list(_campos_con_etiqueta(v._dialog))

    assert any("Monto a Abonar" in t for t in etiquetas)
    assert any("Método de Pago" in t for t in etiquetas)
    assert any("Referencia" in t and "opcional" in t for t in etiquetas)


def test_cobrar_registra_el_abono_parcial_y_refresca_la_lista(vista, pagina, evento):
    """El saldo baja, la deuda sigue abierta y la lista ya muestra el saldo
    nuevo sin que el usuario tenga que recargar nada."""
    deuda = crear_deuda("V-12345678", 100.0, FUTURO)
    v = vista()

    _boton_fila(_fila(v, 0), "Cobrar").on_click(evento)
    _campo(v._dialog, "Monto a Abonar").value = "30"
    dlg = v._dialog
    _click(dlg, "Registrar Abono", evento)

    guardada = obtener_deuda(deuda["id"])
    assert guardada["saldo_usd"] == 70.0
    assert guardada["estado"] == "abierta"
    assert dlg.open is False, "el diálogo debe cerrarse tras un abono exitoso"
    assert pagina.visible is None
    assert "$70.00" in _textos_celda(_fila(v, 0), 1), "la lista debe mostrar el saldo nuevo"


def test_el_abono_queda_firmado_con_el_usuario_de_la_sesion(vista, pagina, evento):
    """"Desde qué cuenta de usuario se cobró" es lo que vuelve auditable la
    caja chica de los fiados."""
    deuda = crear_deuda("V-12345678", 100.0, FUTURO)
    v = vista()

    _boton_fila(_fila(v, 0), "Cobrar").on_click(evento)
    _campo(v._dialog, "Monto a Abonar").value = "30"
    _click(v._dialog, "Registrar Abono", evento)

    assert obtener_deuda(deuda["id"])["abonos"][0]["usuario_nombre"] == "cajera2"


def test_el_abono_final_cierra_la_deuda_y_deshabilita_el_boton_cobrar(vista, pagina, evento):
    deuda = crear_deuda("V-12345678", 100.0, FUTURO)
    v = vista()
    v.deu_solo_abiertas.value = False
    v.refrescar_deudas(evento)

    _boton_fila(_fila(v, 0), "Cobrar").on_click(evento)
    _campo(v._dialog, "Monto a Abonar").value = "100"
    _click(v._dialog, "Registrar Abono", evento)

    assert obtener_deuda(deuda["id"])["estado"] == "pagada"
    assert _boton_fila(_fila(v, 0), "pagada").disabled is True
    assert any("PAGADA" in m for m in _snacks(pagina))


def test_un_abono_superior_al_saldo_muestra_el_error_y_no_rompe_la_vista(vista, pagina, evento):
    """Un cobro de más es un error de tipeo: el servicio lo rechaza con
    ERR_DEUDA_ABONO y la vista lo muestra dejando el diálogo abierto, con lo
    que el usuario escribió, en vez de reventar."""
    deuda = crear_deuda("V-12345678", 100.0, FUTURO)
    v = vista()

    _boton_fila(_fila(v, 0), "Cobrar").on_click(evento)
    dlg = v._dialog
    _campo(dlg, "Monto a Abonar").value = "150"
    _click(dlg, "Registrar Abono", evento)

    assert obtener_deuda(deuda["id"])["saldo_usd"] == 100.0, "no debe registrarse nada"
    assert dlg.open is True, "el diálogo debe seguir abierto para corregir el monto"
    assert pagina.visible is dlg
    assert any("ERR_DEUDA_ABONO" in m for m in _snacks(pagina))
    assert "$100.00" in _textos_celda(_fila(v, 0), 1)


def test_un_monto_ilegible_muestra_el_error_del_servicio(vista, pagina, evento):
    crear_deuda("V-12345678", 100.0, FUTURO)
    v = vista()

    _boton_fila(_fila(v, 0), "Cobrar").on_click(evento)
    _campo(v._dialog, "Monto a Abonar").value = "diez dólares"
    _click(v._dialog, "Registrar Abono", evento)

    assert any("ERR_DEUDA_MONTO" in m for m in _snacks(pagina))
    assert v._dialog.open is True


def test_cancelar_el_cobro_no_registra_nada_y_vacia_la_pila(vista, pagina, evento):
    deuda = crear_deuda("V-12345678", 100.0, FUTURO)
    v = vista()

    _boton_fila(_fila(v, 0), "Cobrar").on_click(evento)
    dlg = v._dialog
    _campo(dlg, "Monto a Abonar").value = "30"
    _click(dlg, "Cancelar", evento)

    assert obtener_deuda(deuda["id"])["saldo_usd"] == 100.0
    assert pagina.visible is None, "no debe quedar ningún diálogo dibujado"
    assert v._dialog_stack == []


def test_abonar_todo_el_saldo_precarga_el_monto_pendiente(vista, pagina, evento):
    """El campo nace vacío a propósito (un campo pre-cargado invita a cerrar de
    un clic una deuda que solo se abonó en parte); cobrar el total es una
    acción explícita."""
    deuda = crear_deuda("V-12345678", 100.0, FUTURO)
    registrar_abono(deuda["id"], 40.0)
    v = vista()

    _boton_fila(_fila(v, 0), "Cobrar").on_click(evento)
    campo = _campo(v._dialog, "Monto a Abonar")
    assert (campo.value or "") == ""

    botones = [
        c for c in _aplanar(v._dialog.content)
        if isinstance(getattr(c, "content", None), str) and "todo el saldo" in c.content
    ]
    assert botones, "debe haber un botón para abonar todo el saldo"
    botones[0].on_click(evento)
    assert campo.value == "60.00"


# ─── Botón Editar: solo fecha límite y monto total ──────────────────────────

def test_editar_solo_ofrece_fecha_limite_y_monto_total(vista, pagina, evento):
    """El saldo y el estado los deriva el servicio del historial de abonos: un
    campo para escribirlos a mano dejaría la lista mintiendo sobre lo cobrado."""
    crear_deuda("V-12345678", 100.0, FUTURO)
    v = vista()

    _boton_fila(_fila(v, 0), "Editar").on_click(evento)
    etiquetas = list(_campos_con_etiqueta(v._dialog))

    assert len(etiquetas) == 2, f"el diálogo no debe ofrecer más campos: {etiquetas}"
    assert any("Fecha Límite" in t for t in etiquetas)
    assert any("Monto Total" in t for t in etiquetas)
    assert not any("saldo" in t.lower() for t in etiquetas)
    assert not any("estado" in t.lower() for t in etiquetas)


def test_editar_precarga_la_fecha_en_dia_mes_ano_y_el_monto_actual(vista, pagina, evento):
    crear_deuda("V-12345678", 100.0, "31/12/2027")
    v = vista()

    _boton_fila(_fila(v, 0), "Editar").on_click(evento)

    assert _campo(v._dialog, "Fecha Límite").value == "31/12/2027"
    assert _campo(v._dialog, "Monto Total").value == "100.00"


def test_editar_prorroga_la_fecha_y_apaga_el_signo_de_exclamacion(vista, pagina, evento):
    deuda = crear_deuda("V-12345678", 100.0, PASADO)
    v = vista()
    assert "!" in _textos_celda(_fila(v, 0), 0)

    _boton_fila(_fila(v, 0), "Editar").on_click(evento)
    _campo(v._dialog, "Fecha Límite").value = "30/11/2027"
    dlg = v._dialog
    _click(dlg, "Guardar Cambios", evento)

    assert obtener_deuda(deuda["id"])["fecha_limite_pago"] == "2027-11-30"
    assert dlg.open is False
    assert "!" not in _textos_celda(_fila(v, 0), 0), "la lista debe reflejar la prórroga"


def test_editar_el_monto_total_rederiva_el_saldo_de_la_lista(vista, pagina, evento):
    deuda = crear_deuda("V-12345678", 100.0, FUTURO)
    registrar_abono(deuda["id"], 40.0)
    v = vista()

    _boton_fila(_fila(v, 0), "Editar").on_click(evento)
    _campo(v._dialog, "Monto Total").value = "80"
    _click(v._dialog, "Guardar Cambios", evento)

    assert obtener_deuda(deuda["id"])["saldo_usd"] == 40.0
    assert "$40.00" in _textos_celda(_fila(v, 0), 1)


def test_editar_a_un_monto_menor_que_lo_abonado_muestra_el_error(vista, pagina, evento):
    deuda = crear_deuda("V-12345678", 100.0, FUTURO)
    registrar_abono(deuda["id"], 40.0)
    v = vista()

    _boton_fila(_fila(v, 0), "Editar").on_click(evento)
    dlg = v._dialog
    _campo(dlg, "Monto Total").value = "10"
    _click(dlg, "Guardar Cambios", evento)

    assert obtener_deuda(deuda["id"])["monto_total_usd"] == 100.0
    assert dlg.open is True, "el diálogo debe seguir abierto para corregir"
    assert any("ERR_DEUDA_MONTO" in m for m in _snacks(pagina))


def test_editar_con_una_fecha_ilegible_muestra_el_error(vista, pagina, evento):
    crear_deuda("V-12345678", 100.0, FUTURO)
    v = vista()

    _boton_fila(_fila(v, 0), "Editar").on_click(evento)
    _campo(v._dialog, "Fecha Límite").value = "el mes que viene"
    _click(v._dialog, "Guardar Cambios", evento)

    assert any("ERR_DEUDA_FECHA" in m for m in _snacks(pagina))
    assert v._dialog.open is True


def test_cancelar_la_edicion_no_cambia_nada(vista, pagina, evento):
    deuda = crear_deuda("V-12345678", 100.0, FUTURO)
    v = vista()

    _boton_fila(_fila(v, 0), "Editar").on_click(evento)
    _campo(v._dialog, "Monto Total").value = "5"
    _click(v._dialog, "Cancelar", evento)

    assert obtener_deuda(deuda["id"])["monto_total_usd"] == 100.0
    assert pagina.visible is None
    assert v._dialog_stack == []


def test_buscar_vuelve_a_la_primera_pagina(vista):
    """El usuario que busca espera ver el primer resultado, no la página en la
    que se había quedado."""
    for dia in range(1, 15):
        crear_deuda("V-12345678", 10.0, f"{dia:02d}/11/2027")
    v = vista()
    v.deu_pagina_siguiente(None)
    assert v.deu_page == 2

    v.deu_search.value = ""
    v.handle_buscar_deudas(None)
    assert v.deu_page == 1
