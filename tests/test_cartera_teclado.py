"""Atajos de teclado de la Cartera: flechas para navegar y F2 / F5 / F6.

Decisiones del usuario del proyecto que esto blinda:

- **Navegación con flechas.** Con solo las flechas se navega según los scrolls
  que haya en la vista; Ctrl+flecha va hasta el final de ese eje. Las flechas
  navegan SOLO cuando ningún campo de texto tiene el foco: si el cursor está en
  un campo, las flechas mueven el cursor como en cualquier programa.
- **F1–F6 actúan solo sobre el renglón marcado.** En Deudas por Cobrar el mapeo
  canónico encaja directo con los tres botones: F2 Cobrar, F5 Editar y F6
  Borrar. F1, F3 y F4 quedan INERTES: no se les inventa equivalencia, porque
  una tecla que significa una cosa en una lista y otra en la de al lado es una
  trampa para quien aprende los atajos.
- Sin nada marcado, ninguna tecla de función hace nada.
- El handler de teclado que la página ya tuviera sigue recibiendo las teclas:
  esta vista comparte la página con el Dashboard.

El handler de `ControlTeclado` es **async** (`scroll_to` es una corutina), así
que aquí se ejerce con `asyncio.run`, igual que en `test_control_teclado.py`.
Un handler síncrono crearía la corutina y la descartaría en silencio.
"""
import asyncio

import flet as ft
import pytest

from services.cartera_service import crear_cliente
from services.deudas_service import crear_deuda, obtener_deuda, registrar_abono
from ui.components.teclado_nav import PASO_HORIZONTAL, PASO_VERTICAL

FUTURO = "31/12/2027"

ITEMS = [
    {"producto_codigo": "P-001", "descripcion_corta": "Filtro de aceite", "cantidad": 2, "subtotal_usd": 20.0},
]


class PageFalsa:
    """Pila de diálogos de Flet 0.86 más el gancho de teclado de la página."""

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

    @property
    def visible(self):
        return next((d for d in reversed(self.dialogos) if d.open), None)


class EventoFalso:
    def __init__(self, page):
        self.page = page


class TeclaFalsa:
    """`KeyboardEvent` mínimo: `ControlTeclado` lee los modificadores con
    `getattr`, así que basta con `key` y lo que se quiera forzar."""

    def __init__(self, key, **modificadores):
        self.key = key
        for nombre, valor in modificadores.items():
            setattr(self, nombre, valor)


class DestinoFalso:
    """Control con scroll: registra cada `scroll_to` recibido."""

    def __init__(self):
        self.llamadas = []

    async def scroll_to(self, **kwargs):
        self.llamadas.append(kwargs)


def _correr(corutina):
    return asyncio.run(corutina)


def _pulsar(v, tecla: str, **modificadores):
    """Dispara el handler real de la página, que es el del `ControlTeclado`."""
    return _correr(v._teclado.manejar(TeclaFalsa(tecla, **modificadores)))


@pytest.fixture
def pagina():
    return PageFalsa()


@pytest.fixture
def evento(pagina):
    return EventoFalso(pagina)


@pytest.fixture
def cliente(db_temporal):
    return crear_cliente(nombre="Fulano de Tal", cedula_rif="V-12345678", telefono="0414-1234567")


@pytest.fixture
def deuda(cliente):
    return crear_deuda("V-12345678", 100.0, FUTURO, items=ITEMS)


@pytest.fixture
def vista(db_temporal):
    def _construir():
        from ui.views.cartera_view import CarteraView

        return CarteraView(user_data={"username": "cajera2", "role": "vendedor"})
    return _construir


@pytest.fixture
def en_deudas(vista, evento):
    """Vista montada, con el teclado enganchado y la pestaña de Deudas activa."""
    def _montar():
        v = vista()
        v.current_tab = "deudas"
        v._asegurar_teclado(evento)
        return v
    return _montar


@pytest.fixture
def destinos(en_deudas):
    """La vista con los dos ejes de la pestaña de Deudas sustituidos por dobles
    que anotan los desplazamientos."""
    def _montar():
        v = en_deudas()
        vertical, horizontal = DestinoFalso(), DestinoFalso()
        v._deu_scroll_vertical = vertical
        v._deu_scroll_horizontal = horizontal
        return v, vertical, horizontal
    return _montar


# ─── Instalación en la página ────────────────────────────────────────────────

def test_la_vista_engancha_el_teclado_de_la_pagina(en_deudas, pagina):
    v = en_deudas()
    assert pagina.on_keyboard_event is v._teclado.handler


