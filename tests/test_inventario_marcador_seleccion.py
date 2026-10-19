"""Marcador y sombreado del ítem en la lista de inventario (Nueva Función 3).

Mecánica que se blinda aquí, tal como la pidió el usuario:
  - Un clic en cualquier parte de la fila marca el ítem: se sombrea y la
    casilla izquierda queda marcada, en los dos formatos de vista ("Separado"
    y "Agrupado").
  - Solo hay DOS formas de deseleccionar: el clic dentro de la casilla marcada
    y la tecla [Esc].
  - Con un ítem marcado, los botones de las demás filas quedan DESHABILITADOS
    (visiblemente, no ignorados en silencio).
  - Sin marcar nada, todos los botones de todas las filas siguen activos: es la
    regla "Importante" del PDF (el sistema trabaja como la versión anterior) y
    es la más fácil de romper al cablear la tabla.

Se usa el mismo patrón de página falsa que `test_inventario_dialogos_pila.py`
para que el enganche del teclado se ejercite contra una API parecida a la real.
El teclado ya no lo atiende un handler propio de la vista sino `ControlTeclado`
(`ui.components.teclado_nav`), cuyo `manejar` es una corutina: por eso las
pulsaciones se ejercitan con `asyncio.run`. Los atajos completos (flechas,
F1..F6, regla del foco) tienen su propio archivo,
`test_inventario_atajos_teclado.py`; aquí solo se conserva lo que el marcador
necesita de ellos.
"""
import asyncio

import flet as ft
import pytest

CODIGOS = ("SEL-001", "SEL-002", "SEL-003")


class PageFalsa:
    """Página headless con soporte de teclado y pila de diálogos."""

    def __init__(self):
        self.dialogos = []
        self.overlay = []
        self.updates = 0
        self.on_keyboard_event = None

    def show_dialog(self, dialog):
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
    def __init__(self, page, key):
        self.page = page
        self.key = key


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
            descripcion_general=f"Producto de prueba {i}",
            departamento="Pruebas",
            marca="ACME",
            precio_dolares=10.0 * i,
            existencia=3,
            costo_usd_efectivo=5.0 * i,
            rol_usuario="administrador",
        )
    return list(CODIGOS)


@pytest.fixture
def vista(productos):
    from ui.views.inventario_view import InventarioView

    v = InventarioView(es_admin=True, username="marcador", rol_usuario="administrador")
    v.get_body()
    return v


# ── Helpers de lectura de la tabla ──────────────────────────────────────────
def _fila(vista, codigo) -> ft.DataRow:
    return next(r for r in vista._dt.rows if r.data == codigo)


def _casilla(fila: ft.DataRow) -> ft.DataCell:
    return fila.cells[0]


def _icono_casilla(fila: ft.DataRow) -> ft.Icon:
    return _casilla(fila).content.content


def _icono_de(control) -> ft.IconButton:
    """Cada botón viaja dentro de un `Stack` junto a la etiqueta de su atajo
    ("F1".."F6" superpuesta en la esquina del ícono)."""
    if isinstance(control, ft.Stack):
        return next(c for c in control.controls if isinstance(c, ft.IconButton))
    return control


def _botones(fila: ft.DataRow) -> list[ft.IconButton]:
    contenido = fila.cells[-1].content
    if isinstance(contenido, ft.Container):  # el modo agrupado envuelve la celda
        contenido = contenido.content
    return [
        _icono_de(c) for c in contenido.controls
        if isinstance(c, (ft.IconButton, ft.Stack))
    ]


def _clic_en_fila(vista, codigo, evento):
    _fila(vista, codigo).on_select_change(evento)


def _clic_en_casilla(vista, codigo, evento):
    _casilla(_fila(vista, codigo)).on_tap(evento)


MODOS = ["separado", "agrupado"]


@pytest.fixture(params=MODOS)
def vista_modo(request, vista):
    """La misma vista en cada uno de los dos formatos con marcador."""
    vista._modo_vista = request.param
    vista._cargar_filas()
    return vista


# ─────────────────────────────────────────────────────────────────────────────
# La casilla existe en los dos formatos
# ─────────────────────────────────────────────────────────────────────────────
def test_la_casilla_marcadora_abre_la_lista_en_los_dos_formatos(vista_modo):
    for codigo in CODIGOS:
        fila = _fila(vista_modo, codigo)
        assert _casilla(fila).on_tap is not None, "la casilla debe atender su propio clic"
        assert isinstance(_icono_casilla(fila), ft.Icon)


