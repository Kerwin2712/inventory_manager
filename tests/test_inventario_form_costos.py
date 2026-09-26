"""Pruebas del guardado completo desde el formulario de Inventario.

Bug que cubren: con la regla `ERR_PROD_COSTO` (todo producto con existencia
>= 1 necesita su Costo USD Efectivo), el paso 2 no recogía ningún costo, así
que NINGÚN producto con stock podía guardarse desde la interfaz. Ahora el
formulario captura costos (solo para roles administrativos) y la alerta de
stock mínimo, y avisa junto al campo antes de llegar al paso 3.
"""
import flet as ft
import pytest

from services.inventario_service import obtener_producto
from ui.components.selector_departamentos import OPCION_NUEVO_DEPARTAMENTO


def _vista(es_admin: bool, rol: str | None):
    from ui.views.inventario_view import InventarioView

    v = InventarioView(es_admin=es_admin, rol_usuario=rol)
    v.get_body()
    return v


@pytest.fixture
def vista_admin(db_temporal):
    return _vista(True, "administrador")


@pytest.fixture
def vista_vendedor(db_temporal):
    return _vista(False, "vendedor")


def _campos(dlg: ft.AlertDialog) -> dict:
    encontrados = {}

    def caminar(control):
        if isinstance(control, ft.TextField) and control.label:
            encontrados[control.label] = control
        for hijo in (getattr(control, "controls", None) or []):
            caminar(hijo)
        contenido = getattr(control, "content", None)
        if isinstance(contenido, ft.Control):
            caminar(contenido)

    caminar(dlg.content)
    return encontrados


def _click(dlg: ft.AlertDialog, etiqueta: str, ev=None):
    for accion in dlg.actions:
        texto = getattr(accion, "text", None) or getattr(accion, "content", None)
        if isinstance(texto, str) and etiqueta.lower() in texto.lower():
            return accion.on_click(ev)
    raise AssertionError(f"No se encontró la acción '{etiqueta}'")


def _rellenar(vista, codigo, *, existencia="10", costo="7.5", alerta="", precio="12"):
    vista._mostrar_paso2_dialogo(None, codigo=codigo)
    dlg = vista._dialog
    campos = _campos(dlg)
    campos["Referencia *"].value = f"REF-{codigo}"
    campos["Descripción General *"].value = "Producto de prueba"
    campos["Existencia"].value = existencia
    campos["Precio USD (Efectivo)"].value = precio
    if alerta:
        campos["Alerta de Stock Mínimo"].value = alerta
    if costo is not None and "Costo USD (Efectivo) *" in campos:
        campos["Costo USD (Efectivo) *"].value = costo
    # Base virgen: se registra el departamento con la opción "Registrar nuevo".
    selector = vista._selector_depto
    selector.dd_departamento.value = OPCION_NUEVO_DEPARTAMENTO
    selector.manejar_cambio_departamento()
    selector.tf_nuevo_departamento.value = "Ferretería"
    return dlg, campos


# ─────────────────────────────────────────────────────────────────────────────
# El formulario expone los campos que la regla de negocio exige
# ─────────────────────────────────────────────────────────────────────────────
def test_el_paso2_de_un_admin_ofrece_los_campos_de_costo(vista_admin):
    vista_admin._mostrar_paso2_dialogo(None, codigo="C-001")
    campos = _campos(vista_admin._dialog)

    assert "Costo USD (Efectivo) *" in campos
    assert "Costo USD (BCV)" in campos
    assert "Alerta de Stock Mínimo" in campos


def test_la_fila_de_costos_esta_oculta_para_un_vendedor(vista_vendedor):
    vista_vendedor._mostrar_paso2_dialogo(None, codigo="C-002")
    filas = vista_vendedor._dialog.content.content.controls
    campos = _campos(vista_vendedor._dialog)

    fila_costos = next(
        f for f in filas
        if isinstance(f, ft.Row) and campos.get("Costo USD (BCV)") in (f.controls or [])
    )
    assert fila_costos.visible is False
    # La alerta de stock NO es un dato restringido: sigue disponible.
    assert campos["Alerta de Stock Mínimo"].visible is not False


