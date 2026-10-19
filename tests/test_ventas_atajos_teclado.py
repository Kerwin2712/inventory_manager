"""Atajos de teclado del módulo de Ventas (`ui/views/ventas_view.py`).

Decisiones del usuario del proyecto que se blindan aquí:

  - **Navegación con flechas.** Las cuatro flechas desplazan el eje que
    corresponda del carrito y Ctrl+flecha va hasta el extremo de ese eje, lo
    mismo que hacen los botones de flecha y los de "ir al inicio"/"ir al
    final" de la barra.
  - **La regla del foco.** Las flechas navegan SOLO cuando ningún campo de
    texto tiene el cursor: si el usuario está escribiendo, las flechas mueven
    el cursor como en cualquier programa. Un campo sin enlazar al registro de
    foco le mueve la pantalla al usuario mientras escribe, que es justo lo
    que la regla evita.
  - **F1–F6 actúan solo sobre el renglón marcado.** F5 edita el renglón y F6
    lo quita del carrito; F1, F2, F3 y F4 quedan INERTES (se usa el mapeo
    canónico de `ATAJOS_ITEM` y no un mapeo propio del carrito, para que la
    misma tecla haga lo mismo en todas las listas). Sin nada marcado, ninguna
    tecla hace nada.
  - **F6 no pide la clave del usuario.** Quitar un renglón de un carrito no
    borra ningún dato del sistema: solo saca un artículo de una venta que
    todavía no se procesó.
  - **La página se comparte con el Dashboard**, así que el handler de teclado
    que ya estuviera puesto tiene que seguir recibiendo teclas.

El handler de `ControlTeclado` es `async` (`Control.scroll_to` es una
corutina), así que se ejercita con `asyncio.run`, igual que en
`tests/test_control_teclado.py`.
"""
import asyncio

import flet as ft
import pytest

from services.bcv_service import actualizar_tasa
from services.cart_manager import limpiar_sesion, obtener_carrito_activo
from services.inventario_service import crear_producto
from ui.views.ventas_view import VentasView

CODIGOS = ("TEC-001", "TEC-002", "TEC-003")


class PageFalsa:
    """Página headless con pila de diálogos y soporte de teclado."""

    def __init__(self):
        self.dialogos = []
        self.overlay = []
        self.updates = 0
        self.on_keyboard_event = None

    def show_dialog(self, dialog):
        dialog.open = True
        self.dialogos.append(dialog)
        self.updates += 1

    def pop_dialog(self):
        dlg = next((d for d in reversed(self.dialogos) if d.open), None)
        if dlg is not None:
            dlg.open = False
            self.updates += 1
        return dlg

    def update(self):
        self.updates += 1

    @property
    def visible(self):
        return next((d for d in reversed(self.dialogos) if d.open), None)


class EventoFalso:
    def __init__(self, page, control=None):
        self.page = page
        self.control = control


class TeclaFalsa:
    """`KeyboardEvent` mínimo: `key` más los modificadores que haga falta."""

    def __init__(self, page, key, **modificadores):
        self.page = page
        self.key = key
        self.control = None
        for nombre, valor in modificadores.items():
            setattr(self, nombre, valor)


class DestinoEspia:
    """Control con scroll que anota cada `scroll_to` recibido.

    Se guarda solo el desplazamiento pedido (`offset`/`delta`): la duración de
    la animación la fija el control de teclado y no es parte de lo que se
    quiere blindar aquí.
    """

    def __init__(self):
        self.llamadas = []

    async def scroll_to(self, **kwargs):
        kwargs.pop("duration", None)
        self.llamadas.append(kwargs)


def _pulsar(vista, pagina, key, **modificadores):
    """Entrega la tecla por el MISMO camino que la página real: el handler que
    quedó en `page.on_keyboard_event`."""
    evento = TeclaFalsa(pagina, key, **modificadores)
    asyncio.run(pagina.on_keyboard_event(evento))
    return evento


@pytest.fixture
def pagina():
    return PageFalsa()


@pytest.fixture
def evento(pagina):
    return EventoFalso(pagina)


