"""Las acciones del Inventario tienen en cuenta TODOS los ítems marcados.

Hasta ahora la selección múltiple servía solo para el borrado masivo: el resto
de las acciones actuaba sobre un único ítem. El usuario del proyecto pidió que
todas tuvieran en cuenta el lote, y la tabla que resulta de lo que pidió es:

| Tecla | Acción             | Con varios marcados                          |
|-------|--------------------|----------------------------------------------|
| F1    | Info / detalle     | elegir UNO de la lista de marcados           |
| F2    | Procesar venta     | TODOS, preguntando antes el carrito destino  |
| F3    | Añadir al carrito  | TODOS, preguntando antes el carrito destino  |
| F4    | Historial clínico  | elegir UNO de la lista de marcados           |
| F5    | Editar             | elegir UNO de la lista de marcados           |
| F6    | Borrar             | TODOS, con la clave una sola vez             |

Con cero o un ítem marcado, todo sigue exactamente como antes: ese es el
contrato que más fácil se rompe al cablear el despacho, así que tiene pruebas
propias.

La otra mitad del bloque es el camino del MOUSE: el clic en un ícono señala una
fila concreta, así que con varias marcadas hay una disyuntiva real y se
pregunta siempre ("si se usa el ícono y hay varios seleccionados, debe
preguntar si solamente al que se le está haciendo clic o a todos los que están
seleccionados").

Patrón de doble de página headless tomado de
`test_inventario_marcador_seleccion.py` / `test_inventario_borrado_clave.py`;
las pulsaciones se ejercitan con `asyncio.run` porque `ControlTeclado.manejar`
es una corutina, igual que en `test_control_teclado.py`.
"""
import asyncio

import flet as ft
import pytest

from ui.components.dialogo_alcance import (
    ALCANCE_TODOS, ALCANCE_UNO, DialogoAlcance, DialogoElegirItem,
)
from ui.components.teclado_nav import ATAJOS_ITEM

CODIGOS = ("LTE-001", "LTE-002", "LTE-003", "LTE-004")
CLAVE = "clave-de-la-sesion-123"


class DashboardFalso:
    def __init__(self):
        self.secciones = []

    def handle_nav_change(self, seccion: str):
        self.secciones.append(seccion)


class PageFalsa:
    """Página headless con teclado, pila de diálogos y navegación de rutas."""

    def __init__(self):
        self.dialogos = []
        self.overlay = []
        self.updates = 0
        self.on_keyboard_event = None
        self.rutas = []
        self.dashboard = DashboardFalso()
        self.views = [self.dashboard]

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


class TeclaFalsa:
    def __init__(self, page, key, **modificadores):
        self.page = page
        self.key = key
        for nombre, valor in modificadores.items():
            setattr(self, nombre, valor)


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
            descripcion_general=f"Producto de lote {i}",
            nombre_referencia_corto=f"Corto {i}",
            departamento="Pruebas",
            precio_dolares=10.0 * i,
            existencia=4,
            costo_usd_efectivo=5.0 * i,
            rol_usuario="administrador",
        )
    return list(CODIGOS)


@pytest.fixture
def sesion_carritos():
    """`cart_manager` guarda el estado en un diccionario de módulo que
    sobrevive entre pruebas, así que el namespace se limpia a mano."""
    from services.cart_manager import limpiar_sesion

    sid = "_sin_sesion"
    limpiar_sesion(sid)
    yield sid
    limpiar_sesion(sid)


@pytest.fixture
def vista(productos, pagina, sesion_carritos):
    """Vista de administrador con una cuenta de sesión de clave conocida."""
    from services.user_service import create_user
    from ui.views.inventario_view import InventarioView

    create_user("lotero", CLAVE, "administrador")
    v = InventarioView(es_admin=True, username="lotero", rol_usuario="administrador")
    v.get_body()
    v._teclado.instalar(EventoFalso(pagina))
    return v


@pytest.fixture
def espia(vista):
    """Registra sobre qué código terminó actuando cada handler de verdad.

    Se espían los seis handlers y no el punto de entrada: lo que hay que
    comprobar en este bloque es justamente QUÉ ítems alcanzó la acción al
    final del despacho, que es lo que el punto de entrada ya no dice.
    """
    hechas = []
    for accion in vista.ACCIONES_ITEM:
        setattr(
            vista,
            f"accion_{accion}",
            lambda codigo, e=None, a=accion: hechas.append((a, codigo)),
        )
    return hechas


