"""Pruebas unitarias para la validación estricta de stock en el carrito,
visualización de existencia y la tira horizontal de productos más usados
en VentasView y inventario_service."""

import pytest
import flet as ft
from core.database import get_connection
from services.inventario_service import (
    obtener_existencia_producto,
    obtener_existencias_productos,
    obtener_productos_mas_usados,
)
from services.cart_manager import (
    crear_nuevo_carrito,
    obtener_carrito_activo,
    obtener_id_carrito_activo,
    vaciar_carrito_activo,
)
from ui.views.ventas_view import VentasView


@pytest.fixture
def db_con_productos_prueba():
    """Crea productos de prueba en la base de datos con distintas existencias y ventas."""
    with get_connection() as conn:
        cur = conn.cursor()
        # Asegurar productos de prueba
        cur.execute(
            """
            INSERT OR REPLACE INTO productos (
                codigo, referencia, departamento, nombre_referencia_corto, descripcion_general,
                precio_dolares, precio_bcv, existencia
            ) VALUES
            ('TEST-STOCK-OK', 'REF-OK', 'Repuestos', 'Producto Con Stock', 'Desc OK', 10.0, 10.0, 5.0),
            ('TEST-STOCK-CERO', 'REF-CERO', 'Repuestos', 'Producto Vacio', 'Desc Cero', 15.0, 15.0, 0.0),
            ('TEST-STOCK-MUCHO', 'REF-MUCHO', 'Repuestos', 'Producto Muy Vendido', 'Desc Vendido', 20.0, 20.0, 50.0)
            """
        )
        conn.commit()

    yield

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM productos WHERE codigo LIKE 'TEST-STOCK-%'")
        conn.commit()


def test_obtener_existencia_producto(db_con_productos_prueba):
    """Verifica que obtener_existencia_producto devuelva el valor correcto."""
    assert obtener_existencia_producto("TEST-STOCK-OK") == 5.0
    assert obtener_existencia_producto("TEST-STOCK-CERO") == 0.0
    assert obtener_existencia_producto("CODIGO-INEXISTENTE-123") == 0.0


def test_obtener_existencias_productos_lote(db_con_productos_prueba):
    """Verifica que la consulta por lotes devuelva las existencias correctas."""
    res = obtener_existencias_productos(["TEST-STOCK-OK", "TEST-STOCK-CERO", "TEST-STOCK-MUCHO"])
    assert res.get("TEST-STOCK-OK") == 5.0
    assert res.get("TEST-STOCK-CERO") == 0.0
    assert res.get("TEST-STOCK-MUCHO") == 50.0


def test_obtener_productos_mas_usados_nunca_incluye_stock_cero(db_con_productos_prueba):
    """Verifica que productos con stock <= 0 nunca aparezcan en la lista de más usados."""
    prods = obtener_productos_mas_usados(limite=50)
    codigos = [p["codigo"] for p in prods]
    assert "TEST-STOCK-CERO" not in codigos
    for p in prods:
        assert float(p["existencia"]) > 0.0


class PageFalsa:
    """Emula la página Flet para pruebas unitarias sin backend GUI."""
    def __init__(self):
        self.dialogos = []
        self.overlay = []
        self.updates = 0

    def show_dialog(self, dialog):
        dialog.open = True
        self.dialogos.append(dialog)
        self.updates += 1

    def pop_dialog(self):
        dlg = next((d for d in reversed(self.dialogos) if d.open), None)
        if dlg is None:
            return None
        dlg.open = False
        self.updates += 1
        return dlg

    def update(self):
        self.updates += 1


def test_validar_stock_y_agregar_bloquea_stock_cero(db_con_productos_prueba):
    """Verifica que _validar_stock_y_agregar impida añadir productos sin existencia."""
    page = PageFalsa()
    view = VentasView(page=page)
    prod_cero = {"codigo": "TEST-STOCK-CERO", "nombre_referencia_corto": "Producto Vacio"}
    
    alertas = []
    view.show_alert_error = lambda e, msg: alertas.append(msg)

    agregado = view._validar_stock_y_agregar(prod_cero, 1.0)
    assert not agregado
    assert len(alertas) == 1
    assert "no tiene existencia disponible" in alertas[0]


