"""Marcador y sombreado del renglón del carrito (`ui/views/ventas_view.py`).

La Nueva Función 3 nació para el Inventario y el usuario del proyecto pidió
extenderla al carrito de Ventas con la MISMA mecánica, para que una lista no
se comporte de dos formas distintas según el módulo:

  - Un clic en cualquier parte del renglón lo marca: se sombrea y la casilla
    de la izquierda queda marcada, y sigue marcado al desplazarse a la derecha
    de la tabla (el sombreado se deriva del modelo, no de una bandera local).
  - Solo hay DOS formas de desmarcar: el clic DENTRO de la casilla marcada y
    la tecla [Esc].
  - Con un renglón marcado, los botones de los DEMÁS renglones quedan
    deshabilitados visiblemente, los +/- de la cantidad incluidos.
  - SIN NADA MARCADO TODO SIGUE COMO ANTES: todos los botones de todos los
    renglones están activos. Es la regla "Importante" del PDF y es la que se
    rompe sola si alguien invierte una condición, así que se prueba en los dos
    sentidos.

Se usa el patrón de página headless de `test_ventas_dialogo_cobro.py`.
"""
import flet as ft
import pytest

from services.bcv_service import actualizar_tasa
from services.cart_manager import limpiar_sesion, obtener_carrito_activo
from services.inventario_service import crear_producto
from ui.views.ventas_view import VentasView

CODIGOS = ("CAR-001", "CAR-002", "CAR-003")


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


@pytest.fixture
def pagina():
    return PageFalsa()


@pytest.fixture
def evento(pagina):
    return EventoFalso(pagina)


@pytest.fixture
def vista(db_temporal):
    """`VentasView` headless con tres renglones ya en el carrito."""
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

    v = VentasView(user_data={"username": "vendedor", "role": "administrador"})
    v.get_body()
    limpiar_sesion(v._sid)  # El sid headless se comparte entre tests.
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


# ─── Utilidades de lectura de la tabla ───────────────────────────────────────

def _descendientes(control):
    if control is None:
        return
    yield control
    hijos = []
    for atributo in ("controls", "content"):
        valor = getattr(control, atributo, None)
        if isinstance(valor, list):
            hijos.extend(valor)
        elif valor is not None and not isinstance(valor, (str, int, float, bool)):
            hijos.append(valor)
    for hijo in hijos:
        yield from _descendientes(hijo)


def _tabla(vista) -> ft.DataTable:
    return next(
        c for c in _descendientes(vista.tabla_carrito_container)
        if isinstance(c, ft.DataTable)
    )


def _repintar(vista) -> ft.DataTable:
    """Reconstruye la tabla como lo hace `_refrescar_carrito_y_resumen`."""
    vista.tabla_carrito_container.content = vista.build_tabla_carrito(
        obtener_carrito_activo(vista._sid)["items"]
    )
    return _tabla(vista)


def _fila(vista, codigo) -> ft.DataRow:
    return next(r for r in _tabla(vista).rows if r.data == codigo)


def _icono_casilla(fila: ft.DataRow) -> ft.Icon:
    return fila.cells[0].content.content


def _botones_accion(fila: ft.DataRow) -> list[ft.IconButton]:
    contenido = fila.cells[-1].content
    if isinstance(contenido, ft.Container):  # el modo agrupado envuelve la celda
        contenido = contenido.content
    return [c for c in contenido.controls if isinstance(c, ft.IconButton)]


def _botones_cantidad(fila: ft.DataRow) -> list[ft.IconButton]:
    return [
        c for celda in fila.cells
        for c in _descendientes(celda.content)
        if isinstance(c, ft.IconButton)
        and c.icon in (ft.Icons.REMOVE_CIRCLE_OUTLINE, ft.Icons.ADD_CIRCLE_OUTLINE)
    ]


def _clic_en_fila(vista, codigo, evento):
    _fila(vista, codigo).on_select_change(evento)


def _clic_en_casilla(vista, codigo, evento):
    _fila(vista, codigo).cells[0].on_tap(evento)


# ─── 1. El clic marca y sombrea ──────────────────────────────────────────────

def test_sin_marcar_nada_ninguna_fila_esta_sombreada(vista):
    for codigo in CODIGOS:
        fila = _fila(vista, codigo)
        assert fila.selected is False
        assert _icono_casilla(fila).icon == ft.Icons.RADIO_BUTTON_UNCHECKED


