"""Atajos de teclado de la lista de Inventario (segunda ola de octubre 2026).

Decisiones del usuario del proyecto que se blindan aquí (reemplazan la
propuesta del PDF, donde F1-F3 navegaban):

  - Con las flechas solas se navega arriba/abajo/izquierda/derecha según los
    scrolls que haya en la vista; con Ctrl+flecha se va hasta el extremo de
    ese eje. Es decir: las flechas hacen lo mismo que los botones de flecha de
    la pantalla, y Ctrl+flecha lo mismo que "ir al inicio" / "ir al final".
  - Las flechas navegan SOLO cuando ningún campo de texto tiene el foco: con
    el cursor dentro de un campo, las flechas mueven el cursor como en
    cualquier programa.
  - [Esc] limpia la selección y suelta el foco.
  - La vista comparte la página con el Dashboard, así que el handler de
    teclado que hubiera puesto debe seguir recibiendo las teclas.

La mecánica de las teclas se prueba aislada en `test_control_teclado.py`; lo
que se verifica aquí es el CABLEADO de esta vista: que los destinos de scroll
sean los controles correctos, que se resuelvan en la pulsación y que la regla
del foco cubra los campos reales de la pantalla.

Patrón de doble de página headless tomado de
`test_inventario_marcador_seleccion.py` / `test_inventario_dialogos_pila.py`;
las pulsaciones se ejercitan con `asyncio.run` porque `ControlTeclado.manejar`
es una corutina (dentro espera a `scroll_to`), igual que en
`test_control_teclado.py`.
"""
import asyncio

import flet as ft
import pytest

from ui.components.teclado_nav import PASO_HORIZONTAL, PASO_VERTICAL

CODIGOS = ("ATA-001", "ATA-002", "ATA-003")


class PageFalsa:
    """Página headless con teclado y pila de diálogos de Flet 0.86."""

    def __init__(self):
        self.dialogos = []
        self.overlay = []
        self.updates = 0
        self.on_keyboard_event = None

    def show_dialog(self, dialog):
        if dialog in self.dialogos:
            raise RuntimeError("Dialog is already opened")
        dialog.open = True
        self.dialogos.append(dialog)

    def pop_dialog(self):
        dlg = next((d for d in reversed(self.dialogos) if d.open), None)
        if dlg is not None:
            dlg.open = False
        return dlg

    def update(self):
        self.updates += 1


class EventoFalso:
    def __init__(self, page):
        self.page = page


class TeclaFalsa:
    def __init__(self, page, key, **modificadores):
        self.page = page
        self.key = key
        for nombre, valor in modificadores.items():
            setattr(self, nombre, valor)


class DestinoFalso:
    """Suplente de un control con scroll: registra cada `scroll_to`.

    Hace falta porque un control de Flet sin página viva lanza al pedirle
    `scroll_to`, y `ControlTeclado` traga esa excepción a propósito (un destino
    desmontado no puede tumbar el teclado): sin el suplente, una flecha que no
    desplaza nada y una flecha que desplaza bien se verían idénticas.

    Expone `page` porque el suplente del cuerpo ocupa el lugar del control por
    el que la vista alcanza la página cuando no hay evento (ver
    `InventarioView._get_page`): un control montado de verdad también la
    expone.
    """

    def __init__(self, page=None):
        self.llamadas = []
        self.page = page

    async def scroll_to(self, **kwargs):
        self.llamadas.append(kwargs)


@pytest.fixture
def pagina():
    return PageFalsa()


@pytest.fixture
def evento(pagina):
    return EventoFalso(pagina)


@pytest.fixture
def productos(db_temporal):
    from services.inventario_service import crear_producto

    for i, codigo in enumerate(CODIGOS, start=1):
        crear_producto(
            codigo=codigo,
            referencia=f"REF-{i}",
            descripcion_general=f"Producto con atajos {i}",
            departamento="Pruebas",
            marca="ACME",
            precio_dolares=10.0 * i,
            existencia=3,
            costo_usd_efectivo=5.0 * i,
            rol_usuario="administrador",
        )
    return list(CODIGOS)


@pytest.fixture
def vista(productos, pagina):
    """Vista de administrador con el teclado ya enganchado a la página falsa."""
    from ui.views.inventario_view import InventarioView

    v = InventarioView(es_admin=True, username="atajos", rol_usuario="administrador")
    v.get_body()
    v._teclado.instalar(EventoFalso(pagina))
    return v


