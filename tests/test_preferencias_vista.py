"""Pruebas de `services.preferencias_service` y de su cableado en Inventario.

La preferencia se guarda en `app_settings` con una clave namespaced por
usuario, de modo que dos vendedores en el mismo equipo no se pisen el modo de
vista del catálogo. La lectura es tolerante (nunca lanza) y la escritura
estricta (un modo fuera del catálogo es `ValueError`).
"""
import pytest

from core.database import get_setting, set_setting
from services.preferencias_service import (
    MODOS_VISTA_INVENTARIO,
    MODO_VISTA_INVENTARIO_DEFECTO,
    PREF_VISTA_INVENTARIO,
    guardar_vista_inventario,
    obtener_vista_inventario,
)


# ─────────────────────────────────────────────────────────────────────────────
# Guardado y carga por usuario
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("modo", MODOS_VISTA_INVENTARIO)
def test_guardar_y_cargar_devuelve_el_modo_elegido(db_temporal, modo):
    assert guardar_vista_inventario("ana", modo) == modo
    assert obtener_vista_inventario("ana") == modo


def test_el_ultimo_guardado_sobreescribe_al_anterior(db_temporal):
    guardar_vista_inventario("ana", "tarjetas")
    guardar_vista_inventario("ana", "agrupado")

    assert obtener_vista_inventario("ana") == "agrupado"


def test_la_preferencia_esta_aislada_entre_dos_usuarios(db_temporal):
    guardar_vista_inventario("ana", "tarjetas")
    guardar_vista_inventario("beto", "agrupado")

    assert obtener_vista_inventario("ana") == "tarjetas"
    assert obtener_vista_inventario("beto") == "agrupado"
    # Un tercer usuario sin preferencia no hereda la de nadie.
    assert obtener_vista_inventario("carla") == MODO_VISTA_INVENTARIO_DEFECTO


def test_la_clave_persistida_esta_namespaced_por_usuario(db_temporal):
    guardar_vista_inventario("ana", "tarjetas")

    assert get_setting(f"{PREF_VISTA_INVENTARIO}:ana") == "tarjetas"
    assert get_setting(f"{PREF_VISTA_INVENTARIO}:beto", "") == ""


# ─────────────────────────────────────────────────────────────────────────────
# Valor por defecto y tolerancia a datos corruptos
# ─────────────────────────────────────────────────────────────────────────────
def test_sin_preferencia_guardada_devuelve_el_modo_por_defecto(db_temporal):
    assert obtener_vista_inventario("nadie") == MODO_VISTA_INVENTARIO_DEFECTO
    assert MODO_VISTA_INVENTARIO_DEFECTO == "separado"


@pytest.mark.parametrize("corrupto", ["", "   ", "lista", "SEPARADO", "null", "{json}", "tarjetas2"])
def test_un_valor_almacenado_invalido_cae_al_defecto_sin_lanzar(db_temporal, corrupto):
    set_setting(f"{PREF_VISTA_INVENTARIO}:ana", corrupto)

    assert obtener_vista_inventario("ana") == MODO_VISTA_INVENTARIO_DEFECTO


@pytest.mark.parametrize("modo_invalido", ["", "   ", "lista", "Separado", None, "comprimido"])
def test_guardar_un_modo_invalido_lanza_value_error(db_temporal, modo_invalido):
    with pytest.raises(ValueError):
        guardar_vista_inventario("ana", modo_invalido)


def test_guardar_un_modo_invalido_no_pisa_la_preferencia_previa(db_temporal):
    guardar_vista_inventario("ana", "tarjetas")

    with pytest.raises(ValueError):
        guardar_vista_inventario("ana", "inventado")

    assert obtener_vista_inventario("ana") == "tarjetas"


# ─────────────────────────────────────────────────────────────────────────────
# Usuario ausente: cubo genérico de sesión, nunca un fallo
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("sin_usuario", [None, "", "   "])
def test_sin_usuario_la_lectura_devuelve_el_defecto(db_temporal, sin_usuario):
    assert obtener_vista_inventario(sin_usuario) == MODO_VISTA_INVENTARIO_DEFECTO