def _pulsar(vista, pagina, tecla):
    return asyncio.run(vista._teclado.manejar(TeclaFalsa(pagina, tecla)))


def _marcar_lote(vista, codigos, evento):
    vista.alternar_modo_seleccion(evento)
    for codigo in codigos:
        vista.alternar_item(codigo, evento)


def _existe(codigo: str) -> bool:
    from services.inventario_service import obtener_producto

    return obtener_producto(codigo) is not None


def _carrito(sid, cid="Carrito 1"):
    from services.cart_manager import obtener_todos_los_carritos

    return obtener_todos_los_carritos(sid)[cid]


def _codigos_en(carrito) -> list[str]:
    return [i["codigo"] for i in carrito["items"]]


def _componente(vista):
    """Todos los diálogos de este bloque viajan en el `data` del suyo."""
    return vista._dialog.data


# ─────────────────────────────────────────────────────────────────────────────
# Con cero o un marcado, nada cambia
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("tecla,accion", sorted(ATAJOS_ITEM.items()))
def test_con_un_solo_marcado_la_tecla_actua_sobre_el_sin_preguntar(
    vista, espia, pagina, evento, tecla, accion
):
    vista.seleccionar_item("LTE-002", evento)

    _pulsar(vista, pagina, tecla)

    assert espia == [(accion, "LTE-002")]
    assert pagina.dialogos == [], "con uno marcado no hay nada que preguntar"


@pytest.mark.parametrize("accion", sorted(("info", "cobrar", "carrito", "historial", "editar", "borrar")))
def test_con_un_solo_marcado_el_icono_actua_sobre_el_sin_preguntar(
    vista, espia, pagina, evento, accion
):
    vista.seleccionar_item("LTE-002", evento)

    assert vista.ejecutar_accion_item(accion, "LTE-002", evento) is True

    assert espia == [(accion, "LTE-002")]
    assert pagina.dialogos == []


def test_sin_nada_marcado_los_iconos_de_todas_las_filas_funcionan(vista, espia, pagina, evento):
    """La regla "Importante": sin selección, todo como en la versión anterior."""
    for codigo in CODIGOS:
        assert vista.ejecutar_accion_item("info", codigo, evento) is True

    assert espia == [("info", c) for c in CODIGOS]
    assert pagina.dialogos == []


def test_sin_nada_marcado_las_teclas_siguen_sin_hacer_nada(vista, espia, pagina):
    for tecla in sorted(ATAJOS_ITEM):
        _pulsar(vista, pagina, tecla)

    assert espia == []
    assert pagina.dialogos == []


# ─────────────────────────────────────────────────────────────────────────────
# F1 / F4 / F5: elegir UNO de los marcados
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("tecla,accion", [("F1", "info"), ("F4", "historial"), ("F5", "editar")])
def test_las_acciones_de_uno_muestran_la_lista_de_marcados(
    vista, espia, pagina, evento, tecla, accion
):
    """Ver el detalle de tres productos a la vez no significa nada: se elige."""
    _marcar_lote(vista, ["LTE-001", "LTE-002", "LTE-003"], evento)

    _pulsar(vista, pagina, tecla)

    comp = _componente(vista)
    assert isinstance(comp, DialogoElegirItem)
    assert comp.marcados == ["LTE-001", "LTE-002", "LTE-003"]
    assert espia == [], "mostrar la lista no ejecuta nada todavía"


def test_la_lista_nombra_los_items_por_su_descripcion_y_no_solo_por_el_codigo(
    vista, pagina, evento
):
    """"LTE-002" no le dice nada a quien atiende el mostrador."""
    _marcar_lote(vista, ["LTE-001", "LTE-002"], evento)

    _pulsar(vista, pagina, "F1")

    titulos = [o.title.value for o in _componente(vista).opciones]
    assert titulos == ["Corto 1", "Corto 2"]
    subtitulos = [o.subtitle.value for o in _componente(vista).opciones]
    assert subtitulos == ["LTE-001", "LTE-002"]


def test_elegir_un_item_de_la_lista_ejecuta_solo_sobre_ese(vista, espia, pagina, evento):
    _marcar_lote(vista, ["LTE-001", "LTE-002", "LTE-003"], evento)
    _pulsar(vista, pagina, "F5")

    _componente(vista).elegir("LTE-003", evento)

    assert espia == [("editar", "LTE-003")]
    assert vista._dialog_stack == [], "la lista se cierra antes de ejecutar"


