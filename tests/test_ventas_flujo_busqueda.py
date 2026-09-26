"""Flujo de búsqueda del módulo de Ventas (`ui/views/ventas_view.py`).

Regla de negocio que se blinda aquí: BUSCAR y AGREGAR son responsabilidades
separadas. El Enter del campo de búsqueda (`on_submit`) solo consulta y
renderiza coincidencias en el panel de resultados; el carrito se muta
únicamente al pulsar un botón "Agregar" explícito.

Las vistas Flet de este proyecto se instancian headless (sin `page`): acceder a
`self.page` lanza `RuntimeError`, que `get_current_page`/`safe_update` ya
capturan, así que `get_body()` y los handlers son ejecutables en test.
"""
import copy

import flet as ft
import pytest

from services.bcv_service import actualizar_tasa
from services.busqueda_service import CRITERIOS_BUSQUEDA
from services.cart_manager import limpiar_sesion, obtener_carrito_activo
from services.inventario_service import crear_producto
from ui.views.ventas_view import VentasView

CAMPOS_COSTO = ("costo_usd_efectivo", "costo_usd_bcv")


def _crear(codigo, referencia, descripcion, departamento, marca, corto, barras, existencia=10.0):
    crear_producto(
        codigo=codigo,
        referencia=referencia,
        descripcion_general=descripcion,
        departamento=departamento,
        marca=marca,
        precio_dolares=100.0,
        precio_bcv=110.0,
        existencia=existencia,
        codigo_barras=barras,
        nombre_referencia_corto=corto,
        costo_usd_efectivo=70.0,
        rol_usuario="administrador",
    )


@pytest.fixture
def vista(db_temporal):
    """`VentasView` headless con catálogo sembrado y su `get_body()` ya
    construido (es ahí donde se crean los controles de la barra de búsqueda)."""
    actualizar_tasa(40.0)
    _crear("LAP-001", "REF-LAPTOP", "Laptop empresarial 14 pulgadas", "Tecnologia", "Lenovo", "Laptop 14", "7591111111111")
    _crear("LAP-002", "REF-LAPTOP-PRO", "Laptop profesional 16 pulgadas", "Tecnologia", "Dell", "Laptop 16", "7592222222222")
    _crear("MOU-010", "REF-MOUSE", "Mouse inalambrico ergonomico", "Accesorios", "Logitech", "Mouse Ergo", "7593333333333")
    _crear("AGO-001", "REF-AGOTADO", "Monitor curvo sin existencia", "Tecnologia", "Samsung", "Monitor 27", "7594444444444", existencia=0.0)

    v = VentasView(user_data={"username": "vendedor", "role": "administrador"})
    v.get_body()
    limpiar_sesion(v._sid)  # Carrito virgen: el sid headless es compartido entre tests.
    yield v
    limpiar_sesion(v._sid)


# ─── Utilidades de inspección del árbol de controles ─────────────────────────

def _descendientes(control):
    """Recorre recursivamente el árbol de controles Flet ya construido."""
    if control is None:
        return
    yield control
    hijos = []
    for atributo in ("controls", "content"):
        valor = getattr(control, atributo, None)
        if isinstance(valor, list):
            hijos.extend(valor)
        elif valor is not None and hasattr(valor, "__class__") and not isinstance(valor, (str, int, float, bool)):
            hijos.append(valor)
    for hijo in hijos:
        yield from _descendientes(hijo)


def _textos(control) -> list[str]:
    return [c.value for c in _descendientes(control) if isinstance(c, ft.Text) and c.value]


def _botones_agregar(vista_ventas) -> list[ft.TextButton]:
    """Botones "Agregar" de las filas del panel de resultados, en orden."""
    return [
        c for c in _descendientes(vista_ventas.panel_resultados_container)
        if isinstance(c, ft.TextButton) and "Agregar" in " ".join(_textos(c))
    ]


def _snapshot_carrito(vista_ventas) -> list[dict]:
    return copy.deepcopy(obtener_carrito_activo(vista_ventas._sid)["items"])


# ─── 1. Cableado de la barra de búsqueda ─────────────────────────────────────

