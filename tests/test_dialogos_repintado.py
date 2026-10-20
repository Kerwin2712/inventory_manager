"""Un diálogo abierto desde el teclado tiene que dibujarse en el momento.

`page.show_dialog()` apila el diálogo pero NO redibuja la página. Tras un clic
eso no se nota, porque Flet repinta al terminar el handler del control; pero un
atajo de teclado no cuelga de ningún control, así que nadie repinta.

El síntoma, visto en la aplicación real: se pulsa F1 sobre un ítem marcado, el
diálogo se abre de verdad —la acción se ejecutó— y la pantalla no cambia. El
usuario concluye que la tecla no hace nada; el diálogo aparece después, al
primer clic en cualquier parte, como si la aplicación se hubiera trabado. Es
primo del defecto de septiembre: el estado es correcto y lo que falla es el
dibujo, que es justo lo que las pruebas de banderas no ven.

Lo mismo al cerrar: Esc cierra desde el teclado.
"""
import flet as ft
import pytest

from ui.views.cartera_view import CarteraView
from ui.views.gestion_datos_view import GestionDatosView
from ui.views.inventario_view import InventarioView
from ui.views.ventas_view import VentasView


class PaginaContadora:
    """Doble de página que cuenta los repintados además de apilar diálogos."""

    def __init__(self):
        self.dialogos = []
        self.overlay = []
        self.updates = 0
        self.on_keyboard_event = None

    def show_dialog(self, dialog):
        dialog.open = True
        self.dialogos.append(dialog)

    def pop_dialog(self):
        dlg = next((d for d in reversed(self.dialogos) if d.open), None)
        if dlg is not None:
            dlg.open = False
        return dlg

    def update(self):
        self.updates += 1


class PaginaQueFalla(PaginaContadora):
    """Una página desmontada puede rechazar `update()`; eso nunca debe tumbar
    la apertura ni el cierre del diálogo."""

    def update(self):
        raise RuntimeError("la pagina ya no esta montada")


def _vista_inventario(db):
    InventarioView.ensure_settings_loaded()
    v = InventarioView(es_admin=True, username="tester")
    pagina = PaginaContadora()
    v._get_page = lambda e=None: pagina
    return v, pagina, v._open_dialog, v._close_dialog


def _vista_ventas(db):
    VentasView.ensure_settings_loaded()
    v = VentasView(user_data={"username": "tester", "role": "administrador"})
    pagina = PaginaContadora()
    v.get_current_page = lambda e=None: pagina
    v._page_ref = pagina
    return v, pagina, v._open_dialog, v._close_dialog


def _vista_cartera(db):
    CarteraView.ensure_settings_loaded()
    v = CarteraView(user_data={"username": "tester", "role": "administrador"})
    pagina = PaginaContadora()
    v.get_current_page = lambda e=None: pagina
    return v, pagina, v._abrir_dialogo, v._cerrar_dialogo


def _vista_gestion(db):
    GestionDatosView.ensure_settings_loaded()
    v = GestionDatosView(user_data={"username": "tester", "role": "superadmin"})
    pagina = PaginaContadora()
    v.get_current_page = lambda e=None: pagina
    return v, pagina, v._open_dialog, v._close_dialog


CONSTRUCTORES = {
    "inventario": _vista_inventario,
    "ventas": _vista_ventas,
    "cartera": _vista_cartera,
    "gestion_datos": _vista_gestion,
}


@pytest.mark.parametrize("nombre", sorted(CONSTRUCTORES))
def test_abrir_un_dialogo_repinta_la_pagina(db_temporal, nombre):
    """Sin esto, un diálogo abierto por teclado no se ve hasta el clic
    siguiente y la aplicación parece trabada."""
    _vista, pagina, abrir, _cerrar = CONSTRUCTORES[nombre](db_temporal)
    dialog = ft.AlertDialog(title=ft.Text("Uno"))

    antes = pagina.updates
    abrir(dialog)

    assert pagina.updates > antes, f"`{nombre}` apiló el diálogo sin repintar"
    assert dialog in pagina.dialogos


@pytest.mark.parametrize("nombre", sorted(CONSTRUCTORES))
def test_cerrar_un_dialogo_repinta_la_pagina(db_temporal, nombre):
    """Esc cierra desde el teclado: mismo motivo."""
    vista, pagina, abrir, cerrar = CONSTRUCTORES[nombre](db_temporal)
    dialog = ft.AlertDialog(title=ft.Text("Uno"))
    abrir(dialog)

    antes = pagina.updates
    if "cartera" == nombre:
        cerrar(dialog)
    else:
        cerrar(dialog=dialog)

    assert pagina.updates > antes, f"`{nombre}` cerró el diálogo sin repintar"
    assert dialog.open is False


def test_una_pagina_que_rechaza_el_repintado_no_tumba_el_dialogo(db_temporal):
    """Una página headless o desmontada puede no aceptar `update()`."""
    InventarioView.ensure_settings_loaded()
    vista = InventarioView(es_admin=True, username="tester")
    pagina = PaginaQueFalla()
    vista._get_page = lambda e=None: pagina

    dialog = ft.AlertDialog(title=ft.Text("Uno"))
    vista._open_dialog(dialog)      # no debe propagar
    assert dialog in pagina.dialogos

    vista._close_dialog(dialog=dialog)
    assert dialog.open is False


def test_el_modal_global_de_tasa_tambien_repinta(db_temporal):
    """`BaseView.abrir_dialogo` es el camino del Dashboard, y por ahí salen
    los diálogos de la Auditoría Preventiva."""
    from ui.views.dashboard_view import DashboardView

    DashboardView.ensure_settings_loaded()
    vista = DashboardView(user_info={"username": "tester", "role": "superadmin"})
    pagina = PaginaContadora()
    vista.get_current_page = lambda e=None: pagina

    dialog = ft.AlertDialog(title=ft.Text("Uno"))
    antes = pagina.updates
    vista.abrir_dialogo(dialog)

    assert pagina.updates > antes
    assert dialog in pagina.dialogos
