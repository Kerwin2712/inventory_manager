"""Pruebas del solapamiento de la navegación rápida sobre los encabezados.

Bug corregido: `scroll_nav` devolvía el cluster HORIZONTAL como un `ft.Container`
anclado con `right`/`top` dentro del `ft.Stack` cuyo primer hijo es la tabla, así
que flotaba justo encima de la fila de encabezados de columna y la tapaba.

Ahora el cluster horizontal vive en la barra de herramientas de la tarjeta
(flujo normal, sin posicionamiento absoluto) y solo el vertical sigue flotando
en la esquina inferior derecha, donde no cubre nada.
"""
import flet as ft
import pytest

from ui.components.scroll_nav import build_floating_v_nav, build_inline_h_nav


@pytest.fixture
def vista(db_temporal):
    from ui.views.inventario_view import InventarioView

    v = InventarioView(es_admin=True, rol_usuario="administrador")
    v.get_body()
    return v


@pytest.fixture
def producto(db_temporal):
    from services.inventario_service import crear_producto

    crear_producto(
        codigo="NAV-001", referencia="R", descripcion_general="Producto de prueba",
        departamento="Ferretería", existencia=0,
    )
    return "NAV-001"


def _descendientes(control, _vistos=None):
    if _vistos is None:
        _vistos = set()
    if control is None or id(control) in _vistos:
        return
    _vistos.add(id(control))
    yield control
    hijos = []
    for attr in ("controls", "actions", "rows", "cells", "columns"):
        hijos.extend(getattr(control, attr, None) or [])
    for attr in ("content", "title", "label", "icon"):
        hijo = getattr(control, attr, None)
        if isinstance(hijo, ft.Control):
            hijos.append(hijo)
    for hijo in hijos:
        yield from _descendientes(hijo, _vistos)


# ─────────────────────────────────────────────────────────────────────────────
# El componente: cada cluster con su propio contrato de posicionamiento
# ─────────────────────────────────────────────────────────────────────────────
def test_el_cluster_horizontal_no_lleva_posicionamiento_absoluto():
    cluster = build_inline_h_nav(ft.Row(scroll=ft.ScrollMode.ALWAYS), "#2196F3")

    assert isinstance(cluster, ft.Container)
    for borde in ("top", "right", "bottom", "left"):
        assert getattr(cluster, borde) is None, f"'{borde}' vuelve a anclarlo al Stack"
    assert len(cluster.content.controls) == 4
    assert all(c.on_click for c in cluster.content.controls)


def test_el_cluster_vertical_sigue_anclado_abajo_a_la_derecha():
    cluster = build_floating_v_nav(ft.Column(scroll=ft.ScrollMode.AUTO), "#2196F3")

    assert cluster.bottom is not None and cluster.right is not None
    assert cluster.top is None, "anclarlo arriba volvería a tapar los encabezados"
    assert len(cluster.content.controls) == 4


# ─────────────────────────────────────────────────────────────────────────────
# La vista: el Stack ya no superpone nada sobre los encabezados
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("modo", ["separado", "agrupado"])
def test_el_cluster_horizontal_no_vive_en_el_stack_de_la_tabla(vista, producto, modo):
    vista._modo_vista = modo
    vista._cargar_filas()
    stack = vista._vista_container.content

    assert isinstance(stack, ft.Stack)
    assert vista._nav_h not in stack.controls, "el cluster horizontal volvió a flotar sobre la tabla"
    # La tabla sigue siendo el primer hijo, ahora envuelta en el contenedor
    # que le reserva holgura al pie para el cluster flotante.
    assert stack.controls[0] is vista._tabla_con_holgura
    assert vista._tabla_con_holgura.content is vista._tabla_scroll_col
    assert vista._nav_v in stack.controls


@pytest.mark.parametrize("modo", ["separado", "agrupado"])
def test_la_tabla_reserva_holgura_para_el_cluster_flotante(vista, producto, modo):
    """El cluster vertical flota anclado abajo a la derecha; sin holgura al pie
    se dibujaba encima del texto de la última fila."""
    vista._modo_vista = modo
    vista._cargar_filas()

    holgura = vista._tabla_con_holgura.padding
    assert holgura is not None, "la tabla debe reservar espacio al pie"
    assert holgura.bottom >= 28, "la holgura debe cubrir el alto del cluster"
    # La holgura no puede reintroducir un scroll propio ni una altura fija.
    assert getattr(vista._tabla_con_holgura, "height", None) is None
    assert getattr(vista._tabla_con_holgura, "scroll", None) is None


@pytest.mark.parametrize("modo", ["separado", "agrupado"])
def test_ningun_hijo_del_stack_flota_sobre_la_fila_de_encabezados(vista, producto, modo):
    """Nada anclado arriba: `top` ocupado es exactamente lo que tapaba los
    encabezados de columna de la `DataTable`."""
    vista._modo_vista = modo
    vista._cargar_filas()

    for hijo in vista._vista_container.content.controls[1:]:
        assert getattr(hijo, "top", None) is None
        assert getattr(hijo, "bottom", None) is not None


def test_el_cluster_horizontal_vive_junto_al_selector_de_modo_de_vista(vista):
    """Nuevo hogar del cluster: la barra de herramientas de la tarjeta."""
    barra = next(
        fila for fila in _descendientes(vista._tabla_panel)
        if isinstance(fila, ft.Row) and vista._btn_modo_vista in (fila.controls or [])
    )

    assert vista._nav_h in barra.controls


def test_los_botones_horizontales_siguen_apuntando_a_la_tabla(vista):
    assert vista._nav_h.content.controls, "el cluster quedó vacío"
    assert all(b.on_click for b in vista._nav_h.content.controls)
    assert vista._tabla_scroll_row.scroll == ft.ScrollMode.ALWAYS


def test_los_targets_de_scroll_conservan_su_contrato_de_ejes(vista, producto):
    """No-regresión del fix de scroll anidado: un solo dueño por eje."""
    vista._cargar_filas()

    assert vista._tabla_scroll_row.scroll == ft.ScrollMode.ALWAYS
    assert vista._tabla_scroll_col.scroll is None
    assert vista._tabla_scroll_col.height is None
    assert vista._vista_container.height is None
    assert vista._body_scroll_col.scroll == ft.ScrollMode.AUTO


def test_en_modo_tarjetas_no_queda_ningun_cluster_superpuesto(vista, producto):
    vista._modo_vista = "tarjetas"
    vista._cargar_filas()

    assert not isinstance(vista._vista_container.content, ft.Stack)
    assert vista._nav_h.visible is False
    assert vista._nav_v.visible is False