def test_enganchar_dos_veces_no_duplica_el_procesamiento(destinos, evento):
    """Sin la guarda de idempotencia, el control queda encadenado a sí mismo y
    una sola flecha se procesa muchas veces."""
    v, vertical, _ = destinos()
    v._asegurar_teclado(evento)
    v._asegurar_teclado(evento)

    _pulsar(v, "Arrow Down")
    assert len(vertical.llamadas) == 1


def test_el_handler_previo_de_la_pagina_sigue_recibiendo_teclas(vista, pagina, evento):
    """La Cartera comparte la página con el Dashboard: tomar el teclado no
    puede robárselo al resto de la aplicación."""
    recibidas = []
    pagina.on_keyboard_event = lambda ev: recibidas.append(getattr(ev, "key", None))

    v = vista()
    v.current_tab = "deudas"
    v._asegurar_teclado(evento)

    _pulsar(v, "Arrow Down")
    _pulsar(v, "F6")
    _pulsar(v, "K")

    assert recibidas == ["Arrow Down", "F6", "K"]


def test_sin_pagina_el_enganche_falla_sin_reventar(vista):
    """La vista se instancia headless y se monta después: hasta entonces no hay
    página, y eso no puede ser un error."""
    v = vista()
    assert v._asegurar_teclado(None) is False


# ─── Las flechas desplazan el destino correcto ───────────────────────────────

def test_la_flecha_abajo_desplaza_el_eje_vertical_de_la_lista(destinos):
    v, vertical, horizontal = destinos()

    _pulsar(v, "Arrow Down")

    assert vertical.llamadas == [{"delta": PASO_VERTICAL, "duration": 200}]
    assert horizontal.llamadas == []


def test_la_flecha_derecha_desplaza_el_eje_horizontal_de_la_lista(destinos):
    v, vertical, horizontal = destinos()

    _pulsar(v, "Arrow Right")

    assert horizontal.llamadas == [{"delta": PASO_HORIZONTAL, "duration": 200}]
    assert vertical.llamadas == []


def test_la_flecha_arriba_y_la_izquierda_van_en_sentido_contrario(destinos):
    v, vertical, horizontal = destinos()

    _pulsar(v, "Arrow Up")
    _pulsar(v, "Arrow Left")

    assert vertical.llamadas[0]["delta"] == -PASO_VERTICAL
    assert horizontal.llamadas[0]["delta"] == -PASO_HORIZONTAL


def test_control_flecha_va_al_extremo_del_eje(destinos):
    """Al principio con `offset=0` (exacto) y al final con un delta enorme que
    Flutter acota al límite real del scroll."""
    v, vertical, horizontal = destinos()

    _pulsar(v, "Arrow Up", ctrl=True)
    assert vertical.llamadas[0] == {"offset": 0.0, "duration": 200}

    _pulsar(v, "Arrow Down", ctrl=True)
    assert vertical.llamadas[1]["delta"] > 10000

    _pulsar(v, "Arrow Left", ctrl=True)
    assert horizontal.llamadas[0] == {"offset": 0.0, "duration": 200}

    _pulsar(v, "Arrow Right", ctrl=True)
    assert horizontal.llamadas[1]["delta"] > 10000


def test_el_destino_se_resuelve_en_el_momento_de_la_pulsacion(destinos):
    """La lista se reconstruye en cada repintado: un control guardado al
    instalar el teclado ya no está en pantalla."""
    v, vertical, _ = destinos()
    _pulsar(v, "Arrow Down")
    assert len(vertical.llamadas) == 1

    nuevo = DestinoFalso()
    v._deu_scroll_vertical = nuevo  # repintado: control nuevo
    _pulsar(v, "Arrow Down")

    assert len(vertical.llamadas) == 1, "siguió desplazando el control viejo"
    assert len(nuevo.llamadas) == 1


def test_las_flechas_siguen_la_pestana_activa(vista, evento):
    """Cada pestaña tiene su propio par de scrolls; desplazar el de la pestaña
    que el usuario no está mirando sería peor que no hacer nada."""
    v = vista()
    v._asegurar_teclado(evento)
    deudas, clientes = DestinoFalso(), DestinoFalso()
    v._deu_scroll_vertical = deudas
    v._cli_scroll_vertical = clientes

    v.current_tab = "clientes"
    _pulsar(v, "Arrow Down")
    assert len(clientes.llamadas) == 1 and deudas.llamadas == []

    v.current_tab = "deudas"
    _pulsar(v, "Arrow Down")
    assert len(deudas.llamadas) == 1


