"""Cada sección del Dashboard debe renderizar su módulo, no el panel de error.

`BaseView.setup_layout()` envuelve la construcción en un try/except que ante
cualquier excepción pinta "Error al Cargar Módulo". Eso convierte un fallo de
construcción en algo silencioso: la app no se cae, simplemente muestra el
panel de error. Estos tests recorren el árbol de controles resultante para
detectarlo.
"""
import flet as ft
import pytest

SECCIONES = ("Inicio", "Ventas", "Inventario", "Cartera", "Gestión de Datos")


def _textos(control) -> list[str]:
    """Aplana los textos del árbol de controles de una vista."""
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
def dashboard(db_temporal):
    from ui.views.dashboard_view import DashboardView

    return DashboardView(user_info={"username": "tester", "role": "administrador"})


@pytest.mark.parametrize("seccion", SECCIONES)
@pytest.mark.parametrize("rol", ["administrador", "vendedor"])
def test_la_seccion_no_cae_al_panel_de_error(db_temporal, rol, seccion):
    from ui.views.dashboard_view import DashboardView

    vista = DashboardView(user_info={"username": "tester", "role": rol})
    vista.current_section = seccion
    vista.setup_layout()

    textos = _textos(vista.controls[0])
    assert not any("Error al Cargar" in t for t in textos), (
        f"la sección '{seccion}' con rol '{rol}' renderizó el panel de error: "
        f"{[t for t in textos if 'Detalle:' in t]}"
    )


def test_la_seccion_ventas_renderiza_el_panel_de_busqueda(dashboard):
    """Regresión: `VentasView(page=self.page, ...)` reventaba con RuntimeError
    mientras el Dashboard no estaba montado, y Ventas nunca se dibujaba."""
    dashboard.current_section = "Ventas"
    dashboard.setup_layout()

    textos = _textos(dashboard.controls[0])
    assert any("BÚSQUEDA Y SELECCIÓN DE ARTÍCULOS" in t for t in textos)