@pytest.fixture
def vista(db_temporal, pagina):
    """`VentasView` con tres renglones en el carrito y el teclado ya instalado
    en una página falsa (como si el Dashboard la hubiera montado)."""
    actualizar_tasa(40.0)
    for i, codigo in enumerate(CODIGOS, start=1):
        crear_producto(
            codigo=codigo, referencia=f"REF-{i}",
            descripcion_general=f"Articulo de prueba {i}",
            departamento="Pruebas", marca="ACME",
            precio_dolares=10.0 * i, precio_bcv=11.0 * i,
            existencia=20.0, nombre_referencia_corto=f"Art {i}",
            costo_usd_efectivo=5.0 * i, rol_usuario="administrador",
        )

    v = VentasView(page=pagina, user_data={"username": "vendedor", "role": "administrador"})
    v.get_body()
    limpiar_sesion(v._sid)
    for i, codigo in enumerate(CODIGOS, start=1):
        v.agregar_producto_directo(
            {"codigo": codigo, "precio_dolares": 10.0 * i,
             "precio_bcv": 11.0 * i, "nombre_referencia_corto": f"Art {i}"},
            2.0, None,
        )
    v.tabla_carrito_container.content = v.build_tabla_carrito(
        obtener_carrito_activo(v._sid)["items"]
    )
    yield v
    limpiar_sesion(v._sid)


def _tabla(vista) -> ft.DataTable:
    from tests.test_ventas_marcador_carrito import _tabla as buscar

    return buscar(vista)


def _fila(vista, codigo) -> ft.DataRow:
    return next(r for r in _tabla(vista).rows if r.data == codigo)


def _marcar(vista, codigo, evento):
    _fila(vista, codigo).on_select_change(evento)
    vista.tabla_carrito_container.content = vista.build_tabla_carrito(
        obtener_carrito_activo(vista._sid)["items"]
    )


def _espiar_destinos(vista) -> tuple[DestinoEspia, DestinoEspia]:
    """Sustituye los destinos de scroll por espías, sin tocar el invocable que
    recibió `ControlTeclado` (que es justamente lo que se quiere ejercitar)."""
    vertical, horizontal = DestinoEspia(), DestinoEspia()
    vista._carrito_scroll_v = vertical
    vista._carrito_scroll_h = horizontal
    return vertical, horizontal


# ─── 1. Instalación del control de teclado ───────────────────────────────────

def test_la_vista_toma_el_teclado_de_la_pagina_al_construirse(vista, pagina):
    assert pagina.on_keyboard_event is vista._teclado.handler
    assert vista._teclado.instalado is True


def test_la_instalacion_es_idempotente(vista, pagina, evento):
    """Sin la guarda, el control acabaría encadenado a sí mismo y una sola
    flecha se procesaría cientos de veces."""
    handler = pagina.on_keyboard_event

    vista._asegurar_teclado(evento)
    vista._asegurar_teclado(evento)

    assert pagina.on_keyboard_event is handler


def test_el_handler_previo_de_la_pagina_sigue_recibiendo_teclas(db_temporal, pagina):
    """La vista comparte la página con el Dashboard: tomar el teclado no puede
    robárselo al resto de la aplicación."""
    recibidas = []
    pagina.on_keyboard_event = lambda e: recibidas.append(getattr(e, "key", None))

    v = VentasView(page=pagina, user_data={"username": "vendedor", "role": "administrador"})
    v.get_body()
    try:
        _pulsar(v, pagina, "Arrow Down")
        _pulsar(v, pagina, "F5")
        _pulsar(v, pagina, "Escape")
    finally:
        limpiar_sesion(v._sid)

    assert recibidas == ["Arrow Down", "F5", "Escape"]


def test_una_vista_headless_no_se_cae_al_no_poder_instalar(db_temporal):
    """Sin página, los atajos simplemente no existen y los botones en
    pantalla los suplen; lo que no puede pasar es que la vista no cargue."""
    v = VentasView(user_data={"username": "vendedor", "role": "administrador"})
    v.get_body()
    try:
        assert v._teclado.instalado is False
        assert v._asegurar_teclado() is False
    finally:
        limpiar_sesion(v._sid)


# ─── 2. Las cuatro flechas y Ctrl+flecha ─────────────────────────────────────

def test_las_flechas_verticales_desplazan_el_carrito_un_paso(vista, pagina):
    from ui.components.teclado_nav import PASO_VERTICAL

    vertical, horizontal = _espiar_destinos(vista)

    _pulsar(vista, pagina, "Arrow Down")
    _pulsar(vista, pagina, "Arrow Up")

    assert vertical.llamadas == [{"delta": PASO_VERTICAL}, {"delta": -PASO_VERTICAL}]
    assert horizontal.llamadas == []


