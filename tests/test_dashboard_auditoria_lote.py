"""Selección múltiple y acciones sobre el lote en la Auditoría Preventiva.

Decisiones del usuario del proyecto que se blindan aquí:

  - La selección múltiple se activa desde un conmutador CON ETIQUETA VISIBLE.
    En el catálogo de Inventario no la encontró porque era un ícono suelto, y
    ya se corrigió allí: una función que existe pero nadie descubre es una
    función que no existe.
  - Con varios marcados, el clic en un ícono pregunta SIEMPRE si la acción va
    sobre ese ítem o sobre todo el lote (`DialogoAlcance`).
  - Ver detalle, Historial y Editar no tienen sentido en lote: cuando la acción
    debe aplicarse a "todos" —por tecla, o porque el usuario eligió el lote— se
    muestra `DialogoElegirItem` para que elija uno, con la descripción corta
    del producto y no solo el código.
  - Contactar proveedor sí lo tiene, y se resuelve agrupado por proveedor.
"""
import asyncio

import flet as ft
import pytest

from services.cartera_service import crear_proveedor
from services.inventario_service import crear_producto
from ui.components.dialogo_alcance import DialogoAlcance, DialogoElegirItem

CODIGOS = ("AUD-001", "AUD-002", "AUD-003")


def _recorrer(control, _vistos=None):
    if _vistos is None:
        _vistos = set()
    if control is None or not hasattr(control, "_c") or id(control) in _vistos:
        return
    _vistos.add(id(control))
    yield control
    for atributo in ("controls", "content", "actions", "title", "subtitle",
                     "rows", "columns", "cells", "label"):
        hijo = getattr(control, atributo, None)
        if isinstance(hijo, list):
            for h in hijo:
                yield from _recorrer(h, _vistos)
        else:
            yield from _recorrer(hijo, _vistos)


def _textos(control) -> list[str]:
    return [str(c.value) for c in _recorrer(control) if isinstance(c, ft.Text) and c.value]


class PaginaFalsa:
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
    def __init__(self, page, key=""):
        self.page = page
        self.key = key


@pytest.fixture
def pagina():
    return PaginaFalsa()


@pytest.fixture
def evento(pagina):
    return EventoFalso(pagina)


@pytest.fixture
def productos(db_temporal):
    """Tres productos críticos: dos del mismo proveedor y uno de otro."""
    acme = crear_proveedor(
        empresa="Acme C.A.", contacto="Juan Pérez", telefono="0412-1112233",
        correo="ventas@acme.com", rif="J-111111",
    )
    globex = crear_proveedor(
        empresa="Globex S.A.", contacto="Ana Díaz", telefono="0414-9998877",
        correo="compras@globex.com", rif="J-222222",
    )
    proveedores = {"AUD-001": acme["id"], "AUD-002": acme["id"], "AUD-003": globex["id"]}
    for i, codigo in enumerate(CODIGOS, start=1):
        crear_producto(
            codigo=codigo, referencia=f"REF-{i}",
            descripcion_general=f"Producto critico {i}",
            departamento="Ferretería", precio_dolares=10.0 * i, existencia=0.0,
            nombre_referencia_corto=f"Corto {codigo}",
            proveedor_id=proveedores[codigo],
            costo_usd_efectivo=None, rol_usuario="administrador",
        )
    return list(CODIGOS)


@pytest.fixture
def vista(productos, pagina):
    from ui.views.dashboard_view import DashboardView

    DashboardView.ensure_settings_loaded()
    v = DashboardView(user_info={"username": "tester", "role": "administrador"})
    v.get_current_page = lambda e=None: pagina
    v.current_section = "Inicio"
    v.get_body()
    return v


@pytest.fixture
def vista_con_lote(vista, evento):
    """Modo múltiple con dos ítems marcados (uno de cada proveedor)."""
    vista.alternar_modo_seleccion_auditoria(evento)
    for codigo in ("AUD-001", "AUD-003"):
        vista.seleccionar_item_auditoria(codigo, evento)
    return vista


def _fila(vista, codigo) -> ft.DataRow:
    return next(r for r in vista._dt_auditoria.rows if r.data == codigo)


def _icono_de(control) -> ft.IconButton:
    if isinstance(control, ft.Stack):
        return next(c for c in control.controls if isinstance(c, ft.IconButton))
    return control