def test_cancelar_la_lista_no_ejecuta_nada(vista, espia, pagina, evento):
    _marcar_lote(vista, ["LTE-001", "LTE-002"], evento)
    _pulsar(vista, pagina, "F1")

    _componente(vista).cancelar(evento)

    assert espia == []
    assert vista._dialog_stack == []


def test_un_vendedor_no_abre_la_lista_del_historial_clinico(productos, pagina):
    """F4 sigue siendo solo de administradores, también en lote."""
    from ui.views.inventario_view import InventarioView

    v = InventarioView(es_admin=False, username="vendedor", rol_usuario="vendedor")
    v.get_body()
    v._teclado.instalar(EventoFalso(pagina))
    ev = EventoFalso(pagina)
    _marcar_lote(v, ["LTE-001", "LTE-002"], ev)

    _pulsar(v, pagina, "F4")

    assert pagina.dialogos == []
    assert v._dialog is None


# ─────────────────────────────────────────────────────────────────────────────
# F2 / F3: todo el lote, preguntando el carrito destino
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("tecla,ir_a_ventas", [("F2", True), ("F3", False)])
def test_las_dos_acciones_de_carrito_preguntan_el_destino(
    vista, pagina, evento, sesion_carritos, tecla, ir_a_ventas
):
    _marcar_lote(vista, ["LTE-001", "LTE-002"], evento)

    _pulsar(vista, pagina, tecla)

    datos = _componente(vista)
    assert isinstance(datos, dict) and "destino" in datos
    assert datos["codigos"] == ("LTE-001", "LTE-002")
    assert datos["ir_a_ventas"] is ir_a_ventas
    assert _codigos_en(_carrito(sesion_carritos)) == [], "aún no se agregó nada"


def test_f3_agrega_todo_el_lote_y_se_queda_en_inventario(
    vista, pagina, evento, sesion_carritos
):
    _marcar_lote(vista, ["LTE-001", "LTE-002", "LTE-003"], evento)
    _pulsar(vista, pagina, "F3")
    datos = _componente(vista)
    datos["destino"].value = "Carrito 1"

    datos["confirmar"](evento)

    assert _codigos_en(_carrito(sesion_carritos)) == ["LTE-001", "LTE-002", "LTE-003"]
    assert pagina.dashboard.secciones == [], "F3 no sale de Inventario"


def test_f2_agrega_todo_el_lote_y_lleva_a_ventas(vista, pagina, evento, sesion_carritos):
    _marcar_lote(vista, ["LTE-001", "LTE-002"], evento)
    _pulsar(vista, pagina, "F2")
    datos = _componente(vista)
    datos["destino"].value = "Carrito 1"

    datos["confirmar"](evento)

    assert _codigos_en(_carrito(sesion_carritos)) == ["LTE-001", "LTE-002"]
    assert pagina.dashboard.secciones == ["Ventas"]


def test_elegir_carrito_nuevo_no_toca_el_que_estaba_abierto(
    vista, pagina, evento, sesion_carritos
):
    """Corrección expresa del usuario: por eso F2/F3 preguntan el destino."""
    from services.cart_manager import agregar_o_actualizar_producto
    from services.inventario_service import obtener_producto

    agregar_o_actualizar_producto(
        sesion_carritos, obtener_producto("LTE-004"), cantidad=2.0, id_carrito="Carrito 1",
    )

    _marcar_lote(vista, ["LTE-001", "LTE-002"], evento)
    _pulsar(vista, pagina, "F3")
    datos = _componente(vista)
    datos["destino"].value = vista._NUEVO_CARRITO
    datos["confirmar"](evento)

    assert _codigos_en(_carrito(sesion_carritos, "Carrito 1")) == ["LTE-004"]
    assert _codigos_en(_carrito(sesion_carritos, "Carrito 2")) == ["LTE-001", "LTE-002"]


# ─────────────────────────────────────────────────────────────────────────────
# F6: todo el lote, con la clave una sola vez
# ─────────────────────────────────────────────────────────────────────────────
def test_f6_pide_la_clave_una_sola_vez_y_borra_todo_el_lote(vista, pagina, evento):
    from ui.components.dialogo_clave import DialogoClave

    lote = ["LTE-001", "LTE-002", "LTE-003"]
    _marcar_lote(vista, lote, evento)

    _pulsar(vista, pagina, "F6")
    assert len(pagina.dialogos) == 1, "un solo diálogo de clave para todo el lote"
    comp = _componente(vista)
    assert isinstance(comp, DialogoClave)
    comp.campo.value = CLAVE
    comp.confirmar(evento)

    assert [c for c in lote if _existe(c)] == []
    assert _existe("LTE-004"), "lo que no estaba marcado no se toca"
    assert len(pagina.dialogos) == 1, "no se pidió la clave una segunda vez"