def test_la_fila_completa_es_sensible_al_clic(vista_modo):
    """"No importa si es fuera de la casilla": toda la fila marca."""
    for codigo in CODIGOS:
        assert _fila(vista_modo, codigo).on_select_change is not None


def test_la_tabla_no_dibuja_su_propia_columna_de_casillas(vista):
    """Con `on_select_change` en todas las filas, activar la columna de
    casillas de la tabla pondría una segunda casilla junto al marcador."""
    assert vista._dt.show_checkbox_column is False


def test_la_columna_marcador_no_se_puede_ocultar(vista):
    assert "marcador" not in vista._columnas_ocultables
    assert vista._columnas_orden_visible()[0] == "marcador"


# ─────────────────────────────────────────────────────────────────────────────
# Marcar y sombrear
# ─────────────────────────────────────────────────────────────────────────────
def test_un_clic_marca_y_sombrea_el_item(vista_modo, evento):
    _clic_en_fila(vista_modo, "SEL-002", evento)

    fila = _fila(vista_modo, "SEL-002")
    assert vista_modo._seleccion.seleccionado == "SEL-002"
    assert fila.selected is True
    assert fila.color is not None, "el ítem marcado debe quedar sombreado"


def test_las_demas_filas_no_quedan_sombreadas(vista_modo, evento):
    _clic_en_fila(vista_modo, "SEL-002", evento)

    for codigo in ("SEL-001", "SEL-003"):
        fila = _fila(vista_modo, codigo)
        assert fila.selected is False
        assert fila.color is None


def test_el_marcado_se_mantiene_al_repintar_la_tabla(vista_modo, evento):
    """El marcado es estado del modelo, así que sobrevive a los repintados (y
    por lo tanto a desplazarse hacia la derecha de la lista)."""
    _clic_en_fila(vista_modo, "SEL-001", evento)

    vista_modo._cargar_filas()

    assert _fila(vista_modo, "SEL-001").selected is True


def test_marcar_otro_item_mueve_el_marcador(vista_modo, evento):
    _clic_en_fila(vista_modo, "SEL-001", evento)
    _clic_en_fila(vista_modo, "SEL-003", evento)

    assert _fila(vista_modo, "SEL-001").selected is False
    assert _fila(vista_modo, "SEL-003").selected is True


def test_el_icono_de_la_casilla_cambia_al_marcar(vista_modo, evento):
    antes = _icono_casilla(_fila(vista_modo, "SEL-001")).icon

    _clic_en_fila(vista_modo, "SEL-001", evento)

    assert _icono_casilla(_fila(vista_modo, "SEL-001")).icon != antes


# ─────────────────────────────────────────────────────────────────────────────
# Las dos únicas formas de deseleccionar
# ─────────────────────────────────────────────────────────────────────────────
def test_el_clic_dentro_de_la_casilla_marcada_deselecciona(vista_modo, evento):
    _clic_en_fila(vista_modo, "SEL-002", evento)

    _clic_en_casilla(vista_modo, "SEL-002", evento)

    assert vista_modo._seleccion.hay_seleccion is False
    assert _fila(vista_modo, "SEL-002").selected is False


def _pulsar(vista, pagina, tecla):
    """`ControlTeclado.manejar` es `async def` (dentro espera a `scroll_to`)."""
    return asyncio.run(vista._teclado.manejar(TeclaFalsa(pagina, tecla)))


def test_la_tecla_escape_deselecciona(vista_modo, pagina, evento):
    _clic_en_fila(vista_modo, "SEL-002", evento)

    _pulsar(vista_modo, pagina, "Escape")

    assert vista_modo._seleccion.hay_seleccion is False


def test_otra_tecla_no_deselecciona(vista_modo, pagina, evento):
    _clic_en_fila(vista_modo, "SEL-002", evento)

    _pulsar(vista_modo, pagina, "Enter")

    assert vista_modo._seleccion.seleccionado == "SEL-002"


def test_un_clic_en_la_fila_nunca_deselecciona(vista_modo, evento):
    """Solo la casilla y [Esc] quitan la marca: repetir el clic en la fila no."""
    _clic_en_fila(vista_modo, "SEL-002", evento)
    _clic_en_fila(vista_modo, "SEL-002", evento)

    assert vista_modo._seleccion.seleccionado == "SEL-002"


