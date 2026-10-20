"""Añadir VARIOS ítems marcados al carrito, preguntando el destino.

Pedido del usuario del proyecto: "si es añadir al carrito, igual funciona que
pueda añadir todos los que tengo seleccionados". Y la corrección que vino
después, que es la que obliga a que haya un diálogo: "en la de F2, cuando se
llevan todos a ventas, tiene que preguntar si agregar todos al carrito o crear
un carrito nuevo. Porque a veces puede que se agreguen los artículos y no se
quiera agregar al carrito que está ahí, sino que se quiera agregar a uno nuevo
o a otro. Entonces debes preguntar".

Lo que estas pruebas blindan:
  - Que el lote NO se escribe en ningún carrito hasta que el usuario elige
    destino (el diálogo por sí solo no mueve nada).
  - Que "carrito nuevo" no toca el que estaba abierto.
  - Que la diferencia entre las dos acciones se conserva: F3 (añadir) se queda
    en Inventario y F2 (procesar venta) lleva además a Ventas.
  - La política de existencias insuficientes: se añade lo que se pueda y se
    avisa de lo que no (ver `_agregar_lote_a_carrito`).

Patrón de doble de página headless tomado de
`test_inventario_marcador_seleccion.py` / `test_inventario_borrado_clave.py`,
con dos añadidos que este bloque necesita: `views` y `go`, por los que la
vista navega a Ventas (ver `InventarioView._ir_a_ventas`).
"""
import flet as ft
import pytest

CODIGOS = ("LOT-001", "LOT-002", "LOT-003")
SIN_STOCK = "LOT-SIN"


class DashboardFalso:
    """Vista de ruta de arriba: es por quien el lote llega a Ventas."""

    def __init__(self):
        self.secciones = []

    def handle_nav_change(self, seccion: str):
        self.secciones.append(seccion)


class PageFalsa:
    """Pila de diálogos de Flet 0.86 más la navegación por vistas de ruta."""

    def __init__(self, con_dashboard: bool = True):
        self.dialogos = []
        self.overlay = []
        self.updates = 0
        self.on_keyboard_event = None
        self.rutas = []
        self.dashboard = DashboardFalso() if con_dashboard else None
        self.views = [self.dashboard] if con_dashboard else []

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

    def go(self, ruta):
        self.rutas.append(ruta)

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
def productos(db_temporal):
    """Tres productos con existencia y uno agotado (para el caso del lote
    parcial)."""
    from services.inventario_service import crear_producto

    for i, codigo in enumerate(CODIGOS, start=1):
        crear_producto(
            codigo=codigo,
            referencia=f"REF-{i}",
            descripcion_general=f"Producto de lote {i}",
            nombre_referencia_corto=f"Corto {i}",
            departamento="Pruebas",
            precio_dolares=10.0 * i,
            precio_bcv=9.0 * i,
            existencia=5,
            costo_usd_efectivo=5.0 * i,
            rol_usuario="administrador",
        )
    crear_producto(
        codigo=SIN_STOCK,
        referencia="REF-SIN",
        descripcion_general="Producto agotado",
        nombre_referencia_corto="Agotado",
        departamento="Pruebas",
        precio_dolares=7.0,
        existencia=0,
        rol_usuario="administrador",
    )
    return list(CODIGOS)


@pytest.fixture
def sesion_carritos():
    """Namespace de carritos limpio: `cart_manager` guarda el estado en un
    diccionario de módulo que sobrevive entre pruebas."""
    from services.cart_manager import limpiar_sesion

    sid = "_sin_sesion"
    limpiar_sesion(sid)
    yield sid
    limpiar_sesion(sid)


@pytest.fixture
def vista(productos, sesion_carritos):
    from ui.views.inventario_view import InventarioView

    v = InventarioView(es_admin=True, username="lotero", rol_usuario="administrador")
    v.get_body()
    return v


def _datos(vista) -> dict:
    """Los controles del diálogo de destino viajan en su `data`."""
    datos = vista._dialog.data
    assert isinstance(datos, dict) and "destino" in datos
    return datos


def _carritos(sid):
    from services.cart_manager import obtener_todos_los_carritos

    return obtener_todos_los_carritos(sid)


def _codigos_en(carrito) -> list[str]:
    return [i["codigo"] for i in carrito["items"]]


def _textos(control) -> list[str]:
    encontrados = []
    if isinstance(control, ft.Text) and control.value:
        encontrados.append(str(control.value))
    for atributo in ("controls", "content", "actions", "title"):
        hijo = getattr(control, atributo, None)
        if isinstance(hijo, list):
            for h in hijo:
                encontrados += _textos(h)
        elif hijo is not None and hasattr(hijo, "_c"):
            encontrados += _textos(hijo)
    return encontrados


def _avisos(pagina) -> str:
    """Todo lo que los `SnackBar` apilados en el overlay le dijeron al usuario."""
    return " ".join(t for s in pagina.overlay for t in _textos(s))


