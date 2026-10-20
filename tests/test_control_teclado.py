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


# ─── Relevo entre controles de la misma vista ────────────────────────────────

def _cadena(pagina) -> int:
    """Cuántos controles de teclado hay encadenados en la página."""
    largo = 0
    handler = getattr(pagina, "on_keyboard_event", None)
    while handler is not None:
        control = getattr(handler, "_control_teclado", None)
        if control is None:
            break
        largo += 1
        handler = control._handler_previo
    return largo


def _control(pagina, identidad=None, destino=None):
    return ControlTeclado(
        obtener_pagina=lambda e=None: pagina,
        destino_vertical=(lambda: destino) if destino is not None else None,
        identidad=identidad,
    )


def test_una_vista_reconstruida_releva_a_la_anterior():
    """El Dashboard reemplaza sus vistas en cada repintado. Sin relevo, la
    cadena de handlers crece sin tope y cada pulsación recorre todas las
    instancias pasadas."""
    pagina = PaginaFalsa()
    for _ in range(5):
        _control(pagina, identidad="ventas").instalar()

    assert _cadena(pagina) == 1


def test_el_control_relevado_queda_marcado_como_no_instalado():
    pagina = PaginaFalsa()
    viejo = _control(pagina, identidad="ventas")
    viejo.instalar()
    nuevo = _control(pagina, identidad="ventas")
    nuevo.instalar()

    assert viejo.instalado is False
    assert nuevo.instalado is True


def test_la_instancia_vieja_ya_no_recibe_las_teclas():
    """Era el defecto concreto: la vista anterior seguía actuando sobre una
    tabla que ya no estaba en pantalla, y el atajo se ejecutaba dos veces."""
    pagina = PaginaFalsa()
    destino_viejo, destino_nuevo = DestinoFalso(), DestinoFalso()

    _control(pagina, identidad="ventas", destino=destino_viejo).instalar()
    _control(pagina, identidad="ventas", destino=destino_nuevo).instalar()

    _correr(pagina.on_keyboard_event(EventoFalso("Arrow Down")))

    assert destino_viejo.llamadas == []
    assert len(destino_nuevo.llamadas) == 1


def test_el_relevo_hereda_el_handler_previo_ajeno():
    """Relevar a la vista anterior no puede costarle el teclado al Dashboard,
    que estaba debajo en la cadena."""
    pagina = PaginaFalsa()
    recibidas = []
    pagina.on_keyboard_event = lambda e: recibidas.append(getattr(e, "key", None))

    _control(pagina, identidad="ventas").instalar()
    _control(pagina, identidad="ventas").instalar()

    _correr(pagina.on_keyboard_event(EventoFalso("Arrow Down")))
    assert recibidas == ["Arrow Down"]


def test_dos_vistas_distintas_si_se_encadenan():
    """Identidades distintas son pantallas distintas que conviven: el
    Dashboard y la vista que aloja, por ejemplo."""
    pagina = PaginaFalsa()
    _control(pagina, identidad="inicio").instalar()
    _control(pagina, identidad="ventas").instalar()

    assert _cadena(pagina) == 2


def test_sin_identidad_se_encadena_como_antes():
    """Comportamiento conservador: un control sin identidad declarada no
    releva a nadie, porque no hay forma de saber si es el mismo."""
    pagina = PaginaFalsa()
    _control(pagina).instalar()
    _control(pagina).instalar()

    assert _cadena(pagina) == 2


def test_una_vista_sin_identidad_no_releva_a_una_con_identidad():
    pagina = PaginaFalsa()
    _control(pagina, identidad="ventas").instalar()
    _control(pagina).instalar()

    assert _cadena(pagina) == 2


# ─── Ciclos en la cadena (el cuelgue de la aplicación) ──────────────────────

def _largo_cadena(control, tope: int = 50) -> int:
    """Cuántos eslabones hay por debajo de `control`, cortando si hay ciclo."""
    vistos = set()
    largo = 0
    handler = control._handler_previo
    while handler is not None and largo < tope:
        duenio = getattr(handler, "_control_teclado", None)
        if duenio is None or id(duenio) in vistos:
            break
        vistos.add(id(duenio))
        largo += 1
        handler = duenio._handler_previo
    return largo