def test_al_marcar_se_engancha_el_teclado_sin_pisar_el_handler_previo(vista, pagina, evento):
    """La vista comparte la página con el Dashboard: el handler que hubiera
    puesto debe seguir recibiendo las teclas."""
    recibidas = []
    pagina.on_keyboard_event = lambda ev: recibidas.append(getattr(ev, "key", None))

    _clic_en_fila(vista, "SEL-001", evento)

    assert pagina.on_keyboard_event is vista._teclado.handler
    asyncio.run(pagina.on_keyboard_event(TeclaFalsa(pagina, "Escape")))
    assert recibidas == ["Escape"], "el handler previo debe seguir invocándose"
    assert vista._seleccion.hay_seleccion is False


# ─────────────────────────────────────────────────────────────────────────────
# La regla "Importante": sin selección, todo funciona como antes
# ─────────────────────────────────────────────────────────────────────────────
def test_sin_marcar_nada_todos_los_botones_estan_activos(vista_modo):
    for codigo in CODIGOS:
        botones = _botones(_fila(vista_modo, codigo))
        assert len(botones) == 6, "info, cobrar, carrito, historial, editar y borrar"
        assert all(b.disabled is False for b in botones), (
            "sin selección el sistema trabaja igual que la versión anterior"
        )


def test_con_un_item_marcado_solo_el_marcado_conserva_sus_botones(vista_modo, evento):
    _clic_en_fila(vista_modo, "SEL-002", evento)

    assert all(b.disabled is False for b in _botones(_fila(vista_modo, "SEL-002")))
    for codigo in ("SEL-001", "SEL-003"):
        botones = _botones(_fila(vista_modo, codigo))
        assert all(b.disabled is True for b in botones), (
            f"los botones de {codigo} deben quedar deshabilitados, no inertes en silencio"
        )


def test_al_deseleccionar_vuelven_a_habilitarse_todos(vista_modo, evento):
    _clic_en_fila(vista_modo, "SEL-002", evento)
    _clic_en_casilla(vista_modo, "SEL-002", evento)

    for codigo in CODIGOS:
        assert all(b.disabled is False for b in _botones(_fila(vista_modo, codigo)))


def test_una_accion_sobre_un_item_no_marcado_se_rechaza_con_aviso(vista, evento):
    """Defensa en profundidad: la regla vale también para quien invoque la
    acción por código o por teclado, no solo para quien hace clic."""
    vista._seleccion.seleccionar("SEL-002")

    assert vista.ejecutar_accion_item("editar", "SEL-001", evento) is False
    assert vista._dialog is None, "no debe abrirse el formulario del ítem ajeno"


def test_la_accion_sobre_el_item_marcado_se_ejecuta(vista, evento):
    vista._seleccion.seleccionar("SEL-002")

    assert vista.ejecutar_accion_item("editar", "SEL-002", evento) is True
    assert vista._editing_codigo == "SEL-002"


def test_sin_seleccion_cualquier_accion_se_ejecuta(vista, evento):
    assert vista.ejecutar_accion_item("editar", "SEL-003", evento) is True
    assert vista._editing_codigo == "SEL-003"


# ─────────────────────────────────────────────────────────────────────────────
# Superficie para la segunda ola (atajos F1..F6)
# ─────────────────────────────────────────────────────────────────────────────
def test_las_seis_acciones_estan_expuestas_con_nombre(vista):
    assert vista.ACCIONES_ITEM == ("info", "cobrar", "carrito", "historial", "editar", "borrar")
    for accion in vista.ACCIONES_ITEM:
        assert callable(vista._handlers_accion()[accion])


def test_se_puede_accionar_el_item_marcado_sin_pasar_el_codigo(vista, evento):
    vista._seleccion.seleccionar("SEL-001")

    assert vista.ejecutar_accion_sobre_seleccionado("editar", evento) is True
    assert vista._editing_codigo == "SEL-001"


def test_sin_item_marcado_no_hay_accion_sobre_el_seleccionado(vista, evento):
    assert vista.ejecutar_accion_sobre_seleccionado("editar", evento) is False


def test_una_accion_desconocida_falla_ruidosamente(vista):
    with pytest.raises(ValueError):
        vista.ejecutar_accion_item("teletransportar", "SEL-001", None)


def test_los_botones_de_la_fila_entran_por_el_punto_de_entrada_unico(vista_modo, evento):
    """Cada botón dispara `ejecutar_accion_item`, que es lo que la segunda ola
    va a enlazar a las teclas."""
    botones = _botones(_fila(vista_modo, "SEL-001"))
    ejecutadas = []
    vista_modo.ejecutar_accion_item = lambda a, c, ev=None: ejecutadas.append((a, c))

    for b in botones:
        b.on_click(evento)

    assert ejecutadas == [(a, "SEL-001") for a in vista_modo.ACCIONES_ITEM]
