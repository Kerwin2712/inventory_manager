"""Flujo del Generador de Archivo por Nueva Mercancía en Gestión de Datos.

Se ejercita con un doble de página headless que emula la pila de diálogos real
de Flet 0.86 (`show_dialog` / `pop_dialog`), igual que
`test_inventario_dialogos_pila.py`: con el patrón heredado (`page.overlay` +
`open`) el cierre no se dibuja y el modal queda pegado o activo pero invisible,
y este flujo encadena tres modales (pedido → casillas → cierre).

La página también expone `session.id`, porque el borrador del pedido se aísla
por sesión: dos usuarios conectados al mismo proceso no pueden compartirlo.
"""
import types

import flet as ft
import pytest

from services import pedidos_service

PROVEEDOR = "Distribuidora Andina"


class PageFalsa:
    """Emula la pila de diálogos de `flet.BasePage` y su sesión."""

    def __init__(self, session_id="sesion-test"):
        self.dialogos = []
        self.overlay = []
        self.updates = 0
        self.session = types.SimpleNamespace(id=session_id)

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


# ── Utilidades de recorrido del árbol de controles ───────────────────────────

def _controles(control):
    """Aplana el árbol de controles de una vista o diálogo."""
    yield control
    for atributo in ("controls", "content", "actions", "title"):
        hijo = getattr(control, atributo, None)
        if isinstance(hijo, list):
            for h in hijo:
                yield from _controles(h)
        elif hijo is not None and hasattr(hijo, "_c"):
            yield from _controles(hijo)


def _textos(control) -> list[str]:
    encontrados = []
    for c in _controles(control):
        if isinstance(c, ft.Text) and c.value:
            encontrados.append(str(c.value))
        elif isinstance(getattr(c, "content", None), str):
            encontrados.append(c.content)
    return encontrados


def _boton(raiz, etiqueta: str):
    """Localiza un control clickeable por el texto que muestra (en Flet 0.86 la
    etiqueta de un botón vive en `content`, no en `text`)."""
    for c in _controles(raiz):
        if getattr(c, "on_click", None) is None:
            continue
        if etiqueta.lower() in " ".join(_textos(c)).lower():
            return c
    raise AssertionError(f"No se encontró un botón con la etiqueta '{etiqueta}'")


def _click(raiz, etiqueta: str, ev):
    _boton(raiz, etiqueta).on_click(ev)


def _campo(raiz, etiqueta: str):
    for c in _controles(raiz):
        if etiqueta.lower() in str(getattr(c, "label", "") or "").lower():
            return c
    raise AssertionError(f"No se encontró el campo '{etiqueta}'")


def _completar_casillas(dlg, cantidad="3", costo="21.5", precio="35"):
    _campo(dlg, "Cantidad recibida").value = cantidad
    _campo(dlg, "Costo USD Efectivo").value = costo
    _campo(dlg, "Costo USD BCV").value = costo
    _campo(dlg, "Precio Venta USD Efectivo").value = precio
    _campo(dlg, "Precio Venta USD BCV").value = precio


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def borradores_limpios():
    yield
    pedidos_service._sesiones.clear()


@pytest.fixture
def banco_de_datos(db_temporal):
    from services.cartera_service import crear_proveedor
    from services.inventario_service import crear_producto

    crear_proveedor(empresa=PROVEEDOR, telefono="0412-5550000", rif="J-123456789")
    crear_producto(
        codigo="TUB-001",
        referencia="REF-TUB-001",
        descripcion_general="Tubo de escape universal",
        departamento="Repuestos",
        marca="Bosch",
        precio_dolares=30.0,
        precio_bcv=33.0,
        existencia=4.0,
        nombre_referencia_corto="Tubo escape",
        costo_usd_efectivo=20.0,
        rol_usuario="administrador",
    )
    return "TUB-001"


def _nueva_vista(rol="vendedor"):
    from ui.views.gestion_datos_view import GestionDatosView

    return GestionDatosView(user_data={"role": rol})


@pytest.fixture
def vista(banco_de_datos):
    """La vista la usa un VENDEDOR: el generador está disponible para todos los
    roles porque no modifica el stock (es el punto del requisito)."""
    return _nueva_vista("vendedor")


@pytest.fixture
def pagina():
    return PageFalsa()


@pytest.fixture
def evento(pagina):
    return EventoFalso(pagina)


def _abrir_generador(vista, evento):
    vista.mostrar_generador_pedido(evento)
    return vista._dialog


