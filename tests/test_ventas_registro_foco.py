"""Registro de foco de la vista de Ventas (`ui/views/ventas_view.py`).

Las flechas navegan SOLO cuando ningún campo de texto tiene el cursor: si el
usuario está escribiendo, las flechas mueven el cursor como en cualquier
programa. Flet no expone un "¿quién tiene el foco?" global, así que el foco se
lleva a mano: cada campo avisa al tomarlo y al soltarlo.

De ahí que esto se pruebe recorriendo la vista ENTERA y no campo por campo: el
modo en que esta regla se rompe no es con un error, es con un `ft.TextField`
nuevo que alguien agrega sin enlazar. Ese campo le desplaza la pantalla al
usuario justo mientras escribe en él, y nada en la pantalla explica por qué.

Se cubre también la contracara: un campo que desaparece con su diálogo sin
entregar el `on_blur` dejaría el registro creyendo para siempre que hay algo
enfocado, y las flechas no volverían a navegar nunca.
"""
import flet as ft
import pytest

from services.bcv_service import actualizar_tasa
from services.cart_manager import (
    establecer_metodo_pago,
    establecer_tipo_venta,
    limpiar_sesion,
    vincular_cliente_a_carrito,
)
from services.cartera_service import crear_cliente, obtener_cliente
from services.inventario_service import crear_producto
from tests.test_ventas_marcador_carrito import (
    EventoFalso,
    PageFalsa,
    _descendientes,
)
from ui.views.ventas_view import VentasView


@pytest.fixture
def pagina():
    return PageFalsa()


@pytest.fixture
def evento(pagina):
    return EventoFalso(pagina)


@pytest.fixture
def vista(db_temporal, pagina):
    actualizar_tasa(40.0)
    crear_producto(
        codigo="FOC-001", referencia="REF-FOC",
        descripcion_general="Articulo para el registro de foco",
        departamento="Pruebas", marca="ACME",
        precio_dolares=100.0, precio_bcv=110.0, existencia=10.0,
        nombre_referencia_corto="Art Foco", costo_usd_efectivo=40.0,
        rol_usuario="administrador",
    )
    crear_cliente(nombre="Cliente Foco", cedula_rif="V-44444444",
                  telefono="0412-1111111", direccion="Calle Foco")

    v = VentasView(page=pagina, user_data={"username": "vendedor", "role": "administrador"})
    v.get_body()
    limpiar_sesion(v._sid)
    v.agregar_producto_directo(
        {"codigo": "FOC-001", "precio_dolares": 100.0, "precio_bcv": 110.0,
         "nombre_referencia_corto": "Art Foco"},
        1.0, None,
    )
    yield v
    limpiar_sesion(v._sid)


def _campos(control) -> list[ft.TextField]:
    return [c for c in _descendientes(control) if isinstance(c, ft.TextField)]


def _sin_enlazar(control) -> list[str]:
    """Etiquetas de los campos de texto a los que les falta el enlace."""
    return [
        campo.label or "(sin etiqueta)"
        for campo in _campos(control)
        if campo.on_focus is None or campo.on_blur is None
    ]


# ─── 1. El cuerpo de la vista ────────────────────────────────────────────────

def test_todos_los_campos_del_cuerpo_de_la_vista_estan_enlazados(vista):
    assert _sin_enlazar(vista.get_body()) == []


@pytest.mark.parametrize(
    "atributo",
    ["prod_search_input", "cant_input", "cli_search_numero"],
)
def test_los_campos_de_la_barra_avisan_al_tomar_y_al_soltar_el_foco(vista, atributo):
    campo = getattr(vista, atributo)

    campo.on_focus(None)
    assert vista._registro_foco.hay_campo_con_foco is True

    campo.on_blur(None)
    assert vista._registro_foco.hay_campo_con_foco is False


def test_dos_campos_a_la_vez_no_se_pisan_la_entrada_del_registro(vista):
    """Al pasar de un campo a otro Flet puede entregar el `on_focus` del nuevo
    antes que el `on_blur` del anterior: con el orden cruzado el registro
    seguiría sabiendo que el cursor está dentro de un campo."""
    vista.prod_search_input.on_focus(None)
    vista.cant_input.on_focus(None)
    vista.prod_search_input.on_blur(None)

    assert vista._registro_foco.hay_campo_con_foco is True

    vista.cant_input.on_blur(None)
    assert vista._registro_foco.hay_campo_con_foco is False


# ─── 2. Los campos de cada diálogo ───────────────────────────────────────────

def test_el_dialogo_de_cobro_tiene_sus_tres_campos_enlazados(vista, evento):
    establecer_tipo_venta(vista._sid, "Informal")
    establecer_metodo_pago(vista._sid, "Transferencia")

    vista.abrir_dialogo_cobro(evento)

    assert _sin_enlazar(vista._dlg_cobro.content) == []
    assert len(_campos(vista._dlg_cobro.content)) == 3


def test_la_ventana_de_credito_tiene_sus_cinco_campos_enlazados(vista, evento):
    establecer_tipo_venta(vista._sid, "Formal")
    vincular_cliente_a_carrito(vista._sid, obtener_cliente("V-44444444"))

    vista.abrir_ventana_credito(evento)

    assert _sin_enlazar(vista._dlg_credito.content) == []
    assert len(_campos(vista._dlg_credito.content)) == 5


def test_el_dialogo_de_editar_renglon_tiene_sus_campos_enlazados(vista, evento):
    vista.ejecutar_accion_item("editar", "FOC-001", evento)

    assert _sin_enlazar(vista._dlg_editar_item.content) == []
    assert len(_campos(vista._dlg_editar_item.content)) == 3


def test_el_dialogo_de_alta_de_cliente_tiene_sus_campos_enlazados(vista, evento):
    vista.abrir_modal_crear_cliente("V-99999999", evento)

    dlg = evento.page.overlay[-1]
    assert _sin_enlazar(dlg.content) == []


def test_el_modal_de_busqueda_en_inventario_tiene_sus_campos_enlazados(vista, evento):
    vista.abrir_modal_buscar_inventario(evento)

    dlg = evento.page.overlay[-1]
    assert _sin_enlazar(dlg.content) == []


def test_el_panel_de_resultados_no_introduce_campos_sin_enlazar(vista):
    vista.prod_search_input.value = "Articulo"
    vista.prod_search_input.on_submit(None)

    assert _sin_enlazar(vista.panel_resultados_container) == []


# ─── 3. Al cerrar un diálogo el foco se libera ───────────────────────────────

def test_cerrar_un_dialogo_libera_el_foco_de_sus_campos(vista, evento):
    """No se puede contar con el `on_blur` de un campo que desaparece de la
    pantalla: sin esto las flechas no volverían a navegar nunca."""
    vista.ejecutar_accion_item("editar", "FOC-001", evento)
    _campos(vista._dlg_editar_item.content)[0].on_focus(None)
    assert vista._registro_foco.hay_campo_con_foco is True

    vista._close_dialog(evento, dialog=vista._dlg_editar_item)

    assert vista._registro_foco.hay_campo_con_foco is False


def test_cancelar_el_cobro_libera_el_foco(vista, evento):
    establecer_tipo_venta(vista._sid, "Informal")
    vista.abrir_dialogo_cobro(evento)
    vista.txt_descuento.on_focus(None)

    vista._cancelar_cobro(evento)

    assert vista._registro_foco.hay_campo_con_foco is False