def test_las_flechas_horizontales_desplazan_el_eje_ancho_de_la_tabla(vista, pagina):
    from ui.components.teclado_nav import PASO_HORIZONTAL

    vertical, horizontal = _espiar_destinos(vista)

    _pulsar(vista, pagina, "Arrow Right")
    _pulsar(vista, pagina, "Arrow Left")

    assert horizontal.llamadas == [{"delta": PASO_HORIZONTAL}, {"delta": -PASO_HORIZONTAL}]
    assert vertical.llamadas == []


def test_ctrl_con_flecha_va_hasta_el_extremo_del_eje(vista, pagina):
    """Equivale a los botones "ir al inicio" / "ir al final" de la barra: al
    inicio se va con `offset=0` (exacto) y al final con un delta enorme que
    Flutter acota al límite real del scroll."""
    vertical, horizontal = _espiar_destinos(vista)

    _pulsar(vista, pagina, "Arrow Up", ctrl=True)
    _pulsar(vista, pagina, "Arrow Down", ctrl=True)
    _pulsar(vista, pagina, "Arrow Left", ctrl=True)
    _pulsar(vista, pagina, "Arrow Right", ctrl=True)

    assert vertical.llamadas[0] == {"offset": 0.0}
    assert vertical.llamadas[1]["delta"] > 1000
    assert horizontal.llamadas[0] == {"offset": 0.0}
    assert horizontal.llamadas[1]["delta"] > 1000


def test_el_destino_de_las_flechas_se_busca_en_cada_pulsacion(vista, pagina):
    """La tabla se reconstruye en cada repintado: si el destino se hubiera
    guardado, la flecha desplazaría un control que ya no está en pantalla."""
    primero, _ = _espiar_destinos(vista)
    _pulsar(vista, pagina, "Arrow Down")

    segundo = DestinoEspia()
    vista._carrito_scroll_v = segundo
    _pulsar(vista, pagina, "Arrow Down")

    assert len(primero.llamadas) == 1
    assert len(segundo.llamadas) == 1


def test_con_el_carrito_vacio_las_flechas_verticales_van_al_panel_de_resultados(vista, pagina):
    """Sin tabla no hay nada que desplazar en el carrito, y el panel de
    resultados es lo único desplazable que queda en pantalla."""
    resultados = DestinoEspia()
    vista._carrito_scroll_v = None
    vista._resultados_scroll_v = resultados

    _pulsar(vista, pagina, "Arrow Down")

    assert len(resultados.llamadas) == 1


# ─── 3. La regla del foco ────────────────────────────────────────────────────

def test_con_un_campo_enfocado_las_flechas_no_desplazan_la_vista(vista, pagina):
    """Nadie espera que al corregir una palabra se le mueva la pantalla."""
    vertical, horizontal = _espiar_destinos(vista)
    vista.prod_search_input.on_focus(None)

    _pulsar(vista, pagina, "Arrow Down")
    _pulsar(vista, pagina, "Arrow Right")

    assert vertical.llamadas == []
    assert horizontal.llamadas == []


def test_al_soltar_el_campo_las_flechas_vuelven_a_desplazar(vista, pagina):
    vertical, _ = _espiar_destinos(vista)
    vista.prod_search_input.on_focus(None)
    vista.prod_search_input.on_blur(None)

    _pulsar(vista, pagina, "Arrow Down")

    assert len(vertical.llamadas) == 1


def test_escape_libera_el_foco_para_devolver_la_navegacion(vista, pagina):
    """[Esc] suelta el foco además de limpiar la marca: si no, el usuario
    tendría que buscar un hueco de la pantalla donde hacer clic."""
    vertical, _ = _espiar_destinos(vista)
    vista.cant_input.on_focus(None)

    _pulsar(vista, pagina, "Escape")
    _pulsar(vista, pagina, "Arrow Down")

    assert vista._registro_foco.hay_campo_con_foco is False
    assert len(vertical.llamadas) == 1


# ─── 4. Escape limpia la marca ───────────────────────────────────────────────