def _agregar_item_desde_la_vista(vista, evento, cantidad="3"):
    dlg_pedido = _abrir_generador(vista, evento)
    _campo(dlg_pedido, "Buscar item registrado").value = "TUB-001"
    _click(dlg_pedido, "Buscar", evento)
    _click(vista._pedido_resultados_col, "Agregar al pedido", evento)
    dlg_renglon = vista._dialog
    _completar_casillas(dlg_renglon, cantidad=cantidad)
    _click(dlg_renglon, "Agregar al pedido", evento)
    return dlg_pedido


# ── La tarjeta está disponible para todos los roles ──────────────────────────

@pytest.mark.parametrize("rol", ["administrador", "vendedor"])
def test_la_tarjeta_del_generador_se_ofrece_a_todos_los_roles(banco_de_datos, rol):
    vista = _nueva_vista(rol)

    textos = " ".join(_textos(vista.get_body()))
    assert "Generador de Archivo por Nueva Mercancía" in textos
    assert "ARMAR PEDIDO DE NUEVA MERCANCÍA" in textos


# ── Armado del pedido ────────────────────────────────────────────────────────

def test_abrir_el_generador_apila_el_dialogo_en_la_pagina(vista, pagina, evento):
    dlg = _abrir_generador(vista, evento)

    assert pagina.visible is dlg
    assert dlg.open is True


def test_buscar_lista_los_items_del_banco_de_datos(vista, pagina, evento):
    dlg = _abrir_generador(vista, evento)
    _campo(dlg, "Buscar item registrado").value = "escape"

    _click(dlg, "Buscar", evento)

    assert "TUB-001" in " ".join(_textos(vista._pedido_resultados_col))


def test_una_busqueda_sin_coincidencias_sugiere_el_alta_manual(vista, pagina, evento):
    dlg = _abrir_generador(vista, evento)
    _campo(dlg, "Buscar item registrado").value = "no-existe-nada"

    _click(dlg, "Buscar", evento)

    assert "Agregar mercancía nueva" in " ".join(_textos(vista._pedido_resultados_col))


def test_el_dialogo_de_casillas_queda_encima_y_trae_la_marca_prerrellenada(vista, pagina, evento):
    dlg_pedido = _abrir_generador(vista, evento)
    _campo(dlg_pedido, "Buscar item registrado").value = "TUB-001"
    _click(dlg_pedido, "Buscar", evento)

    _click(vista._pedido_resultados_col, "Agregar al pedido", evento)

    dlg_renglon = vista._dialog
    assert pagina.visible is dlg_renglon
    assert dlg_renglon is not dlg_pedido
    assert _campo(dlg_renglon, "Marca").value == "Bosch"


def test_agregar_un_renglon_lo_muestra_en_el_pedido_y_devuelve_el_asistente(vista, pagina, evento):
    dlg_pedido = _agregar_item_desde_la_vista(vista, evento, cantidad="3")

    renglones = pedidos_service.obtener_renglones("sesion-test")
    assert [(r["codigo"], r["cantidad"]) for r in renglones] == [("TUB-001", 3.0)]
    assert pagina.visible is dlg_pedido, "al cerrar las casillas vuelve el pedido"
    assert "TUB-001" in " ".join(_textos(vista._pedido_lista_col))


def test_una_cantidad_invalida_no_cierra_el_dialogo_ni_agrega_el_renglon(vista, pagina, evento):
    dlg_pedido = _abrir_generador(vista, evento)
    _campo(dlg_pedido, "Buscar item registrado").value = "TUB-001"
    _click(dlg_pedido, "Buscar", evento)
    _click(vista._pedido_resultados_col, "Agregar al pedido", evento)
    dlg_renglon = vista._dialog
    _completar_casillas(dlg_renglon, cantidad="0")

    _click(dlg_renglon, "Agregar al pedido", evento)

    assert pagina.visible is dlg_renglon, "el diálogo debe seguir abierto para corregir"
    assert pedidos_service.obtener_renglones("sesion-test") == []
    assert any("ERR_PEDIDO_CANT" in t for t in _textos(dlg_renglon))


def test_editar_un_renglon_desde_el_pedido_actualiza_sus_casillas(vista, pagina, evento):
    _agregar_item_desde_la_vista(vista, evento)

    _click(vista._pedido_lista_col, "Editar", evento)
    dlg_edicion = vista._dialog
    _campo(dlg_edicion, "Cantidad recibida").value = "12"
    _campo(dlg_edicion, "Marca").value = "Monroe"
    _click(dlg_edicion, "Guardar cambios", evento)

    renglon = pedidos_service.obtener_renglones("sesion-test")[0]
    assert renglon["cantidad"] == 12
    assert renglon["marca"] == "Monroe"


