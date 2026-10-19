"""Navegación con flechas en el área de Inicio.

El usuario del proyecto pidió que las flechas naveguen en todas las vistas, no
solo en el Inventario. En Inicio no hay ítems con íconos, así que aquí va solo
la navegación: ninguna tecla de función.

El punto delicado de esta pantalla es que el Dashboard **aloja** a las demás
vistas. Si el destino de scroll del Inicio sobreviviera a un cambio de
sección, las flechas desplazarían un control que ya no está montado mientras
el usuario mira Ventas o Inventario: no se vería nada raro, simplemente las
flechas dejarían de responder donde el usuario las espera. De ahí que los
destinos se olviden en cada construcción del cuerpo.
"""
import asyncio

import pytest

from ui.components.teclado_nav import PASO_HORIZONTAL, PASO_VERTICAL
from ui.views.dashboard_view import DashboardView


class PaginaFalsa:
    def __init__(self):
        self.on_keyboard_event = None
        self.overlay = []

    def update(self):
        pass


class EventoFalso:
    def __init__(self, key, **modificadores):
        self.key = key
        for nombre, valor in modificadores.items():
            setattr(self, nombre, valor)


def _correr(corutina):
    return asyncio.run(corutina)


@pytest.fixture
def dashboard(db_temporal):
    """Dashboard en Inicio, con rol administrador (el que ve las dos tablas
    anchas) y una página falsa ya enganchada."""
    DashboardView.ensure_settings_loaded()
    vista = DashboardView(user_info={"username": "tester", "role": "administrador"})
    pagina = PaginaFalsa()
    vista.get_current_page = lambda e=None: pagina
    vista._pagina = pagina
    vista.current_section = "Inicio"
    vista.get_body()
    return vista


class EspiaScroll:
    """Reemplaza un destino real para contar los `scroll_to` recibidos."""

    def __init__(self):
        self.llamadas = []

    async def scroll_to(self, **kwargs):
        self.llamadas.append(kwargs)


# ─── Instalación ─────────────────────────────────────────────────────────────

def test_el_teclado_queda_enganchado_al_construir_el_inicio(dashboard):
    assert dashboard._pagina.on_keyboard_event is dashboard._teclado.handler


def test_antes_de_montarse_la_instalacion_no_falla(db_temporal):
    """La vista se instancia headless y se monta después: el primer intento
    falla sin consecuencias y el siguiente repintado la engancha."""
    DashboardView.ensure_settings_loaded()
    vista = DashboardView(user_info={"username": "tester", "role": "administrador"})
    vista.get_current_page = lambda e=None: None

    vista.current_section = "Inicio"
    vista.get_body()  # no debe lanzar

    assert vista._teclado.instalado is False


# ─── Destinos del Inicio ─────────────────────────────────────────────────────

def test_el_inicio_registra_su_eje_vertical(dashboard):
    assert dashboard._scroll_inicio_v is not None


def test_el_inicio_registra_su_eje_horizontal(dashboard):
    """La tabla ancha de la Auditoría Preventiva tiene su propio eje."""
    assert dashboard._scroll_inicio_h is not None


def test_las_flechas_verticales_desplazan_el_cuerpo_del_inicio(dashboard):
    espia = EspiaScroll()
    dashboard._scroll_inicio_v = espia

    _correr(dashboard._teclado.manejar(EventoFalso("Arrow Down")))
    assert espia.llamadas == [{"delta": PASO_VERTICAL, "duration": 200}]


def test_las_flechas_horizontales_desplazan_la_tabla_ancha(dashboard):
    espia = EspiaScroll()
    dashboard._scroll_inicio_h = espia

    _correr(dashboard._teclado.manejar(EventoFalso("Arrow Right")))
    assert espia.llamadas == [{"delta": PASO_HORIZONTAL, "duration": 200}]


def test_control_flecha_arriba_va_al_principio(dashboard):
    espia = EspiaScroll()
    dashboard._scroll_inicio_v = espia

    _correr(dashboard._teclado.manejar(EventoFalso("Arrow Up", ctrl=True)))
    assert espia.llamadas == [{"offset": 0.0, "duration": 200}]


def test_control_flecha_abajo_va_al_final(dashboard):
    espia = EspiaScroll()
    dashboard._scroll_inicio_v = espia

    _correr(dashboard._teclado.manejar(EventoFalso("Arrow Down", ctrl=True)))
    assert espia.llamadas[0]["delta"] > 10000