def test_un_clic_en_el_renglon_lo_marca_y_lo_sombrea(vista, evento):
    _clic_en_fila(vista, "CAR-002", evento)
    _repintar(vista)

    fila = _fila(vista, "CAR-002")
    assert fila.selected is True
    assert fila.color is not None
    assert _icono_casilla(fila).icon == ft.Icons.RADIO_BUTTON_CHECKED
    assert vista._seleccion.seleccionado == "CAR-002"


def test_la_clave_del_marcador_es_el_codigo_del_producto(vista, evento):
    _clic_en_fila(vista, "CAR-003", evento)

    assert vista._seleccion.seleccionados == ("CAR-003",)


def test_un_clic_en_otro_renglon_mueve_el_marcador(vista, evento):
    _clic_en_fila(vista, "CAR-001", evento)
    _clic_en_fila(vista, "CAR-003", evento)
    _repintar(vista)

    assert vista._seleccion.seleccionados == ("CAR-003",)
    assert _fila(vista, "CAR-001").selected is False
    assert _fila(vista, "CAR-003").selected is True


def test_el_sombreado_no_se_pierde_al_repintar_la_tabla(vista, evento):
    """El sombreado se deriva del modelo: por eso sobrevive al repintado (y
    con él, al desplazamiento horizontal que reconstruye la tabla)."""
    _clic_en_fila(vista, "CAR-002", evento)

    for _ in range(3):
        _repintar(vista)

    assert _fila(vista, "CAR-002").selected is True


def test_el_cebreado_sigue_pintando_las_filas_no_marcadas(vista, evento):
    """El color del marcador reemplaza al cebreado, no lo borra: las filas
    impares no marcadas conservan su fondo alterno."""
    _clic_en_fila(vista, "CAR-001", evento)
    _repintar(vista)

    assert _fila(vista, "CAR-002").color is not None  # fila impar, cebreada
    assert _fila(vista, "CAR-003").color is None


# ─── 2. Las dos únicas formas de desmarcar ───────────────────────────────────

def test_el_clic_en_la_casilla_marcada_deselecciona(vista, evento):
    _clic_en_fila(vista, "CAR-002", evento)
    _repintar(vista)

    _clic_en_casilla(vista, "CAR-002", evento)
    _repintar(vista)

    assert vista._seleccion.hay_seleccion is False
    assert _fila(vista, "CAR-002").selected is False


def test_limpiar_seleccion_deselecciona(vista, evento):
    """`limpiar_seleccion` es lo que ejecuta [Esc] (ver
    `test_ventas_atajos_teclado.py` para la tecla real)."""
    _clic_en_fila(vista, "CAR-001", evento)

    vista.limpiar_seleccion(evento)
    _repintar(vista)

    assert vista._seleccion.hay_seleccion is False
    assert _fila(vista, "CAR-001").selected is False


def test_el_clic_fuera_de_la_casilla_nunca_desmarca(vista, evento):
    """Un segundo clic sobre el renglón ya marcado lo deja marcado: desmarcar
    es trabajo de la casilla y de [Esc], y solo de ellos."""
    _clic_en_fila(vista, "CAR-002", evento)
    _clic_en_fila(vista, "CAR-002", evento)
    _repintar(vista)

    assert vista._seleccion.seleccionados == ("CAR-002",)
    assert _fila(vista, "CAR-002").selected is True


# ─── 3. La regla "Importante", en los dos sentidos ───────────────────────────

def test_sin_marcar_nada_todos_los_botones_siguen_habilitados(vista):
    """La regla más fácil de romper: mientras no haya nada marcado, el sistema
    trabaja igual que la versión anterior."""
    for codigo in CODIGOS:
        fila = _fila(vista, codigo)
        assert [b.disabled for b in _botones_accion(fila)] == [False, False]
        assert all(b.disabled is False for b in _botones_cantidad(fila))


def test_con_un_renglon_marcado_los_botones_de_los_demas_quedan_deshabilitados(vista, evento):
    _clic_en_fila(vista, "CAR-002", evento)
    _repintar(vista)

    assert all(b.disabled is False for b in _botones_accion(_fila(vista, "CAR-002")))
    for codigo in ("CAR-001", "CAR-003"):
        botones = _botones_accion(_fila(vista, codigo))
        assert all(b.disabled is True for b in botones)


def test_los_botones_deshabilitados_explican_por_que_en_el_tooltip(vista, evento):
    """Un botón apagado sin explicación se lee como un cuelgue."""
    _clic_en_fila(vista, "CAR-002", evento)
    _repintar(vista)

    for boton in _botones_accion(_fila(vista, "CAR-001")):
        assert "marcado" in (boton.tooltip or "")