def test_el_on_submit_del_campo_apunta_al_handler_de_busqueda_no_al_de_agregar(vista):
    assert vista.prod_search_input.on_submit == vista.handle_buscar_producto
    assert vista.prod_search_input.on_submit != vista.handle_agregar_producto


def test_el_boton_agregar_conserva_el_handler_de_agregar(vista):
    assert vista.btn_agregar_prod.on_click == vista.handle_agregar_producto


def test_las_opciones_del_criterio_replican_el_mapa_del_servicio(vista):
    assert [o.key for o in vista.criterio_busqueda_dd.options] == list(CRITERIOS_BUSQUEDA)
    assert vista.criterio_busqueda_dd.value == "Todos"


def test_el_panel_de_resultados_arranca_oculto_y_vacio(vista):
    assert vista.panel_resultados_container.visible is False
    assert vista.panel_resultados_container.content is None


# ─── 2. El Enter busca y NO muta el carrito (test central) ───────────────────

def test_enter_ejecuta_la_busqueda_y_puebla_el_panel_de_resultados(vista):
    vista.prod_search_input.value = "laptop"
    vista.criterio_busqueda_dd.value = "Todos"

    vista.prod_search_input.on_submit(None)

    assert [p["codigo"] for p in vista._resultados_busqueda] == ["LAP-001", "LAP-002"]
    assert vista.panel_resultados_container.visible is True
    textos = " | ".join(_textos(vista.panel_resultados_container))
    assert "LAP-001" in textos and "LAP-002" in textos
    assert "MOU-010" not in textos


def test_enter_no_muta_el_carrito(vista):
    antes = _snapshot_carrito(vista)
    vista.prod_search_input.value = "laptop"

    vista.prod_search_input.on_submit(None)

    despues = _snapshot_carrito(vista)
    assert len(despues) == len(antes) == 0
    assert despues == antes


def test_enter_con_codigo_exacto_tampoco_agrega_al_carrito(vista):
    antes = _snapshot_carrito(vista)
    vista.prod_search_input.value = "LAP-001"
    vista.criterio_busqueda_dd.value = "Código"

    vista.prod_search_input.on_submit(None)

    despues = _snapshot_carrito(vista)
    assert len(despues) == len(antes) == 0
    assert despues == antes
    assert [p["codigo"] for p in vista._resultados_busqueda] == ["LAP-001"]


def test_enter_con_codigo_de_barras_exacto_destaca_primero_sin_agregar(vista):
    vista.prod_search_input.value = "7592222222222"
    vista.criterio_busqueda_dd.value = "Código"

    vista.prod_search_input.on_submit(None)

    assert vista._resultados_busqueda[0]["codigo"] == "LAP-002"
    assert obtener_carrito_activo(vista._sid)["items"] == []


def test_enter_sobre_un_carrito_con_items_no_altera_sus_renglones(vista):
    vista.agregar_producto_directo({"codigo": "MOU-010", "precio_dolares": 100.0, "precio_bcv": 110.0,
                                    "nombre_referencia_corto": "Mouse Ergo"}, 3.0, None)
    antes = _snapshot_carrito(vista)
    assert len(antes) == 1

    vista.prod_search_input.value = "laptop"
    vista.prod_search_input.on_submit(None)

    assert _snapshot_carrito(vista) == antes


def test_enter_respeta_el_criterio_seleccionado(vista):
    vista.prod_search_input.value = "Tecnologia"
    vista.criterio_busqueda_dd.value = "Departamento"

    vista.prod_search_input.on_submit(None)

    # Orden estable del motor: departamento, luego código.
    assert [p["codigo"] for p in vista._resultados_busqueda] == ["AGO-001", "LAP-001", "LAP-002"]


def test_enter_sin_coincidencias_muestra_el_estado_vacio(vista):
    vista.prod_search_input.value = "zzzz-inexistente"

    vista.prod_search_input.on_submit(None)

    assert vista._resultados_busqueda == []
    assert vista.panel_resultados_container.visible is True
    assert any("No se encontraron productos" in t for t in _textos(vista.panel_resultados_container))


def test_enter_con_termino_vacio_no_abre_el_panel_ni_toca_el_carrito(vista):
    vista.prod_search_input.value = "   "

    vista.prod_search_input.on_submit(None)

    assert vista.panel_resultados_container.visible is False
    assert obtener_carrito_activo(vista._sid)["items"] == []