def _botones(fila: ft.DataRow) -> list[ft.IconButton]:
    contenido = fila.cells[-1].content
    if isinstance(contenido, ft.Container):
        contenido = contenido.content
    return [
        _icono_de(c) for c in contenido.controls
        if isinstance(c, (ft.IconButton, ft.Stack))
    ]


def _componente(dialogo):
    """Los componentes de diálogo viajan pegados a su `AlertDialog` en `data`."""
    return dialogo.data


def _pulsar(vista, pagina, tecla):
    return asyncio.run(vista._teclado.manejar(EventoFalso(pagina, tecla)))


# ─────────────────────────────────────────────────────────────────────────────
# El conmutador, con etiqueta visible
# ─────────────────────────────────────────────────────────────────────────────
def test_el_conmutador_lleva_etiqueta_visible(vista):
    """Un ícono gris sin texto se lee como un indicador de estado, no como algo
    que se pueda pulsar: así se perdió la función en el catálogo."""
    assert "Selección múltiple" in _textos(vista._btn_modo_seleccion_auditoria)
    assert vista._btn_modo_seleccion_auditoria.on_click is not None


def test_el_conmutador_esta_en_la_barra_de_la_tarjeta(vista):
    assert vista._btn_modo_seleccion_auditoria in vista._barra_seleccion_auditoria.controls


def test_el_conmutador_entra_y_sale_del_modo_de_lote(vista, evento):
    assert vista._seleccion_auditoria.es_multiple is False

    vista._btn_modo_seleccion_auditoria.on_click(evento)
    assert vista._seleccion_auditoria.es_multiple is True

    vista._btn_modo_seleccion_auditoria.on_click(evento)
    assert vista._seleccion_auditoria.es_multiple is False


def test_el_conmutador_dice_que_hace_el_proximo_clic(vista, evento):
    """Un botón que solo se tiñe deja al usuario adivinando si ya lo pulsó."""
    vista.alternar_modo_seleccion_auditoria(evento)

    assert "Salir de selección múltiple" in _textos(vista._btn_modo_seleccion_auditoria)


def test_la_barra_cuenta_cuantos_items_hay_marcados(vista_con_lote):
    assert vista_con_lote._lbl_seleccion_auditoria.value == "2 ítems marcados"


def test_el_boton_de_limpiar_aparece_solo_con_seleccion(vista, evento):
    assert vista._btn_limpiar_seleccion_auditoria.visible is False

    vista.seleccionar_item_auditoria("AUD-001", evento)
    assert vista._btn_limpiar_seleccion_auditoria.visible is True

    vista._btn_limpiar_seleccion_auditoria.on_click(evento)
    assert vista._seleccion_auditoria.hay_seleccion is False
    assert vista._btn_limpiar_seleccion_auditoria.visible is False


# ─────────────────────────────────────────────────────────────────────────────
# Marcar varios
# ─────────────────────────────────────────────────────────────────────────────
def test_en_modo_multiple_se_marcan_varios_a_la_vez(vista_con_lote):
    assert vista_con_lote._seleccion_auditoria.seleccionados == ("AUD-001", "AUD-003")
    assert _fila(vista_con_lote, "AUD-001").selected is True
    assert _fila(vista_con_lote, "AUD-003").selected is True


def test_entrar_al_modo_multiple_conserva_lo_ya_marcado(vista, evento):
    """El ítem que el usuario venía señalando pasa a ser el primero del lote,
    sin obligarlo a volver a marcarlo."""
    vista.seleccionar_item_auditoria("AUD-002", evento)

    vista.alternar_modo_seleccion_auditoria(evento)

    assert vista._seleccion_auditoria.seleccionados == ("AUD-002",)


def test_salir_del_modo_multiple_limpia_el_lote(vista_con_lote, evento):
    """Volver al marcador único con dos marcados dejaría un estado que ese modo
    no puede representar y una lista sombreada a medias."""
    vista_con_lote.alternar_modo_seleccion_auditoria(evento)

    assert vista_con_lote._seleccion_auditoria.hay_seleccion is False