def test_el_contenedor_que_se_reinstala_no_forma_un_ciclo():
    """La regresión que congelaba la aplicación.

    El Dashboard es UNA sola instancia que vuelve a instalarse al final de
    cada repintado, y para entonces el teclado lo tiene la vista que acaba de
    construir, cuya cadena ya apunta al Dashboard. Sin cortar la cadena, queda
    Dashboard → Ventas → Dashboard → …, y una sola pulsación daba cientos de
    vueltas: en la aplicación real abrió 120 diálogos y hubo que cerrarla.
    """
    pagina = PaginaFalsa()
    dashboard = _control(pagina, identidad="dashboard")
    vista = _control(pagina, identidad="ventas")

    # Primer render: la vista anidada se engancha y después el contenedor.
    vista.instalar()
    dashboard.instalar()
    # Repintado: el contenedor se reinstala con la vista al frente.
    dashboard.instalar()

    assert _largo_cadena(dashboard) < 10, "la cadena quedó ciclada"


def test_una_pulsacion_recorre_cada_control_una_sola_vez():
    """Medida de verdad del defecto: contar ejecuciones, no eslabones."""
    pagina = PaginaFalsa()
    destino_vista = DestinoFalso()
    destino_dash = DestinoFalso()

    dashboard = _control(pagina, identidad="dashboard", destino=destino_dash)
    vista = _control(pagina, identidad="ventas", destino=destino_vista)

    vista.instalar()
    dashboard.instalar()
    dashboard.instalar()
    vista.instalar()
    dashboard.instalar()

    _correr(pagina.on_keyboard_event(EventoFalso("Arrow Down")))

    assert len(destino_vista.llamadas) <= 1, destino_vista.llamadas
    assert len(destino_dash.llamadas) <= 1, destino_dash.llamadas


def test_la_accion_se_ejecuta_una_sola_vez_por_pulsacion():
    """En la aplicación real cada vuelta del bucle abría un diálogo."""
    pagina = PaginaFalsa()
    seleccion = SeleccionLista()
    seleccion.seleccionar("P-001")
    aperturas = []

    vista = ControlTeclado(
        obtener_pagina=lambda e=None: pagina,
        seleccion=seleccion,
        ejecutar_accion=lambda accion, e=None: aperturas.append(accion),
        identidad="ventas",
    )
    dashboard = _control(pagina, identidad="dashboard")

    vista.instalar()
    dashboard.instalar()
    dashboard.instalar()

    _correr(pagina.on_keyboard_event(EventoFalso("F5")))

    assert aperturas == ["editar"], aperturas


def test_reinstalar_en_cualquier_orden_no_cicla():
    """El orden real depende de qué sección se dibuja y cuántas veces."""
    pagina = PaginaFalsa()
    dashboard = _control(pagina, identidad="dashboard")
    ventas = _control(pagina, identidad="ventas")
    inventario = _control(pagina, identidad="inventario")

    for _ in range(4):
        for control in (ventas, dashboard, inventario, dashboard, ventas):
            control.instalar()

    for control in (dashboard, ventas, inventario):
        assert _largo_cadena(control) < 10


def test_una_cadena_ya_ciclada_se_corta_al_reinstalar():
    """Si alguien enreda la cadena por otro camino, instalar debe repararla
    en vez de quedarse dando vueltas al intentarlo."""
    pagina = PaginaFalsa()
    uno = _control(pagina, identidad="uno")
    dos = _control(pagina, identidad="dos")

    uno.instalar()
    dos.instalar()
    uno._handler_previo = dos.handler  # ciclo forzado a mano

    uno.instalar()  # no debe colgarse
    assert _largo_cadena(uno) < 10


def test_la_guarda_de_reentrada_corta_una_cadena_ciclada():
    """Cinturón y tirantes: aunque la cadena quede mal, una tecla no puede
    congelar la ventana."""
    pagina = PaginaFalsa()
    destino = DestinoFalso()
    uno = _control(pagina, identidad="uno", destino=destino)
    dos = _control(pagina, identidad="dos")

    uno.instalar()
    dos.instalar()
    uno._handler_previo = dos.handler  # ciclo forzado, sin pasar por instalar

    _correr(pagina.on_keyboard_event(EventoFalso("Arrow Down")))

    assert len(destino.llamadas) <= 1