@pytest.mark.parametrize("sin_usuario", [None, "", "   "])
def test_sin_usuario_el_guardado_usa_una_clave_generica_y_no_falla(db_temporal, sin_usuario):
    assert guardar_vista_inventario(sin_usuario, "agrupado") == "agrupado"
    assert obtener_vista_inventario(sin_usuario) == "agrupado"
    # El cubo anónimo es compartido, pero no contamina a un usuario nombrado.
    assert obtener_vista_inventario("ana") == MODO_VISTA_INVENTARIO_DEFECTO


def test_los_espacios_alrededor_del_usuario_no_crean_cubos_distintos(db_temporal):
    guardar_vista_inventario("ana", "tarjetas")

    assert obtener_vista_inventario("  ana  ") == "tarjetas"


# ─────────────────────────────────────────────────────────────────────────────
# Cableado en `InventarioView`
# ─────────────────────────────────────────────────────────────────────────────
def _vista(username=None):
    from ui.views.inventario_view import InventarioView

    v = InventarioView(es_admin=True, username=username)
    v.get_body()
    return v


class _EventoSegmentado:
    """Evento mínimo de `ft.SegmentedButton` (headless, sin `page`)."""

    def __init__(self, seleccion):
        self.control = type("C", (), {"selected": {seleccion}})()
        self.page = None


def test_la_vista_arranca_en_el_modo_por_defecto_sin_preferencia(db_temporal):
    assert _vista("ana")._modo_vista == MODO_VISTA_INVENTARIO_DEFECTO


def test_la_vista_arranca_en_el_ultimo_modo_guardado_del_usuario(db_temporal):
    guardar_vista_inventario("ana", "tarjetas")

    vista = _vista("ana")

    assert vista._modo_vista == "tarjetas"
    assert vista._btn_modo_vista.selected == ["tarjetas"]


def test_cambiar_de_modo_persiste_la_preferencia_del_usuario(db_temporal):
    vista = _vista("ana")

    vista._handle_cambio_modo_vista(_EventoSegmentado("agrupado"))

    assert vista._modo_vista == "agrupado"
    assert obtener_vista_inventario("ana") == "agrupado"
    # Y se recupera al reabrir el módulo.
    assert _vista("ana")._modo_vista == "agrupado"


def test_el_modo_de_un_usuario_no_afecta_al_de_otro_en_la_vista(db_temporal):
    _vista("ana")._handle_cambio_modo_vista(_EventoSegmentado("tarjetas"))

    assert _vista("beto")._modo_vista == MODO_VISTA_INVENTARIO_DEFECTO


def test_la_vista_sin_username_sigue_construyendose(db_temporal):
    """Instanciación aislada (tests, herramientas): usa el cubo anónimo."""
    vista = _vista(None)

    vista._handle_cambio_modo_vista(_EventoSegmentado("tarjetas"))

    assert vista._modo_vista == "tarjetas"


def test_el_dashboard_propaga_el_usuario_al_inventario(db_temporal):
    """El namespacing depende de que `DashboardView` haga llegar el usuario."""
    from ui.views.dashboard_view import DashboardView
    from ui.views.inventario_view import InventarioView

    guardar_vista_inventario("u", "agrupado")
    creadas = []
    original = InventarioView.__init__

    def espia(self, *args, **kwargs):
        creadas.append(kwargs)
        original(self, *args, **kwargs)

    InventarioView.__init__ = espia
    try:
        tablero = DashboardView(user_info={"username": "u", "role": "administrador"})
        tablero.current_section = "Inventario"
        tablero.get_body()
    finally:
        InventarioView.__init__ = original

    assert creadas, "el dashboard debe instanciar InventarioView"
    assert creadas[-1].get("username") == "u"
    assert creadas[-1].get("rol_usuario") == "administrador"