def test_la_casilla_cambia_de_forma_en_el_modo_de_lote(vista_con_lote):
    """Cuadrada para el lote, redonda para el marcador único: el usuario no
    tiene que ir a mirar el conmutador."""
    icono = _fila(vista_con_lote, "AUD-001").cells[0].content.content

    assert icono.icon == ft.Icons.CHECK_BOX_ROUNDED


def test_los_items_del_lote_conservan_sus_iconos_y_los_demas_no(vista_con_lote):
    assert all(b.disabled is False for b in _botones(_fila(vista_con_lote, "AUD-001")))
    assert all(b.disabled is True for b in _botones(_fila(vista_con_lote, "AUD-002")))


# ─────────────────────────────────────────────────────────────────────────────
# Clic con varios marcados: ¿este o todos?
# ─────────────────────────────────────────────────────────────────────────────
def test_el_clic_con_varios_marcados_pregunta_el_alcance(vista_con_lote, evento, pagina):
    _botones(_fila(vista_con_lote, "AUD-001"))[0].on_click(evento)

    assert pagina.dialogos, "no se abrió la pregunta de alcance"
    assert isinstance(_componente(pagina.dialogos[-1]), DialogoAlcance)


def test_la_pregunta_de_alcance_nombra_la_accion_y_el_item(vista_con_lote, evento, pagina):
    _botones(_fila(vista_con_lote, "AUD-001"))[2].on_click(evento)  # editar

    texto = " ".join(_textos(pagina.dialogos[-1]))
    assert "Editar" in texto
    assert "AUD-001" in texto
    assert "2" in texto


def test_con_un_solo_item_marcado_no_se_pregunta_nada(vista, evento, pagina):
    """Con uno marcado el destinatario es evidente y preguntar sería ruido."""
    vista.seleccionar_item_auditoria("AUD-001", evento)

    _botones(_fila(vista, "AUD-001"))[2].on_click(evento)  # editar

    assert vista._vista_inventario_auxiliar._editing_codigo == "AUD-001"
    assert not any(isinstance(_componente(d), DialogoAlcance) for d in pagina.dialogos)


def test_elegir_solo_este_acciona_un_solo_item(vista_con_lote, evento, pagina):
    _botones(_fila(vista_con_lote, "AUD-003"))[2].on_click(evento)  # editar

    _componente(pagina.dialogos[-1]).boton_uno.on_click(evento)

    assert vista_con_lote._vista_inventario_auxiliar._editing_codigo == "AUD-003"


def test_cancelar_la_pregunta_no_ejecuta_nada(vista_con_lote, evento, pagina):
    """Cancelar no es "solo este" por omisión."""
    _botones(_fila(vista_con_lote, "AUD-001"))[2].on_click(evento)
    dialogo = pagina.dialogos[-1]

    _componente(dialogo).boton_cancelar.on_click(evento)

    assert vista_con_lote._vista_inventario_auxiliar is None
    assert dialogo not in vista_con_lote._dialogos_inicio


# ─────────────────────────────────────────────────────────────────────────────
# "Todos" en una acción que se hace de a uno: ¿cuál?
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("indice,accion", [(0, "info"), (1, "historial"), (2, "editar")])
def test_elegir_el_lote_pregunta_cual_item(vista_con_lote, evento, pagina, indice, accion):
    """Ver cinco fichas a la vez no significa nada, y editar cinco juntos
    menos: se ofrece elegir en vez de mandar a desmarcar."""
    _botones(_fila(vista_con_lote, "AUD-001"))[indice].on_click(evento)

    _componente(pagina.dialogos[-1]).boton_todos.on_click(evento)

    componente = _componente(pagina.dialogos[-1])
    assert isinstance(componente, DialogoElegirItem)
    assert [o.data for o in componente.opciones] == ["AUD-001", "AUD-003"]


def test_la_eleccion_nombra_el_producto_y_no_solo_el_codigo(vista_con_lote, evento, pagina):
    """El código solo no le dice nada a quien atiende el mostrador."""
    _botones(_fila(vista_con_lote, "AUD-001"))[0].on_click(evento)
    _componente(pagina.dialogos[-1]).boton_todos.on_click(evento)

    texto = " ".join(_textos(pagina.dialogos[-1]))
    assert "Corto AUD-001" in texto
    assert "Corto AUD-003" in texto