def test_una_pestana_desconocida_no_desplaza_nada(vista, evento):
    v = vista()
    v._asegurar_teclado(evento)
    v.current_tab = "inventada"

    assert v._destinos_scroll_pestana() == (None, None)
    _pulsar(v, "Arrow Down")  # no debe propagar ninguna excepción


# ─── La regla del foco ───────────────────────────────────────────────────────

def test_con_un_campo_enfocado_las_flechas_no_desplazan(destinos):
    """Si el cursor está en el buscador, las flechas mueven el cursor: nadie
    espera que al corregir una palabra se le mueva la pantalla."""
    v, vertical, _ = destinos()
    v.deu_search.on_focus(None)

    _pulsar(v, "Arrow Down")

    assert vertical.llamadas == []


def test_al_soltar_el_campo_las_flechas_vuelven_a_desplazar(destinos):
    v, vertical, _ = destinos()
    v.deu_search.on_focus(None)
    v.deu_search.on_blur(None)

    _pulsar(v, "Arrow Down")

    assert len(vertical.llamadas) == 1


def test_escape_suelta_el_foco_y_devuelve_la_navegacion(destinos):
    """Sin esto el usuario tendría que buscar un hueco de la pantalla donde
    hacer clic para volver a navegar."""
    v, vertical, _ = destinos()
    v.deu_search.on_focus(None)

    _pulsar(v, "Escape")
    assert v._registro_foco.hay_campo_con_foco is False

    _pulsar(v, "Arrow Down")
    assert len(vertical.llamadas) == 1


def test_todos_los_campos_de_texto_de_la_vista_estan_enlazados(vista):
    """Un campo sin enlazar es un campo donde al usuario se le mueve la
    pantalla mientras escribe; se recorre la vista entera para que ninguno
    quede fuera por olvido."""
    v = vista()
    cuerpo = v.controls[-1]

    def _aplanar(control, vistos=None):
        if control is None or isinstance(control, (str, int, float, bool)):
            return []
        vistos = set() if vistos is None else vistos
        if id(control) in vistos:
            return []
        vistos.add(id(control))
        encontrados = [control]
        for atributo in ("controls", "content", "actions", "title", "label", "segments", "rows", "cells"):
            hijo = getattr(control, atributo, None)
            if isinstance(hijo, (list, tuple)):
                for h in hijo:
                    encontrados += _aplanar(h, vistos)
            elif hijo is not None and not isinstance(hijo, (str, int, float, bool)):
                encontrados += _aplanar(hijo, vistos)
        return encontrados

    campos = [c for c in _aplanar(cuerpo) if isinstance(c, ft.TextField)]
    assert len(campos) >= 13, f"se esperaban los campos de las tres pestañas, hay {len(campos)}"
    sin_enlazar = [c.label for c in campos if c.on_focus is None or c.on_blur is None]
    assert sin_enlazar == [], f"campos sin registrar su foco: {sin_enlazar}"


def test_los_campos_de_los_dialogos_de_deudas_estan_enlazados(vista, deuda, evento):
    """Los campos de los diálogos de abono y de edición también: con el cursor
    dentro de uno, las flechas son del cursor."""
    v = vista()

    v.handle_abrir_cobro(deuda, evento)
    campos = [c for c in _campos_del_dialogo(v._dialog) if isinstance(c, ft.TextField)]
    assert len(campos) == 2, f"monto y referencia: {[c.label for c in campos]}"
    assert all(c.on_focus is not None and c.on_blur is not None for c in campos)
    v._cerrar_dialogo(evento, dialog=v._dialog)

    v.handle_abrir_edicion_deuda(deuda, evento)
    campos = [c for c in _campos_del_dialogo(v._dialog) if isinstance(c, ft.TextField)]
    assert len(campos) == 2, f"fecha límite y monto total: {[c.label for c in campos]}"
    assert all(c.on_focus is not None and c.on_blur is not None for c in campos)


def test_cerrar_un_dialogo_suelta_el_foco_de_sus_campos(vista, deuda, destinos, evento):
    """Un campo que desaparece con su diálogo nunca recibe `on_blur`: sin
    soltarlo al cerrar, su foco quedaría registrado para siempre y las flechas
    no volverían a navegar nunca."""
    v, vertical, _ = destinos()

    v.handle_abrir_cobro(deuda, evento)
    campo = next(c for c in _campos_del_dialogo(v._dialog) if isinstance(c, ft.TextField))
    campo.on_focus(None)
    assert v._registro_foco.hay_campo_con_foco is True

    v._cerrar_dialogo(evento, dialog=v._dialog)

    assert v._registro_foco.hay_campo_con_foco is False
    _pulsar(v, "Arrow Down")
    assert len(vertical.llamadas) == 1