# ─────────────────────────────────────────────────────────────────────────────
# Se pregunta el destino ANTES de tocar nada
# ─────────────────────────────────────────────────────────────────────────────
def test_abrir_el_dialogo_no_agrega_nada_a_ningun_carrito(vista, sesion_carritos, evento):
    """La pregunta es la razón de ser del diálogo: si abrirlo ya escribiera en
    el carrito activo, preguntar sería decorativo."""
    vista._abrir_modal_destino_carrito_lote(CODIGOS, ir_a_ventas=False, e=evento)

    assert all(_codigos_en(c) == [] for c in _carritos(sesion_carritos).values())


def test_el_dialogo_ofrece_el_activo_los_abiertos_y_uno_nuevo(vista, sesion_carritos, evento):
    from services.cart_manager import crear_nuevo_carrito

    crear_nuevo_carrito(sesion_carritos)  # queda "Carrito 2", y además activo
    vista._abrir_modal_destino_carrito_lote(CODIGOS, ir_a_ventas=False, e=evento)

    valores = [o.key for o in _datos(vista)["destino"].options]
    assert vista._NUEVO_CARRITO in valores
    assert "Carrito 1" in valores and "Carrito 2" in valores
    assert _datos(vista)["destino"].value == "Carrito 2", "arranca en el activo"


def test_el_dialogo_nombra_los_items_por_su_descripcion(vista, evento):
    """Un código solo no le dice nada a quien atiende el mostrador."""
    vista._abrir_modal_destino_carrito_lote(CODIGOS, ir_a_ventas=False, e=evento)

    texto = " ".join(_textos(vista._dialog))
    assert "Corto 1" in texto and "LOT-001" in texto


def test_cancelar_el_destino_no_agrega_nada(vista, sesion_carritos, evento):
    vista._abrir_modal_destino_carrito_lote(CODIGOS, ir_a_ventas=False, e=evento)

    _datos(vista)["cancelar"](evento)

    assert all(_codigos_en(c) == [] for c in _carritos(sesion_carritos).values())
    assert vista._dialog_stack == []


def test_un_lote_vacio_no_abre_ningun_dialogo(vista, pagina, evento):
    assert vista._abrir_modal_destino_carrito_lote([], ir_a_ventas=False, e=evento) is None
    assert pagina.dialogos == []


# ─────────────────────────────────────────────────────────────────────────────
# Elegir el destino y agregar
# ─────────────────────────────────────────────────────────────────────────────
def test_elegir_el_carrito_abierto_agrega_todo_el_lote_ahi(vista, sesion_carritos, evento):
    vista._abrir_modal_destino_carrito_lote(CODIGOS, ir_a_ventas=False, e=evento)
    datos = _datos(vista)
    datos["destino"].value = "Carrito 1"

    datos["confirmar"](evento)

    assert _codigos_en(_carritos(sesion_carritos)["Carrito 1"]) == list(CODIGOS)
    assert vista._dialog_stack == [], "el diálogo se cierra antes de ejecutar"


def test_cada_item_entra_con_una_unidad(vista, sesion_carritos, evento):
    vista._abrir_modal_destino_carrito_lote(CODIGOS, ir_a_ventas=False, e=evento)
    datos = _datos(vista)
    datos["destino"].value = "Carrito 1"
    datos["confirmar"](evento)

    items = _carritos(sesion_carritos)["Carrito 1"]["items"]
    assert [i["cantidad"] for i in items] == [1.0, 1.0, 1.0]


def test_carrito_nuevo_no_toca_el_que_estaba_abierto(vista, sesion_carritos, evento):
    """Es la razón exacta por la que el usuario pidió la pregunta."""
    from services.cart_manager import agregar_o_actualizar_producto
    from services.inventario_service import obtener_producto

    # El carrito abierto ya lleva algo dentro.

    agregar_o_actualizar_producto(
        sesion_carritos, obtener_producto("LOT-003"), cantidad=4.0, id_carrito="Carrito 1",
    )

    vista._abrir_modal_destino_carrito_lote(["LOT-001", "LOT-002"], ir_a_ventas=False, e=evento)
    datos = _datos(vista)
    datos["destino"].value = vista._NUEVO_CARRITO
    datos["confirmar"](evento)

    carritos = _carritos(sesion_carritos)
    assert _codigos_en(carritos["Carrito 1"]) == ["LOT-003"], "el de antes queda intacto"
    assert carritos["Carrito 1"]["items"][0]["cantidad"] == 4.0
    nuevo = carritos["Carrito 2"]
    assert _codigos_en(nuevo) == ["LOT-001", "LOT-002"]


def test_el_destino_elegido_queda_activo(vista, sesion_carritos, evento):
    """Ventas abre el carrito activo: si el lote fuera a otro, el usuario
    llegaría a Ventas y no vería lo que acaba de añadir."""
    from services.cart_manager import obtener_id_carrito_activo

    vista._abrir_modal_destino_carrito_lote(CODIGOS, ir_a_ventas=False, e=evento)
    datos = _datos(vista)
    datos["destino"].value = vista._NUEVO_CARRITO
    datos["confirmar"](evento)

    assert obtener_id_carrito_activo(sesion_carritos) == "Carrito 2"


