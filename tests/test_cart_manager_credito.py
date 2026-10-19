"""Método de pago "Crédito" y helpers de cobro en `services.cart_manager`.

Lo que se blinda aquí:

- Crédito solo existe en Venta Formal. La deuda por cobrar se registra contra
  la Cédula/RIF de un cliente de la cartera, así que un carrito de mostrador
  con Crédito es un estado imposible: el carrito debe repararse solo al
  cambiar el tipo de venta, no esperar a que falle el cobro.
- El "monto predeterminado" depende del método de pago (dólares vs Bolívares):
  es el valor con el que se auto-rellena la casilla del monto a cobrar y el
  denominador del porcentaje de descuento.
- La suma de costos es el PISO del descuento, y distingue "cuesta cero" de
  "no se sabe cuánto cuesta" (producto sin costo registrado → piso parcial).
"""
import pytest

from services import cart_manager as cm


@pytest.fixture
def sid():
    """ID de sesión aislado (el estado de carritos vive en memoria global)."""
    session_id = "sesion-test-credito"
    cm.limpiar_sesion(session_id)
    yield session_id
    cm.limpiar_sesion(session_id)


def _items(*filas) -> list[dict]:
    """Renglones mínimos de carrito: (codigo, cantidad, subtotal_usd, subtotal_bcv)."""
    return [
        {"codigo": c, "cantidad": cant, "subtotal_usd": s_usd, "subtotal_bcv": s_bcv}
        for c, cant, s_usd, s_bcv in filas
    ]


# ─── El método en el catálogo ────────────────────────────────────────────────

def test_credito_forma_parte_del_catalogo_de_metodos_de_pago():
    assert cm.METODOS_PAGO_CREDITO == ("Credito",)
    assert "Credito" in cm.METODOS_PAGO


def test_credito_cobra_en_dolares_no_en_bolivares():
    assert cm.moneda_de_cobro("Credito") == "USD"
    assert cm.moneda_de_cobro("Pago Móvil") == "BCV"
    assert cm.moneda_de_cobro("Efectivo") == "USD"


# ─── Crédito solo en Venta Formal ────────────────────────────────────────────

def test_credito_se_acepta_en_un_carrito_formal(sid):
    carrito = cm.establecer_metodo_pago(sid, "Credito")
    assert carrito["metodo_pago"] == "Credito"


def test_credito_se_rechaza_en_un_carrito_de_mostrador(sid):
    cm.establecer_tipo_venta(sid, "Informal")

    with pytest.raises(ValueError, match="Venta Formal"):
        cm.establecer_metodo_pago(sid, "Credito")

    assert cm.obtener_carrito_activo(sid)["metodo_pago"] == "Efectivo"


def test_pasar_a_mostrador_con_credito_devuelve_el_metodo_a_efectivo(sid):
    """Regla central: el carrito nunca queda en la combinación inválida
    Mostrador + Crédito, se repara al cambiar el tipo de venta."""
    cm.establecer_metodo_pago(sid, "Credito")

    carrito = cm.establecer_tipo_venta(sid, "Informal")

    assert carrito["tipo_venta"] == "Informal"
    assert carrito["metodo_pago"] == "Efectivo"


def test_pasar_a_mostrador_no_altera_un_metodo_valido(sid):
    cm.establecer_metodo_pago(sid, "Pago Móvil")

    carrito = cm.establecer_tipo_venta(sid, "Informal")

    assert carrito["metodo_pago"] == "Pago Móvil"


# ─── Monto predeterminado por método de pago ─────────────────────────────────

def test_el_monto_predeterminado_en_dolares_suma_los_subtotales_usd():
    items = _items(("A", 2.0, 50.0, 2000.0), ("B", 1.0, 30.0, 1200.0))

    assert cm.calcular_monto_predeterminado(items, "Efectivo") == 80.0
    assert cm.calcular_monto_predeterminado(items, "Credito") == 80.0


def test_el_monto_predeterminado_en_bolivares_suma_los_subtotales_bcv():
    items = _items(("A", 2.0, 50.0, 2000.0), ("B", 1.0, 30.0, 1200.0))

    assert cm.calcular_monto_predeterminado(items, "Transferencia") == 3200.0


def test_el_monto_predeterminado_de_un_carrito_vacio_es_cero():
    assert cm.calcular_monto_predeterminado([], "Efectivo") == 0.0


# ─── Suma de costos (piso del descuento) ─────────────────────────────────────

def test_la_suma_de_costos_multiplica_costo_por_cantidad():
    items = _items(("A", 2.0, 50.0, 0.0), ("B", 3.0, 30.0, 0.0))

    resumen = cm.calcular_suma_costos(items, {"A": 10.0, "B": 5.0})

    assert resumen["suma"] == 35.0
    assert resumen["parcial"] is False
    assert resumen["sin_costo"] == ()


def test_un_producto_sin_costo_registrado_cuenta_cero_y_marca_el_piso_parcial():
    items = _items(("A", 2.0, 50.0, 0.0), ("SIN", 4.0, 30.0, 0.0))

    resumen = cm.calcular_suma_costos(items, {"A": 10.0, "SIN": None})

    assert resumen["suma"] == 20.0
    assert resumen["parcial"] is True
    assert resumen["sin_costo"] == ("SIN",)


def test_la_suma_de_costos_lee_la_base_cuando_no_se_le_inyectan_los_costos(db_temporal):
    from services.inventario_service import crear_producto

    crear_producto(
        codigo="COSTO-01",
        referencia="REF",
        descripcion_general="Producto con costo registrado",
        departamento="Pruebas",
        precio_dolares=100.0,
        costo_usd_efectivo=42.0,
        rol_usuario="administrador",
    )

    resumen = cm.calcular_suma_costos(_items(("COSTO-01", 3.0, 300.0, 0.0)))

    assert resumen["suma"] == 126.0
    assert resumen["parcial"] is False