def test_escape_quita_la_marca_del_renglon(vista, pagina, evento):
    _marcar(vista, "TEC-002", evento)
    assert vista._seleccion.seleccionado == "TEC-002"

    _pulsar(vista, pagina, "Escape")

    assert vista._seleccion.hay_seleccion is False


# ─── 5. F5 y F6 sobre el renglón marcado ─────────────────────────────────────

def test_f5_abre_el_dialogo_de_edicion_del_renglon_marcado(vista, pagina, evento):
    _marcar(vista, "TEC-002", evento)

    _pulsar(vista, pagina, "F5")

    dlg = pagina.visible
    assert dlg is not None
    textos = [c.value for c in dlg.title.controls if isinstance(c, ft.Text)]
    assert any("Editar Renglón" in t for t in textos)


def test_f6_quita_del_carrito_el_renglon_marcado(vista, pagina, evento):
    _marcar(vista, "TEC-002", evento)

    _pulsar(vista, pagina, "F6")

    codigos = [i["codigo"] for i in obtener_carrito_activo(vista._sid)["items"]]
    assert codigos == ["TEC-001", "TEC-003"]


def test_f6_no_pide_la_clave_del_usuario(vista, pagina, evento):
    """Quitar un renglón de un carrito no borra ningún dato del sistema: solo
    saca un artículo de una venta que todavía no se procesó. La clave quedó
    reservada al borrado de ítems del inventario y de deudas, que sí
    destruyen información persistida."""
    _marcar(vista, "TEC-002", evento)

    _pulsar(vista, pagina, "F6")

    # Se removió de una, sin diálogo intermedio pidiendo nada.
    assert "TEC-002" not in [i["codigo"] for i in obtener_carrito_activo(vista._sid)["items"]]
    assert pagina.visible is None


def test_f6_deja_el_carrito_sin_marca_fantasma(vista, pagina, evento):
    _marcar(vista, "TEC-002", evento)

    _pulsar(vista, pagina, "F6")

    assert vista._seleccion.hay_seleccion is False


@pytest.mark.parametrize("tecla", ["F1", "F2", "F3", "F4"])
def test_f1_a_f4_no_hacen_nada_en_el_carrito(vista, pagina, evento, tecla):
    """Mapeo canónico: las teclas sin ícono equivalente en el carrito quedan
    inertes. En particular NO se les inventó un significado (se descartó
    expresamente mapear F3/F4 a subir y bajar la cantidad)."""
    _marcar(vista, "TEC-002", evento)
    antes = [dict(i) for i in obtener_carrito_activo(vista._sid)["items"]]

    _pulsar(vista, pagina, tecla)

    assert obtener_carrito_activo(vista._sid)["items"] == antes
    assert pagina.visible is None


@pytest.mark.parametrize("tecla", ["F1", "F2", "F3", "F4", "F5", "F6"])
def test_ninguna_tecla_hace_nada_sin_renglon_marcado(vista, pagina, tecla):
    """Sin ítem marcado no hay sobre qué actuar, y adivinar uno sería disparar
    una acción sobre algo que el usuario no eligió."""
    antes = [dict(i) for i in obtener_carrito_activo(vista._sid)["items"]]

    _pulsar(vista, pagina, tecla)

    assert obtener_carrito_activo(vista._sid)["items"] == antes
    assert pagina.visible is None


def test_las_teclas_entran_por_el_mismo_punto_de_entrada_que_los_botones(vista, pagina, evento):
    llamadas = []
    vista.ejecutar_accion_item = lambda accion, codigo, e=None: llamadas.append((accion, codigo))
    _marcar(vista, "TEC-003", evento)

    _pulsar(vista, pagina, "F5")
    _pulsar(vista, pagina, "F6")

    assert llamadas == [("editar", "TEC-003"), ("borrar", "TEC-003")]


def test_ejecutar_accion_sobre_seleccionado_sin_marca_devuelve_falso(vista, evento):
    assert vista.ejecutar_accion_sobre_seleccionado("editar", evento) is False


@pytest.mark.parametrize("accion", ["info", "cobrar", "carrito", "historial"])
def test_las_acciones_sin_equivalente_devuelven_falso(vista, evento, accion):
    _marcar(vista, "TEC-001", evento)

    assert vista.ejecutar_accion_sobre_seleccionado(accion, evento) is False