def test_el_panel_de_resultados_no_expone_costos(vista):
    vista.prod_search_input.value = "laptop"
    vista.prod_search_input.on_submit(None)

    for producto in vista._resultados_busqueda:
        assert not set(producto) & set(CAMPOS_COSTO)
    assert all("70,00" not in t and "70.00" not in t for t in _textos(vista.panel_resultados_container))


# ─── 3. El botón "Agregar" de una fila SÍ agrega ─────────────────────────────

def test_el_boton_agregar_de_una_fila_agrega_ese_producto_al_carrito(vista):
    vista.prod_search_input.value = "laptop"
    vista.prod_search_input.on_submit(None)
    vista.cant_input.value = "2"

    botones = _botones_agregar(vista)
    assert len(botones) == 2
    botones[1].on_click(None)  # LAP-002, la segunda coincidencia

    items = obtener_carrito_activo(vista._sid)["items"]
    assert [i["codigo"] for i in items] == ["LAP-002"]
    assert items[0]["cantidad"] == 2.0
    assert vista.cant_input.value == "1"


def test_el_boton_agregar_de_una_fila_sin_stock_esta_deshabilitado(vista):
    vista.prod_search_input.value = "AGO-001"
    vista.criterio_busqueda_dd.value = "Código"
    vista.prod_search_input.on_submit(None)

    botones = _botones_agregar(vista)
    assert len(botones) == 1
    assert botones[0].disabled is True


def test_el_boton_agregar_de_una_fila_respeta_el_stock_disponible(vista):
    vista.prod_search_input.value = "MOU-010"
    vista.criterio_busqueda_dd.value = "Código"
    vista.prod_search_input.on_submit(None)
    vista.cant_input.value = "99"

    _botones_agregar(vista)[0].on_click(None)

    assert obtener_carrito_activo(vista._sid)["items"] == []


def test_el_boton_agregar_de_una_fila_rechaza_cantidad_invalida(vista):
    vista.prod_search_input.value = "MOU-010"
    vista.criterio_busqueda_dd.value = "Código"
    vista.prod_search_input.on_submit(None)
    vista.cant_input.value = "0"

    _botones_agregar(vista)[0].on_click(None)

    assert obtener_carrito_activo(vista._sid)["items"] == []


# ─── 4. El botón "Agregar" de la barra ya no adivina ─────────────────────────

def test_el_boton_agregar_de_la_barra_agrega_ante_coincidencia_exacta(vista):
    vista.prod_search_input.value = "LAP-001"
    vista.criterio_busqueda_dd.value = "Código"

    vista.btn_agregar_prod.on_click(None)

    assert [i["codigo"] for i in obtener_carrito_activo(vista._sid)["items"]] == ["LAP-001"]
    assert vista.prod_search_input.value == ""
    assert vista.panel_resultados_container.visible is False


def test_el_boton_agregar_de_la_barra_agrega_cuando_hay_una_sola_coincidencia(vista):
    vista.prod_search_input.value = "ergonomico"

    vista.btn_agregar_prod.on_click(None)

    assert [i["codigo"] for i in obtener_carrito_activo(vista._sid)["items"]] == ["MOU-010"]


def test_el_boton_agregar_de_la_barra_no_adivina_con_varias_coincidencias(vista):
    """Antes tomaba `prods[0]` a ciegas; ahora muestra las opciones y espera."""
    vista.prod_search_input.value = "laptop"

    vista.btn_agregar_prod.on_click(None)

    assert obtener_carrito_activo(vista._sid)["items"] == []
    assert vista.panel_resultados_container.visible is True
    assert [p["codigo"] for p in vista._resultados_busqueda] == ["LAP-001", "LAP-002"]


def test_el_boton_agregar_de_la_barra_usa_el_criterio_seleccionado(vista):
    """Con criterio Marca, "Logitech" resuelve a un único producto aunque ese
    término no exista en ninguna otra columna."""
    vista.prod_search_input.value = "Logitech"
    vista.criterio_busqueda_dd.value = "Marca"

    vista.btn_agregar_prod.on_click(None)

    assert [i["codigo"] for i in obtener_carrito_activo(vista._sid)["items"]] == ["MOU-010"]
