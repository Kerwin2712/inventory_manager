"""Ciclo de vida de los diálogos del Inventario sobre la pila de la página.

Los tests de la máquina de estados observan `_dialog_stack` y las banderas
`open`, pero no cómo se monta y desmonta el diálogo en la página — y ahí vivía
un bug que solo se veía con la app corriendo: con el patrón heredado
(`page.overlay` + `open`), Flet no llegaba a dibujar el cierre. El aviso de
código duplicado se quedaba pegado en pantalla, y en una variante quedaba
activo pero INVISIBLE, recibiendo clics sobre botones que ya no se veían.

La `PageFalsa` de aquí emula la API real de Flet 0.86 (`show_dialog` /
`pop_dialog`, con su propia pila) para que estas pruebas ejerciten el mismo
camino que la aplicación.
"""
import asyncio

import pytest


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


def _accion(dlg, etiqueta: str):
    """Localiza un botón por su etiqueta (en Flet 0.86 el texto de un botón
    vive en `content`, no en `text`)."""
    for a in dlg.actions:
        texto = getattr(a, "text", None) or getattr(a, "content", None)
        if isinstance(texto, str) and etiqueta.lower() in texto.lower():
            return a
    raise AssertionError(f"No se encontró la acción '{etiqueta}'")


def _click(dlg, etiqueta: str, ev):
    resultado = _accion(dlg, etiqueta).on_click(ev)
    if asyncio.iscoroutine(resultado):
        asyncio.run(resultado)


@pytest.fixture
def vista(db_temporal):
    from ui.views.inventario_view import InventarioView

    v = InventarioView(es_admin=True)
    v.get_body()
    return v


@pytest.fixture
def pagina():
    return PageFalsa()


@pytest.fixture
def evento(pagina):
    return EventoFalso(pagina)


@pytest.fixture
def producto_duplicado(db_temporal):
    from services.inventario_service import crear_producto

    crear_producto(
        codigo="DUP-PILA",
        referencia="REF",
        descripcion_general="Producto duplicado de prueba",
        departamento="Pruebas",
        precio_dolares=10.0,
    )
    return "DUP-PILA"


def _campo_codigo(dlg):
    return next(c for c in dlg.content.controls if hasattr(c, "label") and c.label)


def test_abrir_muestra_el_dialogo_en_la_pila_de_la_pagina(vista, pagina, evento):
    vista._abrir_flujo_ingreso(evento)

    assert pagina.visible is vista._dialog
    assert vista._dialog.open is True


def test_el_aviso_de_duplicado_queda_encima_y_es_el_que_se_ve(vista, pagina, evento, producto_duplicado):
    vista._abrir_flujo_ingreso(evento)
    dlg_paso1 = vista._dialog
    _campo_codigo(dlg_paso1).value = producto_duplicado

    _click(dlg_paso1, "Verificar", evento)

    assert vista._dialog_stack == [dlg_paso1, vista._dialog]
    assert pagina.visible is vista._dialog, "el aviso debe ser el diálogo visible"
    assert pagina.visible is not dlg_paso1


def test_descartar_el_aviso_devuelve_la_vista_al_paso1_con_el_codigo_limpio(
    vista, pagina, evento, producto_duplicado
):
    """Regresión del bug reportado: tras "No — Limpiar Código" el usuario debe
    recuperar el paso 1 utilizable, no quedarse atrapado."""
    vista._abrir_flujo_ingreso(evento)
    dlg_paso1 = vista._dialog
    campo = _campo_codigo(dlg_paso1)
    campo.value = producto_duplicado
    _click(dlg_paso1, "Verificar", evento)
    dlg_dup = vista._dialog

    _click(dlg_dup, "No — Limpiar", evento)

    assert dlg_dup.open is False, "el aviso debe cerrarse"
    assert pagina.visible is dlg_paso1, "el paso 1 debe volver a ser el visible"
    assert vista._dialog is dlg_paso1
    assert (campo.value or "") == ""


def test_cancelar_el_paso1_tras_el_aviso_no_deja_ningun_dialogo_visible(
    vista, pagina, evento, producto_duplicado
):
    vista._abrir_flujo_ingreso(evento)
    dlg_paso1 = vista._dialog
    _campo_codigo(dlg_paso1).value = producto_duplicado
    _click(dlg_paso1, "Verificar", evento)
    _click(vista._dialog, "No — Limpiar", evento)

    _click(dlg_paso1, "Cancelar", evento)

    assert pagina.visible is None, "no debe quedar ningún diálogo dibujado"
    assert vista._dialog_stack == []
    assert vista._form_codigo_verificado is False
    assert vista._editing_codigo is None
