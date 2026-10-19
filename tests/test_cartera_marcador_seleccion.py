"""Marcador y sombreado de la lista de Deudas por Cobrar.

Nueva Función 3 del PDF del 17/10/2026, que el usuario del proyecto pidió
extender también a esta lista: al dar un clic a un renglón se sombrea, se marca
la casilla de la izquierda y sigue marcado al moverse a la derecha de la lista.
Solo el renglón sombreado tiene permitido accionar sus botones.

Lo que estas pruebas blindan, en orden de "qué se rompe más fácil":

1. La regla **Importante**: SIN NADA MARCADO todo sigue funcionando como en la
   versión anterior, con los tres botones de todos los renglones activos. Es la
   regla más fácil de romper al cablear la vista, porque la forma ingenua de
   implementar el marcador —"habilitar solo el marcado"— la invierte.
2. Que el sombreado se deriva del MODELO y no de una bandera del control que
   recibió el clic: así sobrevive al repintado y al desplazamiento horizontal.
3. Las dos únicas formas de deseleccionar: el clic DENTRO de la casilla marcada
   y la tecla [Esc]. Un clic en otro renglón mueve el marcador, nunca lo quita.
4. Que un botón bloqueado se vea bloqueado y diga por qué: un botón que acepta
   el clic y no hace nada se lee como un cuelgue de la aplicación.

La vista se ejerce headless con el mismo doble de página de
`test_cartera_deudas_view.py`.
"""
import flet as ft
import pytest

from services.cartera_service import crear_cliente
from services.deudas_service import crear_deuda, obtener_deuda, registrar_abono

FUTURO = "31/12/2027"

ITEMS = [
    {"producto_codigo": "P-001", "descripcion_corta": "Filtro de aceite", "cantidad": 2, "subtotal_usd": 20.0},
]

# Índice de la columna estructural del marcador: la primera de la lista.
COL_MARCADOR = 0


# ─── Utilidades de recorrido del árbol de controles ──────────────────────────

def _aplanar(control, vistos=None) -> list:
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


class PageFalsa:
    """Pila de diálogos de Flet 0.86, más el teclado que la vista engancha."""

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


@pytest.fixture
def pagina():
    return PageFalsa()


@pytest.fixture
def evento(pagina):
    return EventoFalso(pagina)


@pytest.fixture
def cliente(db_temporal):
    return crear_cliente(
        nombre="Fulano de Tal",
        cedula_rif="V-12345678",
        telefono="0414-1234567",
    )


@pytest.fixture
def dos_deudas(cliente):
    """Dos deudas abiertas del mismo cliente, en el orden en que la lista las
    pinta (fecha límite ascendente)."""
    primera = crear_deuda("V-12345678", 100.0, "01/11/2027", items=ITEMS)
    segunda = crear_deuda("V-12345678", 60.0, "01/12/2027", items=ITEMS)
    return primera, segunda


@pytest.fixture
def vista(db_temporal):
    def _construir():
        from ui.views.cartera_view import CarteraView

        return CarteraView(user_data={"username": "cajera2", "role": "vendedor"})
    return _construir


# ─── Ayudas sobre la lista ───────────────────────────────────────────────────

def _fila(v, indice: int):
    return v.dt_deudas.rows[indice]


def _icono_marcador(fila):
    iconos = [c for c in _aplanar(fila.cells[COL_MARCADOR].content) if isinstance(c, ft.Icon)]
    assert iconos, "la celda del marcador debe dibujar un icono de casilla"
    return iconos[0]


def _marcada(fila) -> bool:
    return _icono_marcador(fila).icon == ft.Icons.RADIO_BUTTON_CHECKED


def _botones(fila) -> list:
    return [
        c for c in _aplanar(fila.cells[-1].content)
        if isinstance(c, ft.IconButton)
    ]


