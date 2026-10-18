"""Área de Inicio del Dashboard (especificación 17/10/2026).

Mismo enfoque que `test_dashboard_secciones.py`: se construye el árbol de
controles de la vista SIN página de Flet (doble headless) y se recorre, porque
`BaseView.setup_layout()` atrapa cualquier excepción y la convierte en el panel
"Error al Cargar Módulo" — un fallo de construcción sería silencioso.

El recorrido baja también por `rows`/`columns`/`cells`, que es donde viven las
celdas de un `DataTable`.
"""
import flet as ft
import pytest

from services.inventario_service import crear_producto

ATRIBUTOS_HIJOS = ("controls", "content", "actions", "title", "rows", "columns", "cells", "label")

DESCRIPCION_LARGA = (
    "Tornillo autoperforante de acero galvanizado cabeza hexagonal de una "
    "pulgada y media para lamina metalica calibre veinticuatro"
)


def _controles(control):
    """Aplana el árbol de controles de una vista (incluidas celdas de tabla)."""
    if control is None or not hasattr(control, "_c"):
        return
    yield control
    for atributo in ATRIBUTOS_HIJOS:
        hijo = getattr(control, atributo, None)
        if isinstance(hijo, list):
            for h in hijo:
                yield from _controles(h)
        else:
            yield from _controles(hijo)


def _textos(control) -> list[str]:
    return [str(c.value) for c in _controles(control) if isinstance(c, ft.Text) and c.value]


@pytest.fixture
def vista(db_temporal):
    from ui.views.dashboard_view import DashboardView

    return DashboardView(user_info={"username": "tester", "role": "administrador"})


@pytest.fixture
def producto_critico(db_temporal):
    """Producto en cero con descripción larga: dispara la Auditoría Preventiva
    y obliga a la celda a usar la segunda línea."""
    return crear_producto(
        codigo="TOR-001",
        referencia="REF-9988",
        descripcion_general=DESCRIPCION_LARGA,
        departamento="Ferretería",
        marca="Acme",
        precio_dolares=1.5,
        existencia=0.0,
        nombre_referencia_corto="Tornillo AP 1/4",
        costo_usd_efectivo=None,
        rol_usuario="administrador",
    )


# ─── Cambios 1 y 2: Auditoría e Inteligencia a ancho completo ────────────────

def test_auditoria_e_inteligencia_van_a_ancho_completo_y_en_ese_orden(vista, producto_critico):
    seccion = vista.build_data_sections()

    assert isinstance(seccion, ft.ResponsiveRow)
    assert len(seccion.controls) == 2
    for tarjeta in seccion.controls:
        assert tarjeta.col == {"sm": 12, "lg": 12}, (
            "las tarjetas del Inicio deben ocupar la pantalla de izquierda a derecha"
        )

    textos_auditoria = _textos(seccion.controls[0])
    textos_inteligencia = _textos(seccion.controls[1])
    assert any("Auditoría Preventiva" in t for t in textos_auditoria)
    assert any("Inteligencia de Negocio" in t for t in textos_inteligencia)


def test_la_descripcion_de_auditoria_admite_dos_lineas(vista, producto_critico):
    """El modo agrupado del Inventario parte la descripción en dos líneas; la
    Auditoría ampliada debe comportarse igual (`max_lines=2` + elipsis)."""
    seccion = vista.build_data_sections()

    descripciones = [
        c for c in _controles(seccion)
        if isinstance(c, ft.Text) and c.value == DESCRIPCION_LARGA
    ]
    assert descripciones, "la Auditoría no mostró la descripción general del ítem"
    for texto in descripciones:
        assert texto.max_lines == 2
        assert texto.overflow == ft.TextOverflow.ELLIPSIS


def test_auditoria_muestra_la_informacion_completa_del_item(vista, producto_critico):
    """El ancho ganado se gasta en los datos que antes no cabían: código,
    referencia, nombre corto y departamento/marca."""
    textos = _textos(vista.build_data_sections())

    assert any("Cód: TOR-001" in t for t in textos)
    assert any("Ref: REF-9988" in t for t in textos)
    assert any("Tornillo AP 1/4" in t for t in textos)
    assert any(t == "Ferretería" for t in textos)
    assert any(t == "Acme" for t in textos)