# ─────────────────────────────────────────────────────────────────────────────
# Guardado con existencia: el flujo completo llega a la base
# ─────────────────────────────────────────────────────────────────────────────
def test_un_admin_guarda_un_producto_con_stock_de_punta_a_punta(vista_admin):
    dlg_paso2, _ = _rellenar(vista_admin, "FULL-001", existencia="10", costo="7.5", alerta="3")

    _click(dlg_paso2, "Revisar y Guardar")
    _click(vista_admin._dialog, "Aceptar")

    guardado = obtener_producto("FULL-001", rol_usuario="administrador")
    assert guardado is not None, "el producto con stock debe haberse guardado"
    assert guardado["existencia"] == 10
    assert guardado["costo_usd_efectivo"] == 7.5
    assert guardado["alerta_stock_minimo"] == 3
    assert guardado["departamento"] == "Ferretería"
    assert vista_admin._dialog_stack == []


def test_el_costo_falta_y_el_formulario_avisa_junto_al_campo(vista_admin):
    dlg_paso2, campos = _rellenar(vista_admin, "SIN-COSTO", existencia="5", costo=None)

    _click(dlg_paso2, "Revisar y Guardar")

    assert vista_admin._dialog is dlg_paso2, "no debe avanzar al paso 3"
    assert campos["Costo USD (Efectivo) *"].error_text == "Requerido si Existencia >= 1"
    assert obtener_producto("SIN-COSTO") is None


def test_sin_existencia_el_costo_no_es_obligatorio(vista_admin):
    dlg_paso2, _ = _rellenar(vista_admin, "SIN-STOCK", existencia="0", costo=None, precio="0")

    _click(dlg_paso2, "Revisar y Guardar")
    _click(vista_admin._dialog, "Aceptar")

    guardado = obtener_producto("SIN-STOCK", rol_usuario="administrador")
    assert guardado is not None
    assert guardado["costo_usd_efectivo"] is None


def test_el_resumen_del_paso3_no_muestra_las_etiquetas_de_costo_a_un_vendedor(vista_vendedor):
    dlg_paso2, _ = _rellenar(vista_vendedor, "VEND-001", existencia="0", costo=None, precio="0")

    _click(dlg_paso2, "Revisar y Guardar")

    etiquetas = [
        fila.controls[0].value for fila in vista_vendedor._dialog.content.content.controls
    ]
    assert not any("Costo" in et for et in etiquetas)
    assert "Alerta de Stock Mínimo:" in etiquetas


def test_un_admin_ve_sus_costos_al_reabrir_la_edicion(vista_admin):
    from services.inventario_service import crear_producto

    crear_producto(
        codigo="EDIT-COSTO", referencia="R", descripcion_general="D",
        departamento="Ferretería", existencia=4, precio_dolares=9.0,
        costo_usd_efectivo=6.25, rol_usuario="administrador",
    )

    vista_admin._abrir_flujo_edicion("EDIT-COSTO", None)
    campos = _campos(vista_admin._dialog)

    assert campos["Costo USD (Efectivo) *"].value == "6.25"


def test_un_vendedor_edita_sin_pisar_el_costo_almacenado(db_temporal):
    """`None` en un costo significa "no modificar": el costo sobrevive a una
    edición hecha por un rol que no puede verlo."""
    from services.inventario_service import crear_producto

    crear_producto(
        codigo="PRES-001", referencia="R", descripcion_general="D",
        departamento="Ferretería", existencia=4, precio_dolares=9.0,
        costo_usd_efectivo=6.25, rol_usuario="administrador",
    )
    vista = _vista(False, "vendedor")

    vista._abrir_flujo_edicion("PRES-001", None)
    dlg_paso2 = vista._dialog
    _campos(dlg_paso2)["Descripción General *"].value = "Descripción corregida"
    _click(dlg_paso2, "Revisar y Guardar")
    _click(vista._dialog, "Aceptar")

    guardado = obtener_producto("PRES-001", rol_usuario="administrador")
    assert guardado["descripcion_general"] == "Descripción corregida"
    assert guardado["costo_usd_efectivo"] == 6.25, "el costo almacenado se perdió"