def test_f6_con_la_clave_incorrecta_no_borra_el_lote(vista, pagina, evento):
    lote = ["LTE-001", "LTE-002"]
    _marcar_lote(vista, lote, evento)
    _pulsar(vista, pagina, "F6")
    comp = _componente(vista)
    comp.campo.value = "no-es-la-clave"

    comp.confirmar(evento)

    assert all(_existe(c) for c in lote)
    assert comp.error.value == "Clave incorrecta"
    assert vista._seleccion.cantidad == 2, "el lote se conserva para reintentar"


def test_el_dialogo_de_f6_enuncia_el_lote_completo(vista, pagina, evento):
    _marcar_lote(vista, ["LTE-001", "LTE-002"], evento)

    _pulsar(vista, pagina, "F6")

    texto = " ".join(
        c.value or "" for c in vista._dialog.content.controls if isinstance(c, ft.Text)
    )
    assert "2" in texto and "LTE-001" in texto and "LTE-002" in texto


# ─────────────────────────────────────────────────────────────────────────────
# Camino del mouse: el ícono pregunta "¿este o todos?"
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("accion", ["info", "cobrar", "carrito", "historial", "editar", "borrar"])
def test_el_icono_con_varios_marcados_siempre_pregunta_el_alcance(
    vista, espia, pagina, evento, accion
):
    _marcar_lote(vista, ["LTE-001", "LTE-002", "LTE-003"], evento)

    assert vista.ejecutar_accion_item(accion, "LTE-002", evento) is True

    comp = _componente(vista)
    assert isinstance(comp, DialogoAlcance)
    assert comp.codigo == "LTE-002"
    assert comp.marcados == ["LTE-001", "LTE-002", "LTE-003"]
    assert espia == [], "preguntar no ejecuta nada"


def test_solo_este_actua_unicamente_sobre_la_fila_del_clic(vista, espia, pagina, evento):
    _marcar_lote(vista, ["LTE-001", "LTE-002", "LTE-003"], evento)
    vista.ejecutar_accion_item("editar", "LTE-002", evento)

    assert _componente(vista).elegir_uno(evento) == ALCANCE_UNO

    assert espia == [("editar", "LTE-002")]
    assert vista._dialog_stack == [], "el alcance se cierra antes de ejecutar"


def test_los_n_marcados_lleva_a_la_lista_cuando_la_accion_es_de_una_en_una(
    vista, espia, pagina, evento
):
    """"Si elige el lote y la acción es de las de elegir uno, se muestra la
    lista": el ícono y la tecla acaban en el mismo sitio."""
    _marcar_lote(vista, ["LTE-001", "LTE-002", "LTE-003"], evento)
    vista.ejecutar_accion_item("info", "LTE-002", evento)

    assert _componente(vista).elegir_todos(evento) == ALCANCE_TODOS

    comp = _componente(vista)
    assert isinstance(comp, DialogoElegirItem)
    assert comp.marcados == ["LTE-001", "LTE-002", "LTE-003"]
    assert espia == []


def test_los_n_marcados_agrega_el_lote_entero_al_carrito(
    vista, pagina, evento, sesion_carritos
):
    _marcar_lote(vista, ["LTE-001", "LTE-002"], evento)
    vista.ejecutar_accion_item("carrito", "LTE-001", evento)
    _componente(vista).elegir_todos(evento)

    datos = _componente(vista)
    datos["destino"].value = "Carrito 1"
    datos["confirmar"](evento)

    assert _codigos_en(_carrito(sesion_carritos)) == ["LTE-001", "LTE-002"]


def test_solo_este_agrega_un_solo_item_al_carrito(vista, espia, pagina, evento):
    """"Solo este" y "los N" tienen que hacer cosas distintas, no la misma."""
    _marcar_lote(vista, ["LTE-001", "LTE-002"], evento)
    vista.ejecutar_accion_item("carrito", "LTE-001", evento)

    _componente(vista).elegir_uno(evento)

    assert espia == [("carrito", "LTE-001")]


def test_cancelar_el_alcance_no_ejecuta_nada(vista, espia, pagina, evento):
    """Cancelar no es "solo este" por omisión: no se actúa sobre nada."""
    _marcar_lote(vista, ["LTE-001", "LTE-002"], evento)
    vista.ejecutar_accion_item("borrar", "LTE-001", evento)

    _componente(vista).cancelar(evento)

    assert espia == []
    assert all(_existe(c) for c in CODIGOS)
    assert vista._dialog_stack == []
    assert pagina.visible is None


