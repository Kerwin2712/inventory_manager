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
"""
import flet as ft
import pytest

from services.cartera_service import crear_cliente
from services.deudas_service import crear_deuda, registrar_abono

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
