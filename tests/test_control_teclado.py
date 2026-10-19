"""`ControlTeclado`: el enganche de los atajos a la página de Flet.

Lo que se verifica aquí son las cuatro trampas de este enganche, todas
silenciosas si se rompen:

1. La página se comparte con el resto del Dashboard, así que el handler
   anterior tiene que seguir recibiendo teclas.
2. `scroll_to` es una corutina: un handler síncrono la crearía y la
   descartaría sin ejecutarla, sin lanzar error, y las flechas no harían nada
   sin dejar rastro.
3. Los destinos de scroll se buscan al pulsar, no se guardan: la tabla se
   reconstruye en cada repintado y un control viejo ya no está en pantalla.
4. Un destino sin scroll o desmontado no puede tumbar el teclado de toda la
   aplicación.
"""
import asyncio

import pytest

from ui.components.seleccion_lista import SeleccionLista
from ui.components.teclado_nav import PASO_HORIZONTAL, PASO_VERTICAL, ControlTeclado


class DestinoFalso:
    """Control con scroll: registra cada `scroll_to` que recibe."""

    def __init__(self):
        self.llamadas = []

    async def scroll_to(self, **kwargs):
        self.llamadas.append(kwargs)


class DestinoRoto:
    """Control sin scroll habilitado: Flet lanza al pedirle `scroll_to`."""

    async def scroll_to(self, **kwargs):
        raise AssertionError("este control no tiene scroll")


class PaginaFalsa:
    def __init__(self):
        self.on_keyboard_event = None


class EventoFalso:
    def __init__(self, key, **modificadores):
        self.key = key
        for nombre, valor in modificadores.items():
            setattr(self, nombre, valor)


def _correr(corutina):
    return asyncio.run(corutina)


@pytest.fixture
def entorno():
    """Un control de teclado instalado, con destinos y un modelo de selección."""
    pagina = PaginaFalsa()
    vertical, horizontal = DestinoFalso(), DestinoFalso()
    seleccion = SeleccionLista()
    acciones = []
    limpiezas = []

    control = ControlTeclado(
        obtener_pagina=lambda e=None: pagina,
        destino_vertical=lambda: vertical,
        destino_horizontal=lambda: horizontal,
        seleccion=seleccion,
        ejecutar_accion=lambda accion, e=None: acciones.append(accion),
        al_limpiar=lambda e=None: limpiezas.append(True),
    )
    control.instalar()
    return {
        "pagina": pagina, "vertical": vertical, "horizontal": horizontal,
        "seleccion": seleccion, "acciones": acciones, "limpiezas": limpiezas,
        "control": control,
    }


# ─── Instalación ─────────────────────────────────────────────────────────────

def test_instalar_toma_el_teclado_de_la_pagina(entorno):
    assert entorno["pagina"].on_keyboard_event is entorno["control"].handler
    assert entorno["control"].instalado is True


def test_instalar_dos_veces_no_se_encadena_a_si_mismo(entorno):
    """Sin la guarda, el handler previo pasa a ser el propio control y cada
    pulsación se procesa recursivamente: una sola flecha desplazó cientos de
    veces antes de corregirlo. La guarda depende de comparar por identidad una
    referencia ESTABLE al handler, no `self.manejar`, que crea un método
    ligado nuevo en cada acceso."""
    control = entorno["control"]
    control.instalar()
    control.instalar()

    _correr(control.manejar(EventoFalso("Arrow Down")))
    assert len(entorno["vertical"].llamadas) == 1


def test_sin_pagina_la_instalacion_falla_sin_reventar():
    control = ControlTeclado(obtener_pagina=lambda e=None: None)
    assert control.instalar() is False
    assert control.instalado is False


def test_una_pagina_sin_teclado_no_rompe_la_vista():
    class PaginaSinTeclado:
        __slots__ = ()  # asignar `on_keyboard_event` lanza AttributeError

    control = ControlTeclado(obtener_pagina=lambda e=None: PaginaSinTeclado())
    assert control.instalar() is False


def test_desinstalar_devuelve_el_handler_anterior():
    pagina = PaginaFalsa()
    previo = lambda e: None
    pagina.on_keyboard_event = previo

    control = ControlTeclado(obtener_pagina=lambda e=None: pagina)
    control.instalar()
    control.desinstalar()

    assert pagina.on_keyboard_event is previo