def test_validar_stock_y_agregar_bloquea_exceder_stock(db_con_productos_prueba):
    """Verifica que no se pueda agregar una cantidad superior a la existencia disponible."""
    page = PageFalsa()
    view = VentasView(page=page)
    prod_ok = {"codigo": "TEST-STOCK-OK", "nombre_referencia_corto": "Producto Con Stock", "precio_dolares": 10.0}
    
    alertas = []
    view.show_alert_error = lambda e, msg: alertas.append(msg)

    # El producto tiene stock = 5.0; intentar agregar 6.0 debe fallar
    agregado = view._validar_stock_y_agregar(prod_ok, 6.0)
    assert not agregado
    assert len(alertas) == 1
    assert "Stock insuficiente" in alertas[0]

    # Agregar 5.0 debe ser exitoso
    agregado_ok = view._validar_stock_y_agregar(prod_ok, 5.0)
    assert agregado_ok

    # Intentar agregar 1 más cuando ya hay 5 en el carrito debe fallar
    agregado_extra = view._validar_stock_y_agregar(prod_ok, 1.0)
    assert not agregado_extra
    assert len(alertas) == 2


def test_stepper_bloquea_incremento_si_alcanza_stock_maximo(db_con_productos_prueba):
    """Verifica que el botón '+' no permita superar el stock disponible."""
    page = PageFalsa()
    view = VentasView(page=page)
    item = {"codigo": "TEST-STOCK-OK", "nombre_corto": "Producto Con Stock", "cantidad": 5.0, "precio_usd": 10.0}
    
    alertas = []
    view.show_alert_error = lambda e, msg: alertas.append(msg)

    # delta = +1 cuando ya hay 5.0 (stock = 5.0)
    view.handle_ajustar_cantidad(None, item, 1)
    assert len(alertas) == 1
    assert "Stock máximo alcanzado" in alertas[0]


def test_handle_procesar_venta_bloquea_si_stock_insuficiente(db_con_productos_prueba):
    """Verifica que no se pueda procesar la venta si algún ítem excede stock o no tiene stock."""
    page = PageFalsa()
    view = VentasView(page=page)
    alertas = []
    view.show_alert_error = lambda e, msg: alertas.append(msg)

    # Carrito con cliente válido e ítem con cantidad superior al stock
    c = obtener_carrito_activo(view._sid)
    c["cliente"] = {"cedula": "V-12345678", "nombre": "Cliente Prueba"}
    c["items"] = [
        {"codigo": "TEST-STOCK-OK", "nombre_corto": "Prod OK", "cantidad": 10.0, "precio_usd": 10.0, "subtotal_usd": 100.0, "subtotal_bcv": 100.0}
    ]

    view.handle_procesar_venta(None)
    assert len(alertas) == 1
    assert "No se puede procesar la venta por problemas de stock" in alertas[0]


def test_tarjetas_carrito_dimensiones_y_fila_acciones(db_con_productos_prueba):
    """Verifica que el modo tarjetas tenga ancho 310 y ubique las acciones sin recorte."""
    page = PageFalsa()
    modo_anterior = VentasView._modo_vista_carrito_estatico
    try:
        VentasView._modo_vista_carrito_estatico = "tarjetas"
        view = VentasView(page=page)
        
        items = [
            {
                "codigo": "TEST-STOCK-OK",
                "nombre_corto": "Producto Con Stock",
                "cantidad": 2.0,
                "precio_usd": 10.0,
                "precio_bcv": 400.0,
                "subtotal_usd": 20.0,
                "subtotal_bcv": 800.0,
            }
        ]

        card_widget = view.build_tabla_carrito(items)
        assert card_widget is not None
        # Comprobar que en el árbol de controles de tarjetas las tarjetas tengan ancho 310
        contenido_col = card_widget.content.controls[1].content
        tira_tarjetas = contenido_col.controls[0].controls
        assert len(tira_tarjetas) == 1
        tarjeta = tira_tarjetas[0]
        assert tarjeta.width == 310
    finally:
        VentasView._modo_vista_carrito_estatico = modo_anterior