@pytest.fixture
def destinos(vista, pagina):
    """Sustituye los dos controles con scroll por suplentes observables."""
    vertical, horizontal = DestinoFalso(pagina), DestinoFalso()
    vista._body_scroll_col = vertical
    vista._tabla_scroll_row = horizontal
    return {"vertical": vertical, "horizontal": horizontal}


def _pulsar(vista, pagina, tecla, **modificadores):
    return asyncio.run(vista._teclado.manejar(TeclaFalsa(pagina, tecla, **modificadores)))


# ─────────────────────────────────────────────────────────────────────────────
# Enganche a la página
# ─────────────────────────────────────────────────────────────────────────────
def test_el_cuerpo_toma_el_teclado_al_montarse(productos, pagina):
    """El Dashboard descarta la vista y se queda con su cuerpo (y `View.page`
    es de solo lectura), así que el montaje del cuerpo es el único momento en
    que los atajos pueden engancharse sin esperar un clic del usuario: las
    flechas tienen que navegar desde que aparece la pantalla."""
    from ui.views.inventario_view import InventarioView

    v = InventarioView(es_admin=True, username="atajos", rol_usuario="administrador")
    cuerpo = v.get_body()

    assert cuerpo.did_mount == v._al_montar_cuerpo, "el cuerpo debe avisar al montarse"
    # Montaje: a partir de aquí el cuerpo está en el árbol y expone la página.
    v._body_scroll_col = DestinoFalso(pagina)
    cuerpo.did_mount()

    assert pagina.on_keyboard_event is v._teclado.handler


def test_sin_pagina_la_vista_se_construye_igual(productos):
    """Headless (como en las pruebas y en el primer `get_body()` de `__init__`)
    no hay teclado que tomar, y eso no puede impedir construir la vista."""
    from ui.views.inventario_view import InventarioView

    v = InventarioView(es_admin=True, username="atajos", rol_usuario="administrador")
    v.get_body()

    assert v._teclado.instalado is False


def test_el_handler_previo_de_la_pagina_sigue_recibiendo_teclas(productos, pagina):
    """La vista comparte la página con el Dashboard: enganchar los atajos del
    Inventario no puede robarle el teclado al resto de la aplicación."""
    recibidas = []
    pagina.on_keyboard_event = lambda ev: recibidas.append(getattr(ev, "key", None))

    from ui.views.inventario_view import InventarioView

    v = InventarioView(es_admin=True, username="atajos", rol_usuario="administrador")
    v.get_body()
    v._teclado.instalar(EventoFalso(pagina))

    asyncio.run(pagina.on_keyboard_event(TeclaFalsa(pagina, "Arrow Down")))
    asyncio.run(pagina.on_keyboard_event(TeclaFalsa(pagina, "Escape")))

    assert recibidas == ["Arrow Down", "Escape"]


def test_instalar_dos_veces_no_duplica_el_desplazamiento(vista, destinos, pagina):
    """Cada clic en una fila reintenta `instalar()`: si no fuera idempotente,
    el control acabaría encadenado a sí mismo y una sola flecha desplazaría
    muchas veces."""
    vista._teclado.instalar(EventoFalso(pagina))
    vista._teclado.instalar(EventoFalso(pagina))

    _pulsar(vista, pagina, "Arrow Down")

    assert len(destinos["vertical"].llamadas) == 1


# ─────────────────────────────────────────────────────────────────────────────
# Destinos: las flechas mueven lo mismo que los botones de la pantalla
# ─────────────────────────────────────────────────────────────────────────────
def test_los_destinos_son_los_controles_duenos_de_cada_eje(vista):
    """Un solo dueño por eje: el cuerpo de la página scrollea en vertical y la
    Row de la tabla en horizontal (ver `test_scroll_nav_inventario.py`)."""
    assert vista._destino_scroll_vertical() is vista._body_scroll_col
    assert vista._body_scroll_col.scroll == ft.ScrollMode.AUTO
    assert vista._destino_scroll_horizontal() is vista._tabla_scroll_row
    assert vista._tabla_scroll_row.scroll == ft.ScrollMode.ALWAYS