def test_la_guarda_de_reentrada_se_libera_entre_pulsaciones():
    """No puede quedarse trabada: la segunda tecla tiene que funcionar."""
    pagina = PaginaFalsa()
    destino = DestinoFalso()
    control = _control(pagina, identidad="uno", destino=destino)
    control.instalar()

    _correr(pagina.on_keyboard_event(EventoFalso("Arrow Down")))
    _correr(pagina.on_keyboard_event(EventoFalso("Arrow Down")))

    assert len(destino.llamadas) == 2


def test_la_guarda_se_libera_aunque_la_accion_reviente():
    def accion_rota(accion, e=None):
        raise RuntimeError("la vista fallo")

    pagina = PaginaFalsa()
    seleccion = SeleccionLista()
    seleccion.seleccionar("P-001")
    control = ControlTeclado(
        obtener_pagina=lambda e=None: pagina,
        seleccion=seleccion,
        ejecutar_accion=accion_rota,
        identidad="uno",
    )
    control.instalar()

    with pytest.raises(RuntimeError):
        _correr(pagina.on_keyboard_event(EventoFalso("F5")))

    assert control._procesando is False


# ─── Repintado tras una acción de teclado ────────────────────────────────────

class PaginaRepintable(PaginaFalsa):
    """Cuenta los repintados además de manejar la pila de diálogos."""

    def __init__(self):
        super().__init__()
        self.updates = 0

    def update(self):
        self.updates += 1


def _control_con_accion(pagina, accion_hecha):
    seleccion = SeleccionLista()
    seleccion.seleccionar("P-001")
    control = ControlTeclado(
        obtener_pagina=lambda e=None: pagina,
        seleccion=seleccion,
        ejecutar_accion=lambda a, e=None: accion_hecha.append(a),
        identidad="inventario",
    )
    control.instalar()
    return control


def test_una_accion_de_teclado_repinta_la_pagina():
    """Flet acumula los cambios del árbol mientras maneja un evento y los manda
    al terminar. Un atajo de teclado no cuelga de ningún control, así que ese
    envío no llega y el diálogo que la acción apiló se queda sin dibujar: en la
    aplicación real se veía como "F1 no hace nada", y aparecía al clic
    siguiente."""
    pagina = PaginaRepintable()
    hechas = []
    control = _control_con_accion(pagina, hechas)

    _correr(control.manejar(EventoFalso("F1")))

    assert hechas == ["info"]
    assert pagina.updates >= 1, "la acción se ejecutó pero nadie repintó"


def test_el_repintado_se_agenda_despues_del_despacho():
    """Repintar dentro del despacho no alcanza: el cambio vuelve a la misma
    cola. Con un bucle de eventos vivo, el repintado tiene que ocurrir en una
    tarea posterior."""

    async def escenario():
        pagina = PaginaRepintable()
        hechas = []
        control = _control_con_accion(pagina, hechas)

        await control.manejar(EventoFalso("F1"))
        # Todavía dentro del mismo ciclo: puede o no haber repintado.
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        return pagina.updates

    assert asyncio.run(escenario()) >= 1


def test_las_flechas_no_necesitan_repintado():
    """`scroll_to` es una llamada directa al cliente, no un cambio del árbol:
    por eso navegar siempre funcionó y abrir un diálogo no."""
    pagina = PaginaRepintable()
    destino = DestinoFalso()
    control = ControlTeclado(
        obtener_pagina=lambda e=None: pagina,
        destino_vertical=lambda: destino,
        identidad="inventario",
    )
    control.instalar()

    _correr(control.manejar(EventoFalso("Arrow Down")))
    assert destino.llamadas


def test_sin_pagina_el_repintado_no_falla():
    """La vista puede haberse desmontado entre la pulsación y el dibujo."""
    seleccion = SeleccionLista()
    seleccion.seleccionar("P-001")
    control = ControlTeclado(
        obtener_pagina=lambda e=None: None,
        seleccion=seleccion,
        ejecutar_accion=lambda a, e=None: None,
        identidad="inventario",
    )
    _correr(control.manejar(EventoFalso("F1")))  # no debe lanzar


def test_una_pagina_que_rechaza_update_no_tumba_la_tecla():
    class PaginaRota(PaginaFalsa):
        def update(self):
            raise RuntimeError("desmontada")

    pagina = PaginaRota()
    hechas = []
    control = _control_con_accion(pagina, hechas)

    _correr(control.manejar(EventoFalso("F1")))
    assert hechas == ["info"]