def _boton(fila, fragmento_tooltip: str):
    for control in _botones(fila):
        tooltip = control.tooltip or ""
        if fragmento_tooltip.lower() in tooltip.lower():
            return control
    raise AssertionError(
        f"No se encontró el botón '{fragmento_tooltip}'; "
        f"hay {[b.tooltip for b in _botones(fila)]}"
    )


def _clic_en_fila(v, indice: int, evento):
    """El clic en cualquier parte del renglón (`DataRow.on_select_change`)."""
    _fila(v, indice).on_select_change(evento)


def _clic_en_casilla(v, indice: int, evento):
    """El clic DENTRO de la casilla marcadora (`DataCell.on_tap`)."""
    _fila(v, indice).cells[COL_MARCADOR].on_tap(evento)


# ─── La columna del marcador existe y es la primera ──────────────────────────

def test_la_primera_columna_es_la_casilla_marcadora(vista):
    v = vista()
    etiquetas = [c.label.value for c in v.dt_deudas.columns]

    assert etiquetas[0] == v.ENCABEZADO_MARCADOR
    assert etiquetas[1] == "Fecha Límite", "el boceto del PDF arranca después del marcador"


def test_la_tabla_no_dibuja_la_casilla_propia_de_flet(vista):
    """Con `on_select_change` en los renglones y `show_checkbox_column` activo,
    Flet pinta una SEGUNDA casilla junto a nuestro marcador."""
    v = vista()
    assert v.dt_deudas.show_checkbox_column is False


# ─── Un clic marca y sombrea ─────────────────────────────────────────────────

def test_un_clic_en_el_renglon_lo_marca_y_lo_sombrea(vista, dos_deudas, evento):
    primera, _ = dos_deudas
    v = vista()

    _clic_en_fila(v, 0, evento)

    fila = _fila(v, 0)
    assert v._seleccion_deudas.seleccionado == str(primera["id"])
    assert fila.selected is True, "el renglón marcado va sombreado"
    assert fila.color is not None
    assert _marcada(fila) is True


def test_el_sombreado_se_deriva_del_modelo_y_sobrevive_al_repintado(vista, dos_deudas, evento):
    """Un repintado (buscar, filtrar, paginar, desplazarse) reconstruye los
    `DataRow`: si la marca viviera en el control que recibió el clic, se
    perdería ahí."""
    v = vista()
    _clic_en_fila(v, 0, evento)

    v.refrescar_deudas(evento)

    assert _fila(v, 0).selected is True
    assert _marcada(_fila(v, 0)) is True


def test_marcar_otro_renglon_mueve_el_marcador_sin_dejar_dos(vista, dos_deudas, evento):
    _, segunda = dos_deudas
    v = vista()

    _clic_en_fila(v, 0, evento)
    _clic_en_fila(v, 1, evento)

    assert v._seleccion_deudas.cantidad == 1
    assert v._seleccion_deudas.seleccionado == str(segunda["id"])
    assert _marcada(_fila(v, 0)) is False
    assert _marcada(_fila(v, 1)) is True


def test_un_segundo_clic_fuera_de_la_casilla_no_desmarca(vista, dos_deudas, evento):
    """El clic en el renglón solo PUEDE marcar: para desmarcar están la casilla
    y [Esc]."""
    v = vista()

    _clic_en_fila(v, 0, evento)
    _clic_en_fila(v, 0, evento)

    assert v._seleccion_deudas.hay_seleccion is True


# ─── Las dos formas de deseleccionar ─────────────────────────────────────────

def test_el_clic_en_la_casilla_marcada_deselecciona(vista, dos_deudas, evento):
    v = vista()
    _clic_en_fila(v, 0, evento)

    _clic_en_casilla(v, 0, evento)

    assert v._seleccion_deudas.hay_seleccion is False
    assert _fila(v, 0).selected is False
    assert _marcada(_fila(v, 0)) is False


def test_el_clic_en_una_casilla_sin_marcar_marca_ese_renglon(vista, dos_deudas, evento):
    _, segunda = dos_deudas
    v = vista()

    _clic_en_casilla(v, 1, evento)

    assert v._seleccion_deudas.seleccionado == str(segunda["id"])


