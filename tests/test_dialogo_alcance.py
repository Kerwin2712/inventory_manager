"""Diálogos que deciden sobre qué ítems actúa una acción.

Con varios ítems marcados una acción deja de tener destinatario evidente, y
adivinar es inaceptable en las dos direcciones: aplicar a todo lo que el
usuario creía que era uno borra de más, y aplicar a uno lo que creía que era
todo deja trabajo a medias sin avisar. De ahí que la pregunta tenga tests
propios y no sea un detalle de la vista.
"""
import flet as ft
import pytest

from ui.components.dialogo_alcance import (
    ALCANCE_TODOS,
    ALCANCE_UNO,
    DialogoAlcance,
    DialogoElegirItem,
    hace_falta_preguntar,
)

MARCADOS = ["P-001", "P-002", "P-003"]


def _textos(control) -> list[str]:
    encontrados = []
    if isinstance(control, ft.Text) and control.value:
        encontrados.append(str(control.value))
    for atributo in ("controls", "content", "actions", "title", "subtitle", "leading"):
        hijo = getattr(control, atributo, None)
        if isinstance(hijo, list):
            for h in hijo:
                encontrados += _textos(h)
        elif hijo is not None and hasattr(hijo, "_c"):
            encontrados += _textos(hijo)
    return encontrados


# ─── Cuándo hace falta preguntar ────────────────────────────────────────────

@pytest.mark.parametrize("marcados", [[], ["P-001"], None])
def test_con_cero_o_uno_no_se_pregunta(marcados):
    """El destinatario es evidente: preguntar sería ruido."""
    assert hace_falta_preguntar(marcados) is False


def test_con_dos_o_mas_si_se_pregunta():
    assert hace_falta_preguntar(["P-001", "P-002"]) is True
    assert hace_falta_preguntar(MARCADOS) is True


# ─── ¿Este o todos? ──────────────────────────────────────────────────────────

@pytest.fixture
def alcance():
    elegidos, cierres = [], []
    comp = DialogoAlcance(
        titulo="Añadir al carrito",
        accion="Añadir al carrito",
        codigo="P-002",
        marcados=MARCADOS,
        on_elegir=lambda alcance, e=None: elegidos.append(alcance),
        on_cerrar=lambda e=None: cierres.append(True),
    )
    return comp, elegidos, cierres


def test_elegir_solo_este_devuelve_uno(alcance):
    comp, elegidos, _ = alcance
    comp.boton_uno.on_click(None)
    assert elegidos == [ALCANCE_UNO]


def test_elegir_el_lote_devuelve_todos(alcance):
    comp, elegidos, _ = alcance
    comp.boton_todos.on_click(None)
    assert elegidos == [ALCANCE_TODOS]


def test_cancelar_no_ejecuta_nada(alcance):
    """Cancelar no es "solo este" por omisión: no se actúa sobre nada."""
    comp, elegidos, cierres = alcance
    comp.boton_cancelar.on_click(None)
    assert elegidos == []
    assert cierres == [True]


def test_el_dialogo_cierra_antes_de_ejecutar(alcance):
    """Si se ejecutara primero, la acción podría apilar su propio diálogo
    debajo de este y el usuario vería el de abajo."""
    comp, _, cierres = alcance
    comp.boton_todos.on_click(None)
    assert cierres == [True]


def test_el_dialogo_nombra_el_item_y_la_cantidad(alcance):
    """Nadie debería elegir a ciegas sobre qué actúa."""
    comp, _, _ = alcance
    texto = " ".join(_textos(comp.dialogo))
    assert "P-002" in texto
    assert "3" in texto


def test_el_dialogo_nombra_la_accion(alcance):
    comp, _, _ = alcance
    assert "carrito" in " ".join(_textos(comp.dialogo)).lower()


def test_un_lote_largo_no_lista_todos_los_codigos():
    """El diálogo tiene que seguir siendo legible con cincuenta marcados."""
    muchos = [f"P-{n:03d}" for n in range(50)]
    comp = DialogoAlcance(
        titulo="Borrar", accion="Borrar", codigo="P-000",
        marcados=muchos, on_elegir=lambda a, e=None: None,
    )
    texto = " ".join(_textos(comp.dialogo))
    assert "más" in texto
    assert "P-049" not in texto


def test_es_modal():
    """Una pregunta que se puede esquivar tocando al lado no es una pregunta."""
    comp = DialogoAlcance(
        titulo="Borrar", accion="Borrar", codigo="P-001",
        marcados=MARCADOS, on_elegir=lambda a, e=None: None,
    )
    assert comp.dialogo.modal is True


def test_el_componente_viaja_pegado_al_dialogo():
    comp = DialogoAlcance(
        titulo="Borrar", accion="Borrar", codigo="P-001",
        marcados=MARCADOS, on_elegir=lambda a, e=None: None,
    )
    assert comp.dialogo.data is comp


# ─── ¿Cuál de todos? ─────────────────────────────────────────────────────────

@pytest.fixture
def elegir():
    elegidos, cierres = [], []
    comp = DialogoElegirItem(
        titulo="Ver detalle",
        accion="Ver detalle",
        marcados=MARCADOS,
        etiquetas={"P-001": "Filtro de aceite", "P-002": "Bujía"},
        on_elegir=lambda codigo, e=None: elegidos.append(codigo),
        on_cerrar=lambda e=None: cierres.append(True),
    )
    return comp, elegidos, cierres


def test_hay_una_opcion_por_item_marcado(elegir):
    comp, _, _ = elegir
    assert len(comp.opciones) == 3
    assert [o.data for o in comp.opciones] == MARCADOS


def test_elegir_una_opcion_devuelve_su_codigo(elegir):
    comp, elegidos, _ = elegir
    comp.opciones[1].on_click(None)
    assert elegidos == ["P-002"]


def test_se_muestra_la_etiqueta_cuando_existe(elegir):
    """El código solo no le dice nada al usuario de mostrador."""
    comp, _, _ = elegir
    texto = " ".join(_textos(comp.dialogo))
    assert "Filtro de aceite" in texto


def test_sin_etiqueta_se_muestra_el_codigo(elegir):
    """`P-003` no tenía etiqueta: el código siempre existe."""
    comp, _, _ = elegir
    assert "P-003" in " ".join(_textos(comp.dialogo))


def test_cancelar_no_elige_nada(elegir):
    comp, elegidos, cierres = elegir
    comp.boton_cancelar.on_click(None)
    assert elegidos == []
    assert cierres == [True]


def test_cierra_antes_de_ejecutar(elegir):
    comp, _, cierres = elegir
    comp.opciones[0].on_click(None)
    assert cierres == [True]


def test_la_lista_larga_tiene_su_propio_scroll():
    """Un lote de cincuenta no puede estirar el diálogo fuera de la pantalla."""
    muchos = [f"P-{n:03d}" for n in range(50)]
    comp = DialogoElegirItem(
        titulo="Editar", accion="Editar", marcados=muchos,
        on_elegir=lambda c, e=None: None,
    )
    lista = comp.dialogo.content.controls[1]
    assert lista.scroll is not None
    assert lista.height <= 300


def test_el_dialogo_explica_por_que_hay_que_elegir(elegir):
    comp, _, _ = elegir
    texto = " ".join(_textos(comp.dialogo)).lower()
    assert "de a uno" in texto or "elija" in texto