# ─── El handler anterior sigue recibiendo teclas ─────────────────────────────

def test_el_handler_previo_sigue_recibiendo_las_teclas():
    """La vista comparte la página con el Dashboard: instalar los atajos de
    una lista no puede robarle el teclado al resto de la aplicación."""
    pagina = PaginaFalsa()
    recibidas = []
    pagina.on_keyboard_event = lambda e: recibidas.append(getattr(e, "key", None))

    destino = DestinoFalso()
    control = ControlTeclado(
        obtener_pagina=lambda e=None: pagina, destino_vertical=lambda: destino
    )
    control.instalar()

    _correr(control.manejar(EventoFalso("Arrow Down")))
    _correr(control.manejar(EventoFalso("A")))

    assert recibidas == ["Arrow Down", "A"]


def test_tambien_cede_las_teclas_que_esta_vista_consumio():
    """Otra parte de la aplicación puede tener un atajo legítimo sobre la
    misma tecla; consumirla aquí no debe esconderla."""
    pagina = PaginaFalsa()
    recibidas = []
    pagina.on_keyboard_event = lambda e: recibidas.append(getattr(e, "key", None))

    destino = DestinoFalso()
    control = ControlTeclado(
        obtener_pagina=lambda e=None: pagina, destino_vertical=lambda: destino
    )
    control.instalar()
    _correr(control.manejar(EventoFalso("Arrow Up")))

    assert destino.llamadas, "la flecha no se aplicó"
    assert recibidas == ["Arrow Up"]


def test_un_handler_previo_que_revienta_no_tumba_el_teclado():
    pagina = PaginaFalsa()

    def previo_roto(e):
        raise RuntimeError("el handler de otra vista falló")

    pagina.on_keyboard_event = previo_roto
    destino = DestinoFalso()
    control = ControlTeclado(
        obtener_pagina=lambda e=None: pagina, destino_vertical=lambda: destino
    )
    control.instalar()

    _correr(control.manejar(EventoFalso("Arrow Down")))
    assert destino.llamadas


def test_cede_tambien_a_un_handler_previo_asincrono():
    pagina = PaginaFalsa()
    recibidas = []

    async def previo(e):
        recibidas.append(getattr(e, "key", None))

    pagina.on_keyboard_event = previo
    control = ControlTeclado(obtener_pagina=lambda e=None: pagina)
    control.instalar()

    _correr(control.manejar(EventoFalso("A")))
    assert recibidas == ["A"]


# ─── Desplazamiento ──────────────────────────────────────────────────────────

def test_las_flechas_verticales_van_al_destino_vertical(entorno):
    _correr(entorno["control"].manejar(EventoFalso("Arrow Down")))
    assert entorno["vertical"].llamadas == [{"delta": PASO_VERTICAL, "duration": 200}]
    assert entorno["horizontal"].llamadas == []


def test_las_flechas_horizontales_van_al_destino_horizontal(entorno):
    _correr(entorno["control"].manejar(EventoFalso("Arrow Right")))
    assert entorno["horizontal"].llamadas == [{"delta": PASO_HORIZONTAL, "duration": 200}]
    assert entorno["vertical"].llamadas == []


def test_control_flecha_arriba_va_al_offset_cero(entorno):
    _correr(entorno["control"].manejar(EventoFalso("Arrow Up", ctrl=True)))
    assert entorno["vertical"].llamadas == [{"offset": 0.0, "duration": 200}]


def test_control_flecha_abajo_va_al_final(entorno):
    _correr(entorno["control"].manejar(EventoFalso("Arrow Down", ctrl=True)))
    llamada = entorno["vertical"].llamadas[0]
    assert llamada["delta"] > 10000


def test_el_destino_se_busca_al_pulsar_y_no_se_guarda():
    """La tabla se reconstruye en cada repintado: un control guardado al
    instalar sería un control que ya no está en pantalla."""
    pagina = PaginaFalsa()
    actual = {"destino": DestinoFalso()}
    control = ControlTeclado(
        obtener_pagina=lambda e=None: pagina,
        destino_vertical=lambda: actual["destino"],
    )
    control.instalar()

    primero = actual["destino"]
    _correr(control.manejar(EventoFalso("Arrow Down")))
    assert len(primero.llamadas) == 1

    actual["destino"] = DestinoFalso()  # repintado: control nuevo
    _correr(control.manejar(EventoFalso("Arrow Down")))

    assert len(primero.llamadas) == 1, "siguió desplazando el control viejo"
    assert len(actual["destino"].llamadas) == 1


