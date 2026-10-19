"""Sincronización de la pila de diálogos con los cierres que hace Flet.

Las vistas llevan su propia lista de diálogos para saber cuál es el tope. Esa
lista se mantiene sola mientras los diálogos se cierren por los botones de la
vista — pero Flet también los cierra por su cuenta: un `AlertDialog` que no es
`modal=True` se descarta tocando fuera.

Si la vista no se entera, su lista queda con un fantasma, el tope que cree
tener deja de ser el que Flet tiene, y el siguiente cierre descarta el diálogo
equivocado: el usuario pulsa Cancelar, no se cierra nada visible y la pantalla
parece colgada. Es el mismo síntoma que ya costó una corrección en septiembre.
"""
import flet as ft
import pytest

from ui.components.pila_dialogos import sincronizar_al_descartar
from ui.views.inventario_view import InventarioView


def _dlg(titulo="Uno"):
    return ft.AlertDialog(title=ft.Text(titulo))


# ─── El helper, aislado ──────────────────────────────────────────────────────

def test_descartar_saca_el_dialogo_de_la_pila():
    pila = []
    dialog = _dlg()
    pila.append(dialog)
    sincronizar_al_descartar(dialog, pila)

    dialog.on_dismiss(None)

    assert pila == []
    assert dialog.open is False


def test_descartar_no_toca_a_los_demas():
    """Lo esencial: se va el que Flet cerró, no el que estaba debajo."""
    abajo, arriba = _dlg("Abajo"), _dlg("Arriba")
    pila = [abajo, arriba]
    sincronizar_al_descartar(arriba, pila)

    arriba.on_dismiss(None)

    assert pila == [abajo]


def test_descartar_dos_veces_no_falla():
    pila = []
    dialog = _dlg()
    pila.append(dialog)
    sincronizar_al_descartar(dialog, pila)

    dialog.on_dismiss(None)
    dialog.on_dismiss(None)

    assert pila == []


def test_se_conserva_el_on_dismiss_previo():
    """La sincronización es un añadido, no un reemplazo de lo que la vista
    quisiera hacer ahí."""
    llamados = []
    dialog = _dlg()
    dialog.on_dismiss = lambda e: llamados.append("propio")
    pila = [dialog]

    sincronizar_al_descartar(dialog, pila)
    dialog.on_dismiss(None)

    assert llamados == ["propio"]
    assert pila == []


def test_sincronizar_dos_veces_no_encadena_infinito():
    """Reabrir el mismo diálogo vuelve a pasar por el helper."""
    dialog = _dlg()
    pila = [dialog]
    sincronizar_al_descartar(dialog, pila)
    sincronizar_al_descartar(dialog, pila)

    dialog.on_dismiss(None)  # no debe desbordar la pila de llamadas
    assert pila == []


# ─── Cableado en una vista real ──────────────────────────────────────────────

class PaginaFalsa:
    def __init__(self):
        self.dialogos = []
        self.overlay = []
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
        pass


@pytest.fixture
def vista(db_temporal):
    InventarioView.ensure_settings_loaded()
    v = InventarioView(es_admin=True, username="tester")
    pagina = PaginaFalsa()
    v._get_page = lambda e=None: pagina
    v._pagina = pagina
    return v


def test_la_vista_engancha_la_sincronizacion_al_abrir(vista):
    dialog = _dlg()
    vista._open_dialog(dialog)
    assert callable(dialog.on_dismiss)


def test_un_descarte_de_flet_deja_la_pila_de_la_vista_limpia(vista):
    dialog = _dlg()
    vista._open_dialog(dialog)
    assert vista._dialog_stack == [dialog]

    dialog.on_dismiss(None)  # el usuario tocó fuera del diálogo

    assert vista._dialog_stack == []
    assert vista._dialog is None


def test_tras_un_descarte_el_siguiente_dialogo_se_cierra_bien(vista):
    """La regresión completa: con el fantasma en la pila, el cierre del
    diálogo siguiente descartaba el equivocado y la pantalla parecía colgada."""
    fantasma = _dlg("Detalle")
    vista._open_dialog(fantasma)
    fantasma.on_dismiss(None)  # descartado por Flet, no por la vista

    segundo = _dlg("Clave")
    vista._open_dialog(segundo)
    assert vista._dialog is segundo

    vista._close_dialog(dialog=segundo)

    assert vista._dialog_stack == []
    assert segundo.open is False