# ─── El destino no sobrevive a un cambio de sección ──────────────────────────

@pytest.mark.parametrize("seccion", ["Ventas", "Inventario", "Cartera", "Gestión de Datos"])
def test_al_salir_del_inicio_los_destinos_se_olvidan(dashboard, seccion):
    """Si sobrevivieran, las flechas desplazarían un control desmontado y
    dejarían de responder donde el usuario las espera."""
    assert dashboard._scroll_inicio_v is not None

    dashboard.current_section = seccion
    dashboard.get_body()

    assert dashboard._scroll_inicio_v is None
    assert dashboard._scroll_inicio_h is None


def test_fuera_del_inicio_las_flechas_no_desplazan_nada(dashboard):
    dashboard.current_section = "Inventario"
    dashboard.get_body()

    # No hay destino: la pulsación no hace nada y no revienta.
    _correr(dashboard._teclado.manejar(EventoFalso("Arrow Down")))


def test_volver_al_inicio_vuelve_a_registrar_el_destino(dashboard):
    dashboard.current_section = "Ventas"
    dashboard.get_body()
    dashboard.current_section = "Inicio"
    dashboard.get_body()

    assert dashboard._scroll_inicio_v is not None


# ─── La regla del foco ───────────────────────────────────────────────────────

def test_el_campo_de_stock_minimo_esta_enlazado_al_foco(dashboard):
    """Es el único campo de texto del Inicio: mientras el cursor esté ahí, las
    flechas tienen que editar el número y no mover la pantalla."""
    espia = EspiaScroll()
    dashboard._scroll_inicio_v = espia

    dashboard._teclado.foco.tomar("stock_minimo")
    _correr(dashboard._teclado.manejar(EventoFalso("Arrow Down")))
    assert espia.llamadas == []

    dashboard._teclado.foco.soltar("stock_minimo")
    _correr(dashboard._teclado.manejar(EventoFalso("Arrow Down")))
    assert espia.llamadas


def test_escape_suelta_el_foco(dashboard):
    dashboard._teclado.foco.tomar("stock_minimo")
    _correr(dashboard._teclado.manejar(EventoFalso("Escape")))
    assert dashboard._teclado.foco.hay_campo_con_foco is False


# ─── Ninguna tecla de función en Inicio ──────────────────────────────────────

@pytest.mark.parametrize("tecla", ["F1", "F2", "F3", "F4", "F5", "F6"])
def test_las_teclas_de_funcion_no_hacen_nada_en_el_inicio(dashboard, tecla):
    """Aquí no hay ítems con íconos: sin modelo de selección, el control de
    teclado no puede disparar ninguna acción de ítem."""
    espia = EspiaScroll()
    dashboard._scroll_inicio_v = espia

    _correr(dashboard._teclado.manejar(EventoFalso(tecla)))

    assert dashboard._teclado.hay_seleccion is False
    assert espia.llamadas == []


# ─── Convivencia con el resto de la aplicación ───────────────────────────────

def test_el_handler_previo_sigue_recibiendo_las_teclas(db_temporal):
    """El Dashboard aloja a las demás vistas, que también enganchan el
    teclado: nadie puede quedarse con él en exclusiva."""
    DashboardView.ensure_settings_loaded()
    vista = DashboardView(user_info={"username": "tester", "role": "administrador"})
    pagina = PaginaFalsa()
    recibidas = []
    pagina.on_keyboard_event = lambda e: recibidas.append(getattr(e, "key", None))
    vista.get_current_page = lambda e=None: pagina

    vista.current_section = "Inicio"
    vista.get_body()
    _correr(vista._teclado.manejar(EventoFalso("Arrow Down")))

    assert recibidas == ["Arrow Down"]


def test_reconstruir_el_inicio_no_encadena_el_teclado_a_si_mismo(dashboard):
    """Cada repintado vuelve a llamar a `instalar()`. Sin la guarda de
    idempotencia, el control acabaría encadenado a sí mismo y una sola flecha
    se procesaría varias veces."""
    dashboard.get_body()
    dashboard.get_body()

    espia = EspiaScroll()
    dashboard._scroll_inicio_v = espia
    _correr(dashboard._teclado.manejar(EventoFalso("Arrow Down")))

    assert len(espia.llamadas) == 1