def test_sin_destino_en_un_eje_la_flecha_no_hace_nada():
    pagina = PaginaFalsa()
    vertical = DestinoFalso()
    control = ControlTeclado(
        obtener_pagina=lambda e=None: pagina, destino_vertical=lambda: vertical
    )
    control.instalar()

    _correr(control.manejar(EventoFalso("Arrow Right")))  # sin destino horizontal
    assert vertical.llamadas == []


def test_un_destino_sin_scroll_no_tumba_el_teclado():
    pagina = PaginaFalsa()
    control = ControlTeclado(
        obtener_pagina=lambda e=None: pagina, destino_vertical=lambda: DestinoRoto()
    )
    control.instalar()
    _correr(control.manejar(EventoFalso("Arrow Down")))  # no debe propagar


def test_un_destino_desmontado_no_tumba_el_teclado():
    pagina = PaginaFalsa()
    control = ControlTeclado(
        obtener_pagina=lambda e=None: pagina, destino_vertical=lambda: None
    )
    control.instalar()
    _correr(control.manejar(EventoFalso("Arrow Down")))


# ─── La regla del foco ───────────────────────────────────────────────────────

def test_con_un_campo_enfocado_las_flechas_no_desplazan(entorno):
    entorno["control"].foco.tomar("busqueda")
    _correr(entorno["control"].manejar(EventoFalso("Arrow Down")))
    assert entorno["vertical"].llamadas == []


def test_escape_suelta_el_foco_y_devuelve_la_navegacion(entorno):
    """Sin esto, el usuario tendría que buscar un hueco de la pantalla donde
    hacer clic para volver a navegar con las flechas."""
    control = entorno["control"]
    control.foco.tomar("busqueda")

    _correr(control.manejar(EventoFalso("Escape")))
    assert control.foco.hay_campo_con_foco is False

    _correr(control.manejar(EventoFalso("Arrow Down")))
    assert entorno["vertical"].llamadas


# ─── Acciones F1–F6 ──────────────────────────────────────────────────────────

def test_sin_item_marcado_las_teclas_de_funcion_no_accionan(entorno):
    _correr(entorno["control"].manejar(EventoFalso("F6")))
    assert entorno["acciones"] == []


def test_con_item_marcado_la_tecla_acciona(entorno):
    entorno["seleccion"].seleccionar("P-001")
    _correr(entorno["control"].manejar(EventoFalso("F5")))
    assert entorno["acciones"] == ["editar"]


def test_las_seis_teclas_mapean_a_las_seis_acciones(entorno):
    entorno["seleccion"].seleccionar("P-001")
    for tecla in ("F1", "F2", "F3", "F4", "F5", "F6"):
        _correr(entorno["control"].manejar(EventoFalso(tecla)))
    assert entorno["acciones"] == ["info", "cobrar", "carrito", "historial", "editar", "borrar"]


def test_sin_modelo_de_seleccion_nunca_hay_seleccion():
    """Una vista que instala solo la navegación (Inicio, Gestión de Datos) no
    debe poder disparar acciones de ítem."""
    pagina = PaginaFalsa()
    acciones = []
    control = ControlTeclado(
        obtener_pagina=lambda e=None: pagina,
        ejecutar_accion=lambda a, e=None: acciones.append(a),
    )
    control.instalar()

    _correr(control.manejar(EventoFalso("F6")))
    assert control.hay_seleccion is False
    assert acciones == []


# ─── Escape y limpieza ───────────────────────────────────────────────────────

def test_escape_avisa_a_la_vista(entorno):
    entorno["seleccion"].seleccionar("P-001")
    _correr(entorno["control"].manejar(EventoFalso("Escape")))
    assert entorno["limpiezas"] == [True]


def test_escape_sin_nada_marcado_no_falla(entorno):
    _correr(entorno["control"].manejar(EventoFalso("Escape")))
    assert entorno["limpiezas"] == [True]


def test_una_tecla_cualquiera_no_hace_nada(entorno):
    entorno["seleccion"].seleccionar("P-001")
    _correr(entorno["control"].manejar(EventoFalso("K")))
    assert entorno["acciones"] == []
    assert entorno["vertical"].llamadas == []
    assert entorno["limpiezas"] == []