def test_el_item_elegido_es_el_que_se_acciona(vista_con_lote, evento, pagina):
    _botones(_fila(vista_con_lote, "AUD-001"))[2].on_click(evento)  # editar
    _componente(pagina.dialogos[-1]).boton_todos.on_click(evento)

    _componente(pagina.dialogos[-1]).opciones[1].on_click(evento)

    assert vista_con_lote._vista_inventario_auxiliar._editing_codigo == "AUD-003"


def test_la_tecla_con_varios_marcados_pregunta_cual(vista_con_lote, pagina):
    """Por tecla la acción significa "sobre todo lo marcado", y para una acción
    que se hace de a uno eso es preguntar cuál."""
    _pulsar(vista_con_lote, pagina, "F5")

    assert isinstance(_componente(pagina.dialogos[-1]), DialogoElegirItem)


def test_la_tecla_con_un_solo_marcado_acciona_directo(vista, pagina, evento):
    vista.seleccionar_item_auditoria("AUD-002", evento)

    _pulsar(vista, pagina, "F5")

    assert vista._vista_inventario_auxiliar._editing_codigo == "AUD-002"
    assert not any(isinstance(_componente(d), DialogoElegirItem) for d in pagina.dialogos)


# ─────────────────────────────────────────────────────────────────────────────
# Contactar proveedor sí tiene sentido en lote
# ─────────────────────────────────────────────────────────────────────────────
def test_contactar_proveedor_en_lote_no_repite_proveedores(vista, evento, pagina):
    """Tres productos de dos proveedores dan DOS bloques: reponer no se hace
    producto por producto sino llamada por llamada."""
    vista.alternar_modo_seleccion_auditoria(evento)
    for codigo in CODIGOS:
        vista.seleccionar_item_auditoria(codigo, evento)

    assert vista._aplicar_accion_auditoria_a_todos("proveedor", CODIGOS, evento) is True

    texto = " ".join(_textos(pagina.dialogos[-1]))
    assert "Contactar proveedor (2)" in texto
    assert "Acme C.A." in texto
    assert "Globex S.A." in texto


def test_contactar_proveedor_en_lote_no_pregunta_cual_item(vista_con_lote, evento, pagina):
    _botones(_fila(vista_con_lote, "AUD-001"))[3].on_click(evento)  # proveedor

    _componente(pagina.dialogos[-1]).boton_todos.on_click(evento)

    assert not isinstance(_componente(pagina.dialogos[-1]), DialogoElegirItem)
    assert "Contactar proveedor" in " ".join(_textos(pagina.dialogos[-1]))


def test_el_bloque_lista_los_productos_de_ese_proveedor(vista_con_lote, evento, pagina):
    vista_con_lote.seleccionar_item_auditoria("AUD-002", evento)

    vista_con_lote._aplicar_accion_auditoria_a_todos(
        "proveedor", vista_con_lote._seleccion_auditoria.seleccionados, evento,
    )

    texto = " ".join(_textos(pagina.dialogos[-1]))
    assert "Corto AUD-001" in texto
    assert "Corto AUD-002" in texto
    assert "Corto AUD-003" in texto


# ─────────────────────────────────────────────────────────────────────────────
# La pila de diálogos no se descalza
# ─────────────────────────────────────────────────────────────────────────────
def test_la_pregunta_se_cierra_antes_de_abrir_la_siguiente(vista_con_lote, evento, pagina):
    """Si la segunda se apilara sobre la primera sin cerrarla, el usuario
    cerraría el de arriba y volvería a ver la pregunta que ya respondió."""
    _botones(_fila(vista_con_lote, "AUD-001"))[0].on_click(evento)
    alcance = pagina.dialogos[-1]

    _componente(alcance).boton_todos.on_click(evento)

    assert alcance.open is False
    assert alcance not in vista_con_lote._dialogos_inicio
    assert len(vista_con_lote._dialogos_inicio) == 1


def test_una_accion_desconocida_falla_ruidosamente_tambien_en_lote(vista_con_lote):
    with pytest.raises(ValueError):
        vista_con_lote._aplicar_accion_auditoria_a_todos("teletransportar", CODIGOS)


def test_sin_nada_marcado_no_hay_accion_sobre_el_lote(vista):
    assert vista._aplicar_accion_auditoria_a_todos("proveedor", []) is False