def test_escape_limpia_la_seleccion(vista, dos_deudas, evento):
    v = vista()
    _clic_en_fila(v, 0, evento)

    v.limpiar_seleccion_deuda(evento)

    assert v._seleccion_deudas.hay_seleccion is False
    assert _fila(v, 0).selected is False


# ─── La regla "Importante" en los dos sentidos ───────────────────────────────

def test_sin_nada_marcado_todos_los_botones_siguen_habilitados(vista, dos_deudas, evento):
    """La regla más fácil de romper: mientras no haya nada marcado, el sistema
    trabaja igual que la versión anterior y se puede tocar cualquier botón de
    cualquier renglón."""
    v = vista()

    assert v._seleccion_deudas.hay_seleccion is False
    for indice in (0, 1):
        botones = _botones(_fila(v, indice))
        assert len(botones) == 3, f"el renglón {indice} debe traer sus tres botones"
        assert all(b.disabled is False for b in botones), (
            f"renglón {indice}: {[(b.tooltip, b.disabled) for b in botones]}"
        )


def test_con_una_deuda_marcada_los_botones_de_las_demas_quedan_deshabilitados(
    vista, dos_deudas, evento
):
    v = vista()

    _clic_en_fila(v, 0, evento)

    assert all(b.disabled is False for b in _botones(_fila(v, 0))), (
        "la deuda marcada conserva sus botones"
    )
    assert all(b.disabled is True for b in _botones(_fila(v, 1))), (
        "los de las demás quedan apagados"
    )


def test_el_boton_deshabilitado_explica_por_que_en_su_tooltip(vista, dos_deudas, evento):
    """Un botón apagado sin explicación se lee como un cuelgue: el tooltip
    tiene que decir qué hacer para recuperarlo."""
    v = vista()
    _clic_en_fila(v, 0, evento)

    for boton in _botones(_fila(v, 1)):
        assert "otra deuda marcada" in (boton.tooltip or "")
        assert "Esc" in (boton.tooltip or "")


def test_deseleccionar_devuelve_los_botones_de_todos_los_renglones(vista, dos_deudas, evento):
    v = vista()
    _clic_en_fila(v, 0, evento)
    assert all(b.disabled for b in _botones(_fila(v, 1)))

    _clic_en_casilla(v, 0, evento)

    for indice in (0, 1):
        assert all(b.disabled is False for b in _botones(_fila(v, indice)))


def test_una_deuda_pagada_sigue_sin_poder_cobrarse_aunque_este_marcada(vista, cliente, evento):
    """La regla del marcador no habilita lo que el servicio rechaza: el cobro
    de una deuda ya pagada se queda apagado con su propio motivo."""
    deuda = crear_deuda("V-12345678", 50.0, FUTURO)
    registrar_abono(deuda["id"], 50.0)
    v = vista()
    v.deu_solo_abiertas.value = False
    v.refrescar_deudas(evento)

    _clic_en_fila(v, 0, evento)

    boton = _boton(_fila(v, 0), "pagada")
    assert boton.disabled is True
    assert "otra deuda marcada" not in (boton.tooltip or ""), (
        "el motivo debe ser el verdadero: la deuda ya está pagada"
    )


# ─── El punto de entrada único revalida la regla ─────────────────────────────

def test_el_punto_de_entrada_rechaza_una_accion_sobre_un_renglon_no_marcado(
    vista, dos_deudas, evento
):
    """La regla vale también para quien entre por teclado o por código, no solo
    para quien hace clic en un botón que ya venía deshabilitado."""
    primera, segunda = dos_deudas
    v = vista()
    _clic_en_fila(v, 0, evento)

    assert v.ejecutar_accion_deuda("editar", segunda["id"], evento) is False
    assert v._dialog_stack == [], "no debe abrirse ningún diálogo"