def test_la_respuesta_no_se_recuerda_para_el_clic_siguiente(vista, espia, pagina, evento):
    """La intención cambia de un clic al otro: recordarla sería decidir por el
    usuario."""
    _marcar_lote(vista, ["LTE-001", "LTE-002"], evento)
    vista.ejecutar_accion_item("editar", "LTE-001", evento)
    _componente(vista).elegir_uno(evento)
    espia.clear()

    vista.ejecutar_accion_item("editar", "LTE-001", evento)

    assert isinstance(_componente(vista), DialogoAlcance), "vuelve a preguntar"
    assert espia == []


def test_el_icono_de_una_fila_ajena_al_lote_sigue_rechazado(vista, espia, pagina, evento):
    """Sobre una fila que no está en el lote no hay disyuntiva que plantear:
    el botón ya viene deshabilitado y la regla se repite aquí."""
    _marcar_lote(vista, ["LTE-001", "LTE-002"], evento)

    assert vista.ejecutar_accion_item("editar", "LTE-004", evento) is False

    assert espia == []
    assert pagina.dialogos == []


def test_el_alcance_enuncia_la_accion_en_palabras_del_usuario(vista, evento):
    _marcar_lote(vista, ["LTE-001", "LTE-002"], evento)
    vista.ejecutar_accion_item("carrito", "LTE-001", evento)

    titulo = " ".join(
        t.value for t in vista._dialog.title.controls if isinstance(t, ft.Text)
    )
    assert titulo == "Añadir al carrito"


# ─────────────────────────────────────────────────────────────────────────────
# El borrado masivo sigue alcanzable con el mouse
# ─────────────────────────────────────────────────────────────────────────────
def test_el_borrado_masivo_se_alcanza_desde_el_icono_de_una_fila(vista, pagina, evento):
    """Se retiró el botón "Borrar marcados" de la barra porque F6 ya cubre el
    lote; el camino del mouse tiene que seguir existiendo, o el borrado masivo
    quedaría accesible solo por teclado."""
    from ui.components.dialogo_clave import DialogoClave

    lote = ["LTE-001", "LTE-002", "LTE-003"]
    _marcar_lote(vista, lote, evento)

    # Exactamente lo que hace el ícono de la papelera de una fila marcada.
    vista.ejecutar_accion_item("borrar", "LTE-002", evento)
    _componente(vista).elegir_todos(evento)

    comp = _componente(vista)
    assert isinstance(comp, DialogoClave), "una sola clave para todo el lote"
    comp.campo.value = CLAVE
    comp.confirmar(evento)

    assert [c for c in lote if _existe(c)] == []
    assert _existe("LTE-004")


def test_el_icono_de_borrar_de_una_fila_marcada_puede_borrar_solo_esa(vista, pagina, evento):
    _marcar_lote(vista, ["LTE-001", "LTE-002"], evento)
    vista.ejecutar_accion_item("borrar", "LTE-001", evento)

    _componente(vista).elegir_uno(evento)
    comp = _componente(vista)
    comp.campo.value = CLAVE
    comp.confirmar(evento)

    assert not _existe("LTE-001")
    assert _existe("LTE-002"), "el resto del lote no se toca"


# ─────────────────────────────────────────────────────────────────────────────
# Clasificación de las seis acciones
# ─────────────────────────────────────────────────────────────────────────────
def test_las_dos_clasificaciones_cubren_las_seis_acciones(vista):
    """Una acción sin clasificar se despacharía de forma arbitraria."""
    from ui.views.inventario_view import InventarioView

    clasificadas = set(InventarioView.ACCIONES_DE_UNO) | set(InventarioView.ACCIONES_EN_LOTE)
    assert clasificadas == set(InventarioView.ACCIONES_ITEM)
    assert not set(InventarioView.ACCIONES_DE_UNO) & set(InventarioView.ACCIONES_EN_LOTE)
    assert set(InventarioView.ETIQUETAS_ACCION) == set(InventarioView.ACCIONES_ITEM)


def test_una_accion_inventada_falla_ruidosamente(vista, evento):
    """Un nombre mal escrito se vería como un botón que no hace nada."""
    with pytest.raises(ValueError):
        vista.ejecutar_accion_item("inventada", "LTE-001", evento)
    with pytest.raises(ValueError):
        vista._ejecutar_accion_en_lote("inventada", ["LTE-001", "LTE-002"], evento)