def test_los_mas_y_menos_de_la_cantidad_tambien_siguen_la_regla(vista, evento):
    _clic_en_fila(vista, "CAR-002", evento)
    _repintar(vista)

    assert all(b.disabled is False for b in _botones_cantidad(_fila(vista, "CAR-002")))
    assert all(b.disabled is True for b in _botones_cantidad(_fila(vista, "CAR-001")))


def test_al_desmarcar_vuelven_a_habilitarse_todos(vista, evento):
    _clic_en_fila(vista, "CAR-002", evento)
    _clic_en_casilla(vista, "CAR-002", evento)
    _repintar(vista)

    for codigo in CODIGOS:
        assert all(b.disabled is False for b in _botones_accion(_fila(vista, codigo)))


# ─── 4. El punto de entrada único revalida la regla ──────────────────────────

def test_ejecutar_accion_item_rechaza_un_renglon_no_marcado(vista, evento):
    _clic_en_fila(vista, "CAR-002", evento)

    assert vista.ejecutar_accion_item("editar", "CAR-001", evento) is False
    assert evento.page.visible is None  # no se abrió el diálogo de edición


def test_ejecutar_accion_item_funciona_sin_nada_marcado(vista, evento):
    """Es la contracara de la regla "Importante" en el camino por código."""
    assert vista.ejecutar_accion_item("editar", "CAR-001", evento) is True


def test_ejecutar_accion_item_sobre_un_codigo_que_ya_no_esta(vista, evento):
    assert vista.ejecutar_accion_item("editar", "NO-EXISTE", evento) is False


def test_ejecutar_accion_item_rechaza_una_accion_inventada(vista, evento):
    with pytest.raises(ValueError):
        vista.ejecutar_accion_item("teletransportar", "CAR-001", evento)


def test_los_botones_del_renglon_entran_por_el_punto_de_entrada_unico(vista, evento):
    """Si el botón no pasara por `ejecutar_accion_item`, la tecla y el mouse
    recorrerían caminos distintos y un día divergirían."""
    llamadas = []
    vista.ejecutar_accion_item = lambda accion, codigo, e=None: llamadas.append((accion, codigo))
    _repintar(vista)

    for boton in _botones_accion(_fila(vista, "CAR-001")):
        boton.on_click(evento)

    assert llamadas == [("editar", "CAR-001"), ("borrar", "CAR-001")]


# ─── 5. La columna del marcador es estructural ───────────────────────────────

def test_el_marcador_es_la_primera_columna_y_las_acciones_la_ultima(vista):
    assert vista._columnas_carrito_orden_visible()[0] == "marcador"
    assert vista._columnas_carrito_orden_visible()[-1] == "acciones"


def test_el_marcador_no_se_puede_ocultar_desde_el_selector_de_columnas(vista):
    assert "marcador" not in vista._columnas_carrito_ocultables
    etiquetas = [i.content for i in vista._build_selector_columnas_carrito().items]
    assert "Sel." not in etiquetas


def test_la_tabla_no_dibuja_la_columna_de_casillas_propia_de_flet(vista):
    """Con `on_select_change` en las filas, Flet añadiría una SEGUNDA casilla
    junto a nuestro marcador si no se desactiva explícitamente."""
    assert _tabla(vista).show_checkbox_column is False


# ─── 6. Sin selección fantasma ───────────────────────────────────────────────

def test_quitar_el_renglon_marcado_no_deja_una_marca_fantasma(vista, evento):
    """Un código marcado que ya no está en el carrito no tiene casilla con la
    que desmarcarse, y mientras exista deshabilita todo lo demás."""
    _clic_en_fila(vista, "CAR-002", evento)
    vista.handle_remover_item(evento, "CAR-002")

    _repintar(vista)
    assert vista._seleccion.hay_seleccion is False
    for codigo in ("CAR-001", "CAR-003"):
        assert all(b.disabled is False for b in _botones_accion(_fila(vista, codigo)))


# ─── 7. La mecánica también en los otros dos modos de vista ──────────────────

@pytest.mark.parametrize("modo", ["separado", "agrupado"])
def test_el_marcador_marca_y_sombrea_en_los_dos_formatos_de_tabla(vista, evento, modo):
    VentasView._modo_vista_carrito_estatico = modo
    try:
        _repintar(vista)
        _clic_en_fila(vista, "CAR-002", evento)
        _repintar(vista)

        fila = _fila(vista, "CAR-002")
        assert fila.selected is True
        assert _icono_casilla(fila).icon == ft.Icons.RADIO_BUTTON_CHECKED
        assert all(b.disabled is True for b in _botones_accion(_fila(vista, "CAR-001")))
    finally:
        VentasView._modo_vista_carrito_estatico = "separado"