def test_el_punto_de_entrada_acepta_la_accion_sobre_el_renglon_marcado(
    vista, dos_deudas, evento
):
    primera, _ = dos_deudas
    v = vista()
    _clic_en_fila(v, 0, evento)

    assert v.ejecutar_accion_deuda("editar", primera["id"], evento) is True
    assert v._dialog is not None


def test_el_punto_de_entrada_no_cobra_una_deuda_ya_pagada(vista, cliente, evento):
    deuda = crear_deuda("V-12345678", 50.0, FUTURO)
    registrar_abono(deuda["id"], 50.0)
    v = vista()

    assert v.ejecutar_accion_deuda("cobrar", deuda["id"], evento) is False
    assert v._dialog_stack == []


def test_el_punto_de_entrada_sobrevive_a_una_deuda_borrada_por_otra_ventana(
    vista, dos_deudas, evento
):
    """Dos ventanas abiertas sobre la misma base: la marca queda apuntando a un
    id que ya no existe. Sin descartarla, esa selección fantasma dejaría
    inertes los botones de todos los renglones vivos."""
    from services.deudas_service import eliminar_deuda

    primera, _ = dos_deudas
    v = vista()
    _clic_en_fila(v, 0, evento)

    eliminar_deuda(primera["id"])

    assert v.ejecutar_accion_deuda("borrar", primera["id"], evento) is False
    assert v._seleccion_deudas.hay_seleccion is False, "la marca fantasma debe descartarse"
    assert v._dialog_stack == []
    assert all(b.disabled is False for b in _botones(_fila(v, 0))), (
        "el renglón vivo debe recuperar sus botones"
    )


def test_una_accion_que_esta_lista_no_tiene_no_hace_nada(vista, dos_deudas, evento):
    """"info", "carrito" e "historial" son del mapeo canónico pero no existen
    en Deudas por Cobrar: quedan inertes, sin equivalencias inventadas."""
    primera, _ = dos_deudas
    v = vista()
    _clic_en_fila(v, 0, evento)

    for accion in ("info", "carrito", "historial"):
        assert v.ejecutar_accion_deuda(accion, primera["id"], evento) is False
    assert v._dialog_stack == []


def test_los_tres_botones_pasan_por_el_punto_de_entrada(vista, dos_deudas, evento, monkeypatch):
    """Si el ratón y la tecla no recorren el mismo camino, un día divergen."""
    v = vista()
    llamadas = []
    monkeypatch.setattr(
        v, "ejecutar_accion_deuda",
        lambda accion, deuda_id, e=None: llamadas.append((accion, str(deuda_id))) or True,
    )
    v.refrescar_deudas(evento)

    primera, _ = dos_deudas
    for fragmento in ("Cobrar", "Editar", "Borrar"):
        _boton(_fila(v, 0), fragmento).on_click(evento)

    assert llamadas == [
        ("cobrar", str(primera["id"])),
        ("editar", str(primera["id"])),
        ("borrar", str(primera["id"])),
    ]


# ─── Etiquetas de los atajos a la vista ──────────────────────────────────────

def test_los_botones_muestran_su_atajo_en_pantalla(vista, dos_deudas):
    """El PDF pide los atajos visibles "para siempre ser consciente de ellos":
    un tooltip hay que ir a buscarlo con el ratón."""
    v = vista()
    etiquetas = [
        c.value for c in _aplanar(_fila(v, 0).cells[-1].content)
        if isinstance(c, ft.Text) and c.value
    ]

    assert etiquetas == ["F2", "F5", "F6"], (
        "Cobrar=F2, Editar=F5 y Borrar=F6, en el orden de los botones"
    )


def test_el_tooltip_tambien_nombra_el_atajo(vista, dos_deudas):
    v = vista()
    fila = _fila(v, 0)

    assert "(F2)" in _boton(fila, "Cobrar").tooltip
    assert "(F5)" in _boton(fila, "Editar").tooltip
    assert "(F6)" in _boton(fila, "Borrar").tooltip
