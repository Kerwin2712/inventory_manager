"""Pruebas del encabezado unificado en una sola franja horizontal.

Antes existían DOS franjas: la que `BaseView.setup_layout()` pintaba con el
título global y la barra propia del dashboard (módulo actual + usuario + opciones
de interfaz + cerrar sesión). El encabezado unificado muestra solo el nombre de la
vista activa ("Inicio", "Ventas", etc.) junto con el usuario y opciones sin franjas extra.

Las vistas se instancian headless (sin `page`): los accesos a `self.page`
lanzan `RuntimeError`, que los helpers de `BaseView` ya capturan.
"""
import flet as ft
import pytest


@pytest.fixture
def dashboard(db_temporal):
    """`DashboardView` headless con un usuario administrativo."""
    from ui.views.dashboard_view import DashboardView

    return DashboardView(user_info={"username": "u", "role": "administrador"})


def _descendientes(control, _vistos=None):
    """Recorre en profundidad el árbol de controles de Flet."""
    if _vistos is None:
        _vistos = set()
    if control is None or id(control) in _vistos:
        return
    _vistos.add(id(control))
    yield control
    hijos = []
    for attr in ("controls", "actions", "segments", "items"):
        hijos.extend(getattr(control, attr, None) or [])
    for attr in ("content", "label", "icon", "title", "leading", "trailing"):
        hijo = getattr(control, attr, None)
        if isinstance(hijo, ft.Control):
            hijos.append(hijo)
    for hijo in hijos:
        yield from _descendientes(hijo, _vistos)


def _textos(control) -> list[str]:
    return [c.value for c in _descendientes(control) if isinstance(c, ft.Text) and c.value]


def _tooltips(control) -> list[str]:
    return [c.tooltip for c in _descendientes(control) if getattr(c, "tooltip", None)]


# ─────────────────────────────────────────────────────────────────────────────
# Una sola franja: todo convive en la misma fila
# ─────────────────────────────────────────────────────────────────────────────
def test_el_header_reune_titulo_modulo_usuario_opciones_y_salir_en_una_fila(dashboard):
    dashboard.current_section = "Inventario"
    header = dashboard.build_header()

    assert isinstance(header, ft.Row), "el encabezado debe ser una única franja horizontal"
    textos = _textos(header)
    tooltips = " | ".join(_tooltips(header))

    assert "General" not in textos, "no debe incluir 'General' en los títulos de las vistas"
    assert "Inventario" in textos, "falta el módulo actual"
    assert any("u" in t and "Administrador" in t for t in textos), "falta el badge de usuario"
    assert "Alternar Modo Claro / Oscuro" in tooltips
    assert "Seleccionar Color de Acento" in tooltips
    assert "Alertas de Stock Crítico" in tooltips
    assert "Cerrar Sesión" in tooltips


def test_el_modulo_inicio_muestra_su_nombre(dashboard):
    dashboard.current_section = "Inicio"

    assert "Inicio" in _textos(dashboard.build_header())
    assert "General" not in _textos(dashboard.build_header())


def test_la_vista_no_pinta_un_titulo_duplicado_en_una_linea_aparte(dashboard):
    """El encabezado no se duplica en una franja extra: `controls` tiene
    solo el cuerpo, y 'General' no aparece en el árbol."""
    assert dashboard.mostrar_titulo_por_defecto is False
    assert dashboard.build_encabezado() == []
    assert len(dashboard.controls) == 1, "sobrevive una franja extra de título"
    assert not any(isinstance(c, ft.Text) for c in dashboard.controls)
    assert not any(isinstance(c, ft.Divider) for c in dashboard.controls)

    assert "General" not in _textos(dashboard)


def test_el_bloque_de_titulo_cede_ancho_y_elide_sin_empujar_las_acciones(dashboard):
    """En ventanas angostas el texto se recorta con elipsis; la zona de
    acciones va `tight` para no comprimirse ni salir de pantalla."""
    dashboard.current_section = "Gestión de Datos"
    header = dashboard.build_header()
    bloque_titulo, acciones = header.controls[0], header.controls[1]

    assert isinstance(bloque_titulo, ft.Container) and bloque_titulo.expand
    for texto in bloque_titulo.content.controls:
        assert texto.max_lines == 1
        assert texto.overflow == ft.TextOverflow.ELLIPSIS

    modulo = bloque_titulo.content.controls[-1]
    assert modulo.value == "Gestión de Datos"
    assert modulo.expand, "el título debe ceder ancho al elidir"

    assert isinstance(acciones, ft.Row) and acciones.tight is True
    assert acciones.expand in (None, False, 0)


# ─────────────────────────────────────────────────────────────────────────────
# No-regresión: las vistas con título propio siguen igual
# ─────────────────────────────────────────────────────────────────────────────
def test_admin_users_conserva_su_primera_franja_de_titulo(db_temporal):
    """`AdminUsersView` usa el `setup_layout()` de `BaseView` y debe seguir
    renderizando título + divisor + cuerpo, exactamente como antes."""
    from ui.views.admin_users_view import AdminUsersView

    vista = AdminUsersView()

    assert vista.mostrar_titulo_por_defecto is True
    assert len(vista.controls) == 3, "título + divisor + cuerpo"
    assert isinstance(vista.controls[0], ft.Text)
    assert vista.controls[0].value == "Gestión de Usuarios | SuperAdmin"
    assert isinstance(vista.controls[1], ft.Divider)


def test_login_conserva_su_layout_limpio_sin_cabecera(db_temporal):
    """`LoginView` ya sobreescribía `setup_layout()` con un layout sin
    cabeceras: el nuevo punto de extensión no lo altera."""
    from ui.views.login_view import LoginView

    vista = LoginView()

    assert len(vista.controls) == 1
    assert not any(isinstance(c, ft.Text) for c in vista.controls)
    assert "Control de Acceso" == vista.view_title