def _campos_del_dialogo(dialogo) -> list:
    encontrados = []
    pendientes = [dialogo.content]
    vistos = set()
    while pendientes:
        actual = pendientes.pop()
        if actual is None or id(actual) in vistos:
            continue
        vistos.add(id(actual))
        encontrados.append(actual)
        for atributo in ("controls", "content"):
            hijo = getattr(actual, atributo, None)
            if isinstance(hijo, (list, tuple)):
                pendientes += list(hijo)
            elif hijo is not None and not isinstance(hijo, (str, int, float, bool)):
                pendientes.append(hijo)
    return encontrados


# ─── F2 / F5 / F6 sobre la deuda marcada ─────────────────────────────────────

def _marcar(v, evento):
    v.dt_deudas.rows[0].on_select_change(evento)


def test_f2_abre_el_dialogo_de_cobro_de_la_deuda_marcada(en_deudas, deuda, evento):
    v = en_deudas()
    _marcar(v, evento)

    _pulsar(v, "F2")

    assert v._dialog is not None, "F2 debe abrir el cobro"
    textos = [c.value for c in _campos_del_dialogo(v._dialog) if isinstance(c, ft.Text) and c.value]
    assert any("Saldo pendiente" in t for t in textos)


def test_f5_abre_el_dialogo_de_edicion_de_la_deuda_marcada(en_deudas, deuda, evento):
    v = en_deudas()
    _marcar(v, evento)

    _pulsar(v, "F5")

    etiquetas = [
        c.label for c in _campos_del_dialogo(v._dialog) if isinstance(c, ft.TextField)
    ]
    assert any("Fecha Límite" in (e or "") for e in etiquetas)
    assert any("Monto Total" in (e or "") for e in etiquetas)


def test_f6_abre_la_confirmacion_de_borrado_de_la_deuda_marcada(en_deudas, deuda, evento):
    v = en_deudas()
    _marcar(v, evento)

    _pulsar(v, "F6")

    textos = [c.value for c in _campos_del_dialogo(v._dialog) if isinstance(c, ft.Text) and c.value]
    assert any("cascada" in t for t in textos), "F6 debe llegar a la confirmación, no borrar"
    assert obtener_deuda(deuda["id"]) is not None


def test_f1_f3_y_f4_quedan_inertes_en_esta_lista(en_deudas, deuda, evento):
    """El mapeo es fijo y común a todas las listas: las teclas sin un botón
    equivalente aquí no hacen nada, y no se les inventa uno."""
    v = en_deudas()
    _marcar(v, evento)

    for tecla in ("F1", "F3", "F4"):
        _pulsar(v, tecla)

    assert v._dialog_stack == [], "ninguna de las tres debe abrir nada"


def test_sin_deuda_marcada_ninguna_tecla_de_funcion_hace_nada(en_deudas, deuda, evento):
    """Adivinar un renglón sería disparar una acción —incluido un borrado—
    sobre algo que el usuario no eligió."""
    v = en_deudas()
    assert v._seleccion_deudas.hay_seleccion is False

    for tecla in ("F1", "F2", "F3", "F4", "F5", "F6"):
        _pulsar(v, tecla)

    assert v._dialog_stack == []
    assert obtener_deuda(deuda["id"]) is not None


def test_f2_no_cobra_una_deuda_marcada_que_ya_esta_pagada(en_deudas, cliente, evento):
    pagada = crear_deuda("V-12345678", 50.0, FUTURO)
    registrar_abono(pagada["id"], 50.0)
    v = en_deudas()
    v.deu_solo_abiertas.value = False
    v.refrescar_deudas(evento)
    _marcar(v, evento)

    _pulsar(v, "F2")

    assert v._dialog_stack == []


def test_escape_limpia_la_marca_de_la_lista(en_deudas, deuda, evento):
    v = en_deudas()
    _marcar(v, evento)
    assert v._seleccion_deudas.hay_seleccion is True

    _pulsar(v, "Escape")

    assert v._seleccion_deudas.hay_seleccion is False


def test_la_tecla_acciona_por_el_mismo_camino_que_el_boton(en_deudas, deuda, evento, monkeypatch):
    """Si la tecla y el ratón no comparten el punto de entrada, un día uno
    valida algo que el otro no."""
    v = en_deudas()
    _marcar(v, evento)
    llamadas = []
    monkeypatch.setattr(
        v, "ejecutar_accion_deuda",
        lambda accion, deuda_id, e=None: llamadas.append((accion, str(deuda_id))) or True,
    )

    _pulsar(v, "F5")

    assert llamadas == [("editar", str(deuda["id"]))]