def test_quitar_un_renglon_lo_saca_del_pedido(vista, pagina, evento):
    _agregar_item_desde_la_vista(vista, evento)

    _click(vista._pedido_lista_col, "Quitar", evento)

    assert pedidos_service.obtener_renglones("sesion-test") == []
    assert "El pedido está vacío" in " ".join(_textos(vista._pedido_lista_col))


# ── Alta manual de mercancía nueva ───────────────────────────────────────────

def test_el_alta_manual_agrega_un_renglon_de_mercancia_no_registrada(vista, pagina, evento):
    dlg_pedido = _abrir_generador(vista, evento)

    _click(dlg_pedido, "Agregar mercancía nueva", evento)
    dlg_manual = vista._dialog
    _campo(dlg_manual, "Código (obligatorio)").value = "AMO-77"
    _campo(dlg_manual, "Descripción General").value = "Amortiguador trasero reforzado"
    _completar_casillas(dlg_manual, cantidad="2")
    _click(dlg_manual, "Agregar al pedido", evento)

    renglon = pedidos_service.obtener_renglones("sesion-test")[0]
    assert renglon["codigo"] == "AMO-77"
    assert renglon["origen"] == "manual"
    assert pagina.visible is dlg_pedido
    assert "(nueva)" in " ".join(_textos(vista._pedido_lista_col))


def test_el_alta_manual_sin_codigo_avisa_y_no_agrega_nada(vista, pagina, evento):
    dlg_pedido = _abrir_generador(vista, evento)
    _click(dlg_pedido, "Agregar mercancía nueva", evento)
    dlg_manual = vista._dialog
    _campo(dlg_manual, "Descripción General").value = "Pieza sin código"
    _completar_casillas(dlg_manual, cantidad="1")

    _click(dlg_manual, "Agregar al pedido", evento)

    assert pedidos_service.obtener_renglones("sesion-test") == []
    assert any("ERR_PEDIDO_MANUAL" in t for t in _textos(dlg_manual))


# ── Cierre del pedido: proveedor y fecha una sola vez ────────────────────────

def test_el_cierre_pide_el_proveedor_y_la_fecha_una_sola_vez(vista, pagina, evento):
    _agregar_item_desde_la_vista(vista, evento)

    _click(vista._pedido_dlg, "CERRAR PEDIDO Y EXPORTAR", evento)

    dlg_cierre = vista._dialog
    assert pagina.visible is dlg_cierre
    assert _campo(dlg_cierre, "Proveedor").options[0].key == PROVEEDOR
    assert _campo(dlg_cierre, "Fecha de Recepción").value, "la fecha arranca con el día de hoy"


def test_cerrar_sin_elegir_proveedor_avisa_y_no_exporta(vista, pagina, evento, monkeypatch):
    _agregar_item_desde_la_vista(vista, evento)
    _click(vista._pedido_dlg, "CERRAR PEDIDO Y EXPORTAR", evento)
    dlg_cierre = vista._dialog

    llamadas = []
    monkeypatch.setattr(vista, "abrir_dialogo_guardado", lambda *a, **k: llamadas.append(a))

    _click(dlg_cierre, "GENERAR ARCHIVO EXCEL", evento)

    assert llamadas == [], "no debe llegar al diálogo de guardado sin proveedor"
    assert pagina.visible is dlg_cierre
    assert any("ERR_PEDIDO_PROV" in t for t in _textos(dlg_cierre))


def test_una_fecha_mal_escrita_avisa_y_no_exporta(vista, pagina, evento, monkeypatch):
    _agregar_item_desde_la_vista(vista, evento)
    _click(vista._pedido_dlg, "CERRAR PEDIDO Y EXPORTAR", evento)
    dlg_cierre = vista._dialog
    _campo(dlg_cierre, "Proveedor").value = PROVEEDOR
    _campo(dlg_cierre, "Fecha de Recepción").value = "2026-10-17"

    monkeypatch.setattr(vista, "abrir_dialogo_guardado", lambda *a, **k: pytest.fail("no debe pedir ruta"))

    _click(dlg_cierre, "GENERAR ARCHIVO EXCEL", evento)

    assert any("ERR_PEDIDO_FECHA" in t for t in _textos(dlg_cierre))


def test_el_pedido_vacio_no_abre_el_cierre(vista, pagina, evento):
    dlg_pedido = _abrir_generador(vista, evento)

    _click(dlg_pedido, "CERRAR PEDIDO Y EXPORTAR", evento)

    assert vista._dialog is dlg_pedido, "no debe apilarse el diálogo de cierre"