def test_un_destino_que_ya_no_existe_cae_al_activo(vista, sesion_carritos, evento):
    """Otro camino pudo eliminar el carrito entre la pregunta y la respuesta;
    eso no puede tumbar la acción ni perder el lote."""
    agregados = vista._agregar_lote_a_carrito(
        CODIGOS, "Carrito 42", ir_a_ventas=False, e=evento,
    )

    assert agregados == list(CODIGOS)
    assert _codigos_en(_carritos(sesion_carritos)["Carrito 1"]) == list(CODIGOS)


# ─────────────────────────────────────────────────────────────────────────────
# F2 lleva a Ventas, F3 no
# ─────────────────────────────────────────────────────────────────────────────
def test_procesar_venta_en_lote_lleva_a_ventas(vista, pagina, evento):
    vista._agregar_lote_a_carrito(CODIGOS, "Carrito 1", ir_a_ventas=True, e=evento)

    assert pagina.dashboard.secciones == ["Ventas"]


def test_anadir_al_carrito_en_lote_se_queda_en_inventario(vista, pagina, evento):
    vista._agregar_lote_a_carrito(CODIGOS, "Carrito 1", ir_a_ventas=False, e=evento)

    assert pagina.dashboard.secciones == []
    assert pagina.rutas == []


def test_sin_dashboard_la_navegacion_cae_a_la_ruta(vista, sesion_carritos):
    """Fuera del Dashboard no hay `handle_nav_change`, pero la ruta sigue."""
    pagina = PageFalsa(con_dashboard=False)
    evento = EventoFalso(pagina)

    vista._agregar_lote_a_carrito(CODIGOS, "Carrito 1", ir_a_ventas=True, e=evento)

    assert pagina.rutas == ["/ventas"]


def test_el_lote_no_pasa_por_el_callback_que_crea_un_carrito(vista, sesion_carritos, evento):
    """`on_procesar_venta` del Dashboard crea un carrito nuevo y mete el
    producto él mismo: usarlo para un lote ya añadido duplicaría el renglón y
    anularía la elección de destino."""
    llamadas = []
    vista.on_procesar_venta = lambda prod, ev=None: llamadas.append(prod["codigo"])

    vista._agregar_lote_a_carrito(CODIGOS, "Carrito 1", ir_a_ventas=True, e=evento)

    assert llamadas == []
    assert _codigos_en(_carritos(sesion_carritos)["Carrito 1"]) == list(CODIGOS)
    assert list(_carritos(sesion_carritos)) == ["Carrito 1"], "no se creó otro carrito"


# ─────────────────────────────────────────────────────────────────────────────
# Existencias insuficientes en el lote
# ─────────────────────────────────────────────────────────────────────────────
def test_se_agrega_lo_que_se_puede_y_se_avisa_de_lo_que_no(vista, pagina, sesion_carritos, evento):
    """Rechazar el lote entero obligaría al usuario a adivinar cuál de los
    códigos es el culpable y volver a empezar."""
    agregados = vista._agregar_lote_a_carrito(
        ["LOT-001", SIN_STOCK, "LOT-002"], "Carrito 1", ir_a_ventas=False, e=evento,
    )

    assert agregados == ["LOT-001", "LOT-002"]
    assert _codigos_en(_carritos(sesion_carritos)["Carrito 1"]) == ["LOT-001", "LOT-002"]
    avisos = _avisos(pagina)
    assert SIN_STOCK in avisos, "la omisión no puede pasar desapercibida"


def test_si_ninguno_tiene_existencia_no_se_agrega_ni_se_crea_carrito(
    vista, pagina, sesion_carritos, evento
):
    agregados = vista._agregar_lote_a_carrito(
        [SIN_STOCK], vista._NUEVO_CARRITO, ir_a_ventas=False, e=evento,
    )

    assert agregados == []
    assert list(_carritos(sesion_carritos)) == ["Carrito 1"], "sin carritos vacíos colgados"
    assert "existencia" in _avisos(pagina)


def test_un_codigo_borrado_entre_el_marcado_y_la_confirmacion_queda_fuera(
    vista, sesion_carritos, evento
):
    from services.inventario_service import eliminar_producto

    vista._abrir_modal_destino_carrito_lote(
        ["LOT-001", "LOT-002"], ir_a_ventas=False, e=evento,
    )
    datos = _datos(vista)
    datos["destino"].value = "Carrito 1"
    # El índice de pantalla aún lo recuerda, así que hay que vaciarlo para
    # reproducir el caso real (la relectura de la base es la que falla).
    vista._productos_en_pantalla.pop("LOT-002", None)
    eliminar_producto("LOT-002")

    datos["confirmar"](evento)

    assert _codigos_en(_carritos(sesion_carritos)["Carrito 1"]) == ["LOT-001"]