def test_el_destino_se_resuelve_en_la_pulsacion_y_no_se_guarda(vista, pagina):
    """La tabla se reconstruye en cada repintado: un control guardado al
    instalar sería un control que ya no está en pantalla."""
    primero = DestinoFalso()
    vista._body_scroll_col = primero
    _pulsar(vista, pagina, "Arrow Down")
    assert len(primero.llamadas) == 1

    segundo = DestinoFalso()  # repintado: control nuevo
    vista._body_scroll_col = segundo
    _pulsar(vista, pagina, "Arrow Down")

    assert len(primero.llamadas) == 1, "siguió desplazando el control viejo"
    assert len(segundo.llamadas) == 1


# ─────────────────────────────────────────────────────────────────────────────
# Las cuatro flechas y el salto al extremo
# ─────────────────────────────────────────────────────────────────────────────
def test_flecha_abajo_baja_la_vista(vista, destinos, pagina):
    _pulsar(vista, pagina, "Arrow Down")

    assert destinos["vertical"].llamadas == [{"delta": PASO_VERTICAL, "duration": 200}]
    assert destinos["horizontal"].llamadas == []


def test_flecha_arriba_sube_la_vista(vista, destinos, pagina):
    _pulsar(vista, pagina, "Arrow Up")

    assert destinos["vertical"].llamadas == [{"delta": -PASO_VERTICAL, "duration": 200}]


def test_flecha_derecha_desplaza_la_tabla_a_la_derecha(vista, destinos, pagina):
    _pulsar(vista, pagina, "Arrow Right")

    assert destinos["horizontal"].llamadas == [{"delta": PASO_HORIZONTAL, "duration": 200}]
    assert destinos["vertical"].llamadas == []


def test_flecha_izquierda_desplaza_la_tabla_a_la_izquierda(vista, destinos, pagina):
    _pulsar(vista, pagina, "Arrow Left")

    assert destinos["horizontal"].llamadas == [{"delta": -PASO_HORIZONTAL, "duration": 200}]


def test_control_flecha_arriba_va_al_primer_item(vista, destinos, pagina):
    """Equivale al botón "ir arriba del todo" del cluster vertical."""
    _pulsar(vista, pagina, "Arrow Up", ctrl=True)

    assert destinos["vertical"].llamadas == [{"offset": 0.0, "duration": 200}]


def test_control_flecha_izquierda_va_al_inicio_de_la_tabla(vista, destinos, pagina):
    """Equivale al botón "ir al Código (inicio)" del cluster horizontal."""
    _pulsar(vista, pagina, "Arrow Left", ctrl=True)

    assert destinos["horizontal"].llamadas == [{"offset": 0.0, "duration": 200}]


def test_control_flecha_abajo_va_al_final_de_la_lista(vista, destinos, pagina):
    _pulsar(vista, pagina, "Arrow Down", ctrl=True)

    assert destinos["vertical"].llamadas[0]["delta"] > 10000


def test_control_flecha_derecha_va_al_final_de_la_tabla(vista, destinos, pagina):
    _pulsar(vista, pagina, "Arrow Right", ctrl=True)

    assert destinos["horizontal"].llamadas[0]["delta"] > 10000


def test_una_tecla_cualquiera_no_desplaza_nada(vista, destinos, pagina):
    _pulsar(vista, pagina, "K")

    assert destinos["vertical"].llamadas == []
    assert destinos["horizontal"].llamadas == []


# ─────────────────────────────────────────────────────────────────────────────
# Escape
# ─────────────────────────────────────────────────────────────────────────────
def test_escape_limpia_la_seleccion(vista, evento, pagina):
    vista.seleccionar_item("ATA-002", evento)

    _pulsar(vista, pagina, "Escape")

    assert vista._seleccion.hay_seleccion is False


def test_escape_suelta_el_foco_y_devuelve_la_navegacion(vista, destinos, pagina):
    """Sin esto, el usuario tendría que buscar un hueco de la pantalla donde
    hacer clic para que las flechas volvieran a navegar."""
    vista._teclado.foco.tomar("busqueda")

    _pulsar(vista, pagina, "Escape")
    assert vista._teclado.foco.hay_campo_con_foco is False

    _pulsar(vista, pagina, "Arrow Down")
    assert destinos["vertical"].llamadas, "tras [Esc] las flechas deben navegar"
