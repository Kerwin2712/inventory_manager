"""La barra de selección tiene que ser DESCUBRIBLE, no solo correcta.

Verificando la aplicación real, el usuario reportó que "no deja seleccionar
varios ítems al mismo tiempo". La función estaba completa y funcionando: lo
que faltaba era encontrarla. El conmutador era un ícono gris sin texto, pegado
a la leyenda "Sin selección", y en esa posición se lee como un indicador de
estado y no como algo que se pueda pulsar.

Una función que existe pero nadie descubre es una función que no existe, así
que la etiqueta visible va cubierta por tests igual que el comportamiento.
"""
import flet as ft
import pytest

from ui.views.inventario_view import InventarioView


def _textos(control) -> list[str]:
    encontrados = []
    if isinstance(control, ft.Text) and control.value:
        encontrados.append(str(control.value))
    for atributo in ("controls", "content", "actions", "title"):
        hijo = getattr(control, atributo, None)
        if isinstance(hijo, list):
            for h in hijo:
                encontrados += _textos(h)
        elif hijo is not None and hasattr(hijo, "_c"):
            encontrados += _textos(hijo)
    return encontrados


@pytest.fixture
def vista(db_temporal):
    InventarioView.ensure_settings_loaded()
    v = InventarioView(es_admin=True, username="tester")
    v.get_body()
    return v


def test_el_conmutador_dice_lo_que_hace(vista):
    """Con texto, no solo con un ícono."""
    assert "Selección múltiple" in " ".join(_textos(vista._btn_modo_seleccion))


def test_el_conmutador_es_pulsable(vista):
    """Un `Text` suelto no tiene `on_click`: el control tiene que ser un botón."""
    assert callable(getattr(vista._btn_modo_seleccion, "on_click", None))


def test_al_activarlo_el_boton_anuncia_como_salir(vista):
    """Un botón que solo cambia de color deja al usuario adivinando si ya lo
    pulsó."""
    vista.alternar_modo_seleccion()
    etiqueta = " ".join(_textos(vista._btn_modo_seleccion))
    assert "Salir" in etiqueta


def test_al_desactivarlo_vuelve_a_su_etiqueta(vista):
    vista.alternar_modo_seleccion()
    vista.alternar_modo_seleccion()
    etiqueta = " ".join(_textos(vista._btn_modo_seleccion))
    assert "Salir" not in etiqueta
    assert "Selección múltiple" in etiqueta


def test_el_tooltip_explica_para_que_sirve(vista):
    assert "varios" in (vista._btn_modo_seleccion.tooltip or "").lower()


# ─── Y que la función que se descubre, funcione ─────────────────────────────

def test_en_modo_multiple_se_marcan_varios_items(vista):
    """El reporte decía "solo puedo seleccionar de uno en uno"."""
    vista.alternar_modo_seleccion()
    vista.seleccionar_item("P-001")
    vista.seleccionar_item("P-002")
    vista.seleccionar_item("P-003")

    assert set(vista._seleccion.seleccionados) == {"P-001", "P-002", "P-003"}


def test_sin_el_modo_multiple_solo_queda_el_ultimo(vista):
    """El marcador del PDF: uno solo, y el clic mueve la marca."""
    vista.seleccionar_item("P-001")
    vista.seleccionar_item("P-002")

    assert vista._seleccion.seleccionados == ("P-002",)


def test_el_boton_de_borrado_en_lote_aparece_al_marcar(vista):
    vista.alternar_modo_seleccion()
    assert vista._btn_borrar_lote.visible is False

    vista.seleccionar_item("P-001")
    vista.seleccionar_item("P-002")

    assert vista._btn_borrar_lote.visible is True
    assert "2" in " ".join(_textos(vista._btn_borrar_lote))


def test_la_etiqueta_de_estado_dice_cuantos_van(vista):
    vista.alternar_modo_seleccion()
    vista.seleccionar_item("P-001")
    vista.seleccionar_item("P-002")

    assert "2" in (vista._lbl_seleccion.value or "")
