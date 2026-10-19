"""Diálogos de `BaseView` sobre la API de pila nativa de Flet 0.86.

Por qué existe este archivo: en Flet 0.86 el patrón heredado de meter el
`AlertDialog` en `page.overlay` y alternar su propiedad `open` **no dibuja el
cierre**. El síntoma real que ya se vio en producción fue un diálogo que
quedaba pegado en pantalla y, en una variante, uno activo pero invisible que
recibía clics sobre botones que el usuario ya no veía. La vista de Inventario
se migró en septiembre; el modal global de la Tasa BCV se había quedado atrás,
y lo usan ahora el área de Inicio y el de Inventario.

El doble de página emula la pila real de Flet (`show_dialog`/`pop_dialog`) para
que las pruebas recorran el mismo camino que la aplicación: verificar las
banderas `open` no habría detectado nunca el defecto original.
"""
import flet as ft
import pytest

from ui.views.base_view import BaseView


class PaginaFalsa:
    """Doble de `ft.Page` con su propia pila de diálogos.

    `pop_dialog` replica la semántica que importa: cierra el diálogo más alto
    que SIGA abierto. Es justamente esa semántica la que obliga a llamarlo
    antes de bajar la bandera `open`.
    """

    def __init__(self):
        self.overlay = []
        self.pila = []
        self.updates = 0

    def show_dialog(self, dialog):
        self.pila.append(dialog)

    def pop_dialog(self):
        for dialog in reversed(self.pila):
            if getattr(dialog, "open", False):
                self.pila.remove(dialog)
                return dialog
        return None

    def update(self):
        self.updates += 1


class PaginaSinPila:
    """Doble de una página que NO expone la API de diálogos, para comprobar
    que el respaldo por `overlay` sigue funcionando."""

    def __init__(self):
        self.overlay = []
        self.updates = 0

    def update(self):
        self.updates += 1


class VistaDePrueba(BaseView):
    """Vista mínima: `BaseView` es abstracta en el cuerpo, no en los helpers
    de diálogo que queremos ejercitar."""

    def __init__(self, pagina):
        BaseView.ensure_settings_loaded()
        super().__init__(route="/prueba", title="Prueba")
        self._pagina = pagina

    def get_current_page(self, e=None):
        return self._pagina

    def get_body(self) -> ft.Control:
        return ft.Text("cuerpo")


@pytest.fixture
def vista(db_temporal):
    return VistaDePrueba(PaginaFalsa())


def _dialogo(titulo="Uno"):
    return ft.AlertDialog(title=ft.Text(titulo))


# ─── Apertura y cierre por la pila ───────────────────────────────────────────

def test_abrir_usa_la_pila_y_no_el_overlay(vista):
    dlg = _dialogo()
    vista.abrir_dialogo(dlg)
    assert dlg in vista._pagina.pila
    assert dlg not in vista._pagina.overlay
    assert dlg.open is True


def test_cerrar_saca_el_dialogo_de_la_pila(vista):
    dlg = _dialogo()
    vista.abrir_dialogo(dlg)
    vista.cerrar_dialogo(dlg)
    assert dlg not in vista._pagina.pila
    assert dlg.open is False


def test_cerrar_descarta_el_de_arriba_y_no_el_de_abajo(vista):
    """El bug original: bajar la bandera antes de llamar a `pop_dialog` hace
    que Flet encuentre como tope el diálogo de ABAJO y cierre el equivocado."""
    abajo, arriba = _dialogo("Abajo"), _dialogo("Arriba")
    vista.abrir_dialogo(abajo)
    vista.abrir_dialogo(arriba)

    vista.cerrar_dialogo(arriba)

    assert arriba not in vista._pagina.pila
    assert abajo in vista._pagina.pila
    assert abajo.open is True


def test_abrir_dos_veces_el_mismo_dialogo_no_lo_duplica(vista):
    dlg = _dialogo()
    vista.abrir_dialogo(dlg)
    vista.abrir_dialogo(dlg)
    assert vista._pagina.pila.count(dlg) <= 1


def test_sin_pagina_no_revienta(db_temporal):
    vista = VistaDePrueba(None)
    dlg = _dialogo()
    vista.abrir_dialogo(dlg)      # no debe lanzar
    vista.cerrar_dialogo(dlg)
    assert dlg.open is False


def test_respaldo_por_overlay_en_paginas_sin_api_de_pila(db_temporal):
    """Una página que no expone `show_dialog`/`pop_dialog` sigue atendida por
    el camino viejo: el helper degrada, no falla."""
    vista = VistaDePrueba(PaginaSinPila())
    dlg = _dialogo()

    vista.abrir_dialogo(dlg)
    assert dlg in vista._pagina.overlay
    assert dlg.open is True

    vista.cerrar_dialogo(dlg)
    assert dlg not in vista._pagina.overlay
    assert dlg.open is False


# ─── El modal de la Tasa BCV, que era el que seguía en el patrón viejo ──────

def test_el_modal_de_tasa_se_monta_en_la_pila(vista):
    vista.mostrar_modal_tasa_bcv()
    assert len(vista._pagina.pila) == 1
    assert vista._pagina.overlay == []


def test_cancelar_el_modal_de_tasa_lo_cierra_de_verdad(vista):
    vista.mostrar_modal_tasa_bcv()
    dlg = vista._pagina.pila[-1]

    boton_cancelar = dlg.actions[0]
    boton_cancelar.on_click(None)

    assert dlg not in vista._pagina.pila
    assert dlg.open is False


def test_guardar_una_tasa_valida_cierra_el_modal_y_persiste(vista):
    from services.bcv_service import obtener_estado_tasa

    vista.mostrar_modal_tasa_bcv()
    dlg = vista._pagina.pila[-1]

    campo = dlg.content.content.controls[2]
    campo.value = "732,48"
    dlg.actions[1].on_click(None)

    assert dlg not in vista._pagina.pila
    assert obtener_estado_tasa()["tasa"] == pytest.approx(732.48)


def test_una_tasa_invalida_no_cierra_el_modal_y_muestra_el_error(vista):
    """El usuario tiene que poder corregir sin perder el diálogo."""
    vista.mostrar_modal_tasa_bcv()
    dlg = vista._pagina.pila[-1]

    campo = dlg.content.content.controls[2]
    etiqueta_error = dlg.content.content.controls[3]
    campo.value = "cero"
    dlg.actions[1].on_click(None)

    assert dlg in vista._pagina.pila
    assert etiqueta_error.value


def test_una_tasa_cero_o_negativa_se_rechaza(vista):
    vista.mostrar_modal_tasa_bcv()
    dlg = vista._pagina.pila[-1]
    campo = dlg.content.content.controls[2]
    etiqueta_error = dlg.content.content.controls[3]

    for valor in ("0", "-5"):
        etiqueta_error.value = ""
        campo.value = valor
        dlg.actions[1].on_click(None)
        assert dlg in vista._pagina.pila
        assert etiqueta_error.value


def test_el_callback_recibe_la_tasa_guardada(vista):
    recibidas = []
    vista.mostrar_modal_tasa_bcv(callback_al_guardar=recibidas.append)
    dlg = vista._pagina.pila[-1]

    campo = dlg.content.content.controls[2]
    campo.value = "100"
    dlg.actions[1].on_click(None)

    assert recibidas == [pytest.approx(100.0)]