def test_el_flujo_completo_de_un_vendedor_genera_el_archivo(vista, pagina, evento, monkeypatch, tmp_path):
    """Recorrido entero del requisito: el empleado busca el item, completa las
    pocas casillas, cierra con proveedor y fecha, y se lleva el Excel."""
    ruta = tmp_path / "pedido_vendedor.xlsx"
    monkeypatch.setattr(vista, "abrir_dialogo_guardado", lambda *a, **k: str(ruta))

    _agregar_item_desde_la_vista(vista, evento, cantidad="6")
    _click(vista._pedido_dlg, "CERRAR PEDIDO Y EXPORTAR", evento)
    dlg_cierre = vista._dialog
    _campo(dlg_cierre, "Proveedor").value = PROVEEDOR
    _campo(dlg_cierre, "Fecha de Recepción").value = "17/10/2026"

    _click(dlg_cierre, "GENERAR ARCHIVO EXCEL", evento)

    assert ruta.exists()
    assert pagina.visible is None, "no debe quedar ningún diálogo dibujado"
    assert vista._dialog_stack == []
    # El borrador se descarta: el siguiente pedido no arranca con lo anterior.
    assert pedidos_service.obtener_renglones("sesion-test") == []


def test_el_archivo_generado_desde_la_vista_entra_por_la_carga_masiva(
    vista, pagina, evento, monkeypatch, tmp_path
):
    from services.importacion_service import procesar_importacion_excel
    from services.inventario_service import obtener_producto

    ruta = tmp_path / "pedido.xlsx"
    monkeypatch.setattr(vista, "abrir_dialogo_guardado", lambda *a, **k: str(ruta))
    _agregar_item_desde_la_vista(vista, evento, cantidad="6")
    _click(vista._pedido_dlg, "CERRAR PEDIDO Y EXPORTAR", evento)
    dlg_cierre = vista._dialog
    _campo(dlg_cierre, "Proveedor").value = PROVEEDOR
    _campo(dlg_cierre, "Fecha de Recepción").value = "17/10/2026"
    _click(dlg_cierre, "GENERAR ARCHIVO EXCEL", evento)

    resultado = procesar_importacion_excel(str(ruta))

    assert resultado["exito"] is True, resultado["mensaje"]
    assert obtener_producto("TUB-001")["existencia"] == 6


def test_armar_y_exportar_desde_la_vista_no_toca_el_inventario(
    vista, pagina, evento, monkeypatch, tmp_path
):
    """Un vendedor recorre todo el flujo: el stock queda intacto hasta que el
    Administrador decida importar el archivo."""
    from core.database import get_connection

    def foto():
        with get_connection() as conn:
            return [tuple(f) for f in conn.execute(
                "SELECT codigo, existencia, precio_dolares, marca FROM productos ORDER BY codigo"
            ).fetchall()]

    antes = foto()
    monkeypatch.setattr(vista, "abrir_dialogo_guardado", lambda *a, **k: str(tmp_path / "p.xlsx"))

    _agregar_item_desde_la_vista(vista, evento, cantidad="99")
    _click(vista._pedido_dlg, "CERRAR PEDIDO Y EXPORTAR", evento)
    dlg_cierre = vista._dialog
    _campo(dlg_cierre, "Proveedor").value = PROVEEDOR
    _campo(dlg_cierre, "Fecha de Recepción").value = "17/10/2026"
    _click(dlg_cierre, "GENERAR ARCHIVO EXCEL", evento)

    assert foto() == antes
    assert antes == [("TUB-001", 4.0, 30.0, "Bosch")]


# ── Aislamiento entre sesiones desde la vista ────────────────────────────────

def test_dos_sesiones_de_la_aplicacion_no_comparten_el_pedido(banco_de_datos):
    """Dos pestañas conectadas al mismo proceso Flet arman pedidos distintos."""
    vista_a, vista_b = _nueva_vista(), _nueva_vista()
    evento_a = EventoFalso(PageFalsa("sesion-A"))
    evento_b = EventoFalso(PageFalsa("sesion-B"))

    _agregar_item_desde_la_vista(vista_a, evento_a, cantidad="4")
    _agregar_item_desde_la_vista(vista_b, evento_b, cantidad="9")

    assert pedidos_service.obtener_renglones("sesion-A")[0]["cantidad"] == 4
    assert pedidos_service.obtener_renglones("sesion-B")[0]["cantidad"] == 9


def test_cerrar_el_asistente_sin_exportar_conserva_el_borrador(vista, pagina, evento):
    _agregar_item_desde_la_vista(vista, evento)

    _click(vista._pedido_dlg, "Cerrar sin exportar", evento)

    assert pagina.visible is None
    assert len(pedidos_service.obtener_renglones("sesion-test")) == 1
