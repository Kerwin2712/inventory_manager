"""Cobro de la venta en `services.ventas_service`: referencia, descuento y crédito.

Reglas de negocio blindadas aquí (actualización de octubre 2026):

- `total_usd`/`total_bcv` son la suma a precio de LISTA (el "predeterminado");
  `monto_cobrado` es lo realmente cobrado y `porcentaje_descuento` la
  diferencia con signo. Son columnas distintas a propósito: perder el precio
  de lista haría imposible auditar el descuento después.
- El piso del descuento es la suma de costos del carrito, y se valida igual
  para todos los roles — pero el mensaje de rechazo solo nombra el costo a
  quien puede verlo (`services/permisos_service`).
- A crédito el descuento tope es -5%, y la venta a crédito nunca queda sin su
  deuda por cobrar asociada.
"""
import pytest

from services import deudas_service
from services.cartera_service import crear_cliente
from services.inventario_service import crear_producto
from services.ventas_service import (
    calcular_porcentaje_descuento,
    formatear_porcentaje_descuento,
    procesar_venta,
)


@pytest.fixture
def catalogo(db_temporal):
    """Un cliente y dos productos con costo conocido.

    Precios de lista: AAA $100 (costo $60), BBB $50 (costo $20).
    Carrito típico de estos tests: 1xAAA + 1xBBB = $150 de lista, $80 de costo.
    """
    crear_cliente(nombre="Cliente Credito", cedula_rif="V-11111111", telefono="0414-1112233",
                  direccion="Av. Principal", correo="cliente@ejemplo.com")
    crear_producto(
        codigo="AAA", referencia="REF-A", descripcion_general="Producto A",
        departamento="Pruebas", precio_dolares=100.0, precio_bcv=110.0,
        existencia=20.0, costo_usd_efectivo=60.0, rol_usuario="administrador",
    )
    crear_producto(
        codigo="BBB", referencia="REF-B", descripcion_general="Producto B",
        departamento="Pruebas", precio_dolares=50.0, precio_bcv=55.0,
        existencia=20.0, costo_usd_efectivo=20.0, rol_usuario="administrador",
    )
    return db_temporal


def _lineas(*filas) -> list[dict]:
    """(codigo, cantidad, precio_usd, precio_bcv_bolivares)."""
    return [
        {
            "producto_codigo": codigo,
            "nombre_corto": f"Corto {codigo}",
            "cantidad": cantidad,
            "precio_unitario_usd": precio_usd,
            "precio_unitario_bcv": precio_bs,
            "subtotal_usd": cantidad * precio_usd,
            "subtotal_bcv": cantidad * precio_bs,
        }
        for codigo, cantidad, precio_usd, precio_bs in filas
    ]


def _carrito_estandar() -> list[dict]:
    return _lineas(("AAA", 1.0, 100.0, 4000.0), ("BBB", 1.0, 50.0, 2000.0))


def _fila_venta(venta_id: int) -> dict:
    from core.database import get_connection

    with get_connection() as conn:
        fila = conn.execute("SELECT * FROM ventas WHERE id = ?", (venta_id,)).fetchone()
    return {clave: fila[clave] for clave in fila.keys()}


# ─── 1. Porcentaje de descuento: fórmula y formato ───────────────────────────

def test_el_porcentaje_es_negativo_cuando_se_cobra_por_debajo_de_la_lista():
    assert calcular_porcentaje_descuento(53.0, 80.0) == -33.75


def test_el_porcentaje_es_positivo_cuando_se_cobra_por_encima_de_la_lista():
    assert calcular_porcentaje_descuento(111.23, 100.0) == 11.23


def test_el_porcentaje_negativo_se_muestra_con_signo_coma_y_sufijo_off():
    assert formatear_porcentaje_descuento(-33.75) == "-33,75% OFF"


def test_el_porcentaje_positivo_se_muestra_con_signo_coma_y_sufijo_on():
    assert formatear_porcentaje_descuento(11.23) == "+11,23% ON"


def test_sin_precio_de_lista_no_se_divide_por_cero():
    assert calcular_porcentaje_descuento(50.0, 0.0) == 0.0


# ─── 2. Piso de costo del descuento ──────────────────────────────────────────

def test_un_monto_por_encima_de_la_suma_de_costos_se_acepta(catalogo):
    """Costos: $60 + $20 = $80. Cobrar $100 sobre $150 de lista es válido."""
    resultado = procesar_venta(
        tipo_venta="Informal", lineas=_carrito_estandar(), metodo_pago="Efectivo",
        monto_cobrado=100.0,
    )

    assert resultado["monto_cobrado"] == 100.0
    assert resultado["total_usd"] == 150.0
    assert resultado["porcentaje_descuento"] == pytest.approx(-33.33)


def test_un_monto_por_debajo_de_la_suma_de_costos_se_rechaza(catalogo):
    with pytest.raises(ValueError, match="ERR_VENTA_DESCUENTO_PISO"):
        procesar_venta(
            tipo_venta="Informal", lineas=_carrito_estandar(), metodo_pago="Efectivo",
            monto_cobrado=79.99,
        )


def test_un_monto_igual_a_la_suma_de_costos_se_rechaza(catalogo):
    """El piso es ESTRICTO: vender al costo exacto tampoco se permite."""
    with pytest.raises(ValueError, match="ERR_VENTA_DESCUENTO_PISO"):
        procesar_venta(
            tipo_venta="Informal", lineas=_carrito_estandar(), metodo_pago="Efectivo",
            monto_cobrado=80.0,
        )


def test_el_rechazo_del_piso_no_revela_el_costo_a_un_vendedor(catalogo):
    """Fuga de información: el piso se valida igual para todos, pero el monto
    del costo es información reservada a la administración."""
    with pytest.raises(ValueError) as error:
        procesar_venta(
            tipo_venta="Informal", lineas=_carrito_estandar(), metodo_pago="Efectivo",
            monto_cobrado=50.0, rol_usuario="vendedor",
        )

    mensaje = str(error.value)
    assert "consulte con un administrador" in mensaje.lower()
    assert "80" not in mensaje


def test_el_rechazo_del_piso_si_nombra_el_costo_a_un_administrador(catalogo):
    with pytest.raises(ValueError) as error:
        procesar_venta(
            tipo_venta="Informal", lineas=_carrito_estandar(), metodo_pago="Efectivo",
            monto_cobrado=50.0, rol_usuario="administrador",
        )

    assert "80,00" in str(error.value).replace(".", ",")


def test_un_producto_sin_costo_registrado_deja_el_piso_parcial_y_lo_avisa(catalogo):
    """Sin costo registrado el producto cuenta 0: el piso baja, pero el aviso
    evita que el administrador crea que el número es exacto.

    El costo se vacía por SQL porque `crear_producto` ya exige costo cuando
    hay existencia: los productos sin costo son los que venían de antes de esa
    regla (instalaciones migradas), y son justo los que dejan el piso parcial.
    """
    from core.database import get_connection

    crear_producto(
        codigo="CCC", referencia="REF-C", descripcion_general="Producto sin costo",
        departamento="Pruebas", precio_dolares=40.0, precio_bcv=44.0,
        existencia=5.0, costo_usd_efectivo=15.0, rol_usuario="administrador",
    )
    with get_connection() as conn:
        conn.execute("UPDATE productos SET costo_usd_efectivo = NULL WHERE codigo = 'CCC'")
        conn.commit()

    with pytest.raises(ValueError) as error:
        procesar_venta(
            tipo_venta="Informal",
            lineas=_lineas(("AAA", 1.0, 100.0, 4000.0), ("CCC", 1.0, 40.0, 1600.0)),
            metodo_pago="Efectivo", monto_cobrado=59.0, rol_usuario="administrador",
        )

    assert "piso es parcial" in str(error.value)


def test_el_piso_de_un_cobro_en_bolivares_se_compara_en_bolivares(catalogo):
    """El monto en Bs se compara contra el piso llevado a Bs con la misma
    proporción del total de lista: nunca se mezclan monedas."""
    # Lista: Bs 6.000 sobre $150 → el piso de $80 equivale a Bs 3.200.
    with pytest.raises(ValueError, match="ERR_VENTA_DESCUENTO_PISO"):
        procesar_venta(
            tipo_venta="Informal", lineas=_carrito_estandar(), metodo_pago="Transferencia",
            referencia_pago="0001", monto_cobrado=3100.0,
        )

    resultado = procesar_venta(
        tipo_venta="Informal", lineas=_carrito_estandar(), metodo_pago="Transferencia",
        referencia_pago="0001", monto_cobrado=3300.0,
    )
    assert resultado["monto_cobrado"] == 3300.0


# ─── 3. Referencia del pago ──────────────────────────────────────────────────

def test_el_efectivo_no_exige_referencia(catalogo):
    resultado = procesar_venta(
        tipo_venta="Informal", lineas=_carrito_estandar(), metodo_pago="Efectivo",
    )

    assert resultado["referencia_omitida"] is False
    assert _fila_venta(resultado["venta_id"])["referencia_omitida"] == 0


def test_un_metodo_distinto_de_efectivo_exige_referencia(catalogo):
    with pytest.raises(ValueError, match="ERR_VENTA_REFERENCIA"):
        procesar_venta(
            tipo_venta="Informal", lineas=_carrito_estandar(), metodo_pago="Pago Móvil",
        )


def test_la_referencia_escrita_se_persiste(catalogo):
    resultado = procesar_venta(
        tipo_venta="Informal", lineas=_carrito_estandar(), metodo_pago="Pago Móvil",
        referencia_pago="  998877  ",
    )

    fila = _fila_venta(resultado["venta_id"])
    assert fila["referencia_pago"] == "998877"
    assert fila["referencia_omitida"] == 0


def test_la_omision_confirmada_permite_cobrar_y_queda_registrada(catalogo):
    resultado = procesar_venta(
        tipo_venta="Informal", lineas=_carrito_estandar(), metodo_pago="Punto",
        referencia_omitida=True,
    )

    fila = _fila_venta(resultado["venta_id"])
    assert fila["referencia_pago"] is None
    assert fila["referencia_omitida"] == 1


def test_escribir_la_referencia_apaga_la_bandera_de_omision(catalogo):
    """Si el vendedor escribió la referencia, no la omitió: la bandera
    mentiría en el historial."""
    resultado = procesar_venta(
        tipo_venta="Informal", lineas=_carrito_estandar(), metodo_pago="Punto",
        referencia_pago="123", referencia_omitida=True,
    )

    assert _fila_venta(resultado["venta_id"])["referencia_omitida"] == 0


# ─── 4. Persistencia del cobro ───────────────────────────────────────────────

def test_sin_descuento_se_persiste_el_precio_de_lista_y_cero_por_ciento(catalogo):
    resultado = procesar_venta(
        tipo_venta="Informal", lineas=_carrito_estandar(), metodo_pago="Efectivo",
        usuario_nombre="mario",
    )

    fila = _fila_venta(resultado["venta_id"])
    assert fila["total_usd"] == 150.0
    assert fila["monto_cobrado"] == 150.0
    assert fila["porcentaje_descuento"] == 0.0
    assert fila["usuario_nombre"] == "mario"


def test_con_descuento_el_total_de_lista_se_conserva_aparte_del_cobrado(catalogo):
    resultado = procesar_venta(
        tipo_venta="Informal", lineas=_carrito_estandar(), metodo_pago="Efectivo",
        monto_cobrado="99,38", usuario_nombre="vendedora",
    )

    fila = _fila_venta(resultado["venta_id"])
    assert fila["total_usd"] == 150.0, "el precio de lista no se pisa con el cobrado"
    assert fila["monto_cobrado"] == 99.38
    assert fila["porcentaje_descuento"] == pytest.approx(-33.75)
    assert formatear_porcentaje_descuento(fila["porcentaje_descuento"]) == "-33,75% OFF"


def test_un_cobro_por_encima_de_la_lista_persiste_un_porcentaje_positivo(catalogo):
    resultado = procesar_venta(
        tipo_venta="Informal", lineas=_carrito_estandar(), metodo_pago="Efectivo",
        monto_cobrado=180.0,
    )

    assert _fila_venta(resultado["venta_id"])["porcentaje_descuento"] == pytest.approx(20.0)


# ─── 5. Crédito ──────────────────────────────────────────────────────────────

def test_el_credito_se_rechaza_en_venta_mostrador(catalogo):
    with pytest.raises(ValueError, match="ERR_VENTA_CREDITO_TIPO"):
        procesar_venta(
            tipo_venta="Informal", lineas=_carrito_estandar(), metodo_pago="Credito",
            referencia_pago="COMPROMISO-1", fecha_limite_pago="31/12/2026",
        )


def test_el_credito_se_rechaza_sin_cliente_asociado(catalogo):
    """Venta Formal sin cliente: la deuda no tendría contra quién registrarse."""
    with pytest.raises(ValueError, match="cliente"):
        procesar_venta(
            tipo_venta="Formal", cliente_id=None, lineas=_carrito_estandar(),
            metodo_pago="Credito", referencia_pago="COMPROMISO-1",
            fecha_limite_pago="31/12/2026",
        )


def test_el_credito_exige_fecha_limite_de_pago(catalogo):
    with pytest.raises(ValueError, match="ERR_DEUDA_FECHA"):
        procesar_venta(
            tipo_venta="Formal", cliente_id="V-11111111", lineas=_carrito_estandar(),
            metodo_pago="Credito", referencia_pago="COMPROMISO-1",
        )


def test_el_credito_exige_referencia_igual_que_los_demas_metodos(catalogo):
    with pytest.raises(ValueError, match="ERR_VENTA_REFERENCIA"):
        procesar_venta(
            tipo_venta="Formal", cliente_id="V-11111111", lineas=_carrito_estandar(),
            metodo_pago="Credito", fecha_limite_pago="31/12/2026",
        )


def test_el_credito_crea_la_deuda_con_el_monto_y_la_fecha_limite_correctos(catalogo):
    resultado = procesar_venta(
        tipo_venta="Formal", cliente_id="V-11111111", lineas=_carrito_estandar(),
        metodo_pago="Credito", referencia_pago="COMPROMISO-1",
        fecha_limite_pago="31/12/2026", monto_cobrado=145.0, usuario_nombre="mario",
    )

    deuda = deudas_service.obtener_deuda(resultado["deuda_id"])
    assert deuda["venta_id"] == resultado["venta_id"]
    assert deuda["cliente_id"] == "V-11111111"
    assert deuda["monto_total_usd"] == 145.0, "la deuda nace por lo COBRADO, no por la lista"
    assert deuda["saldo_usd"] == 145.0
    assert deuda["fecha_limite_pago"] == "2026-12-31"
    assert deuda["usuario_nombre"] == "mario"
    assert sorted(i["producto_codigo"] for i in deuda["items"]) == ["AAA", "BBB"]
    assert deuda["items_descripcion"] == "Corto AAA, Corto BBB"


def test_el_descuento_a_credito_no_puede_pasar_del_cinco_por_ciento(catalogo):
    """Lista $150 → el mínimo a crédito es $142,50."""
    with pytest.raises(ValueError, match="ERR_VENTA_CREDITO_DESCUENTO"):
        procesar_venta(
            tipo_venta="Formal", cliente_id="V-11111111", lineas=_carrito_estandar(),
            metodo_pago="Credito", referencia_pago="COMPROMISO-1",
            fecha_limite_pago="31/12/2026", monto_cobrado=142.49,
        )


def test_el_descuento_a_credito_acepta_exactamente_el_cinco_por_ciento(catalogo):
    resultado = procesar_venta(
        tipo_venta="Formal", cliente_id="V-11111111", lineas=_carrito_estandar(),
        metodo_pago="Credito", referencia_pago="COMPROMISO-1",
        fecha_limite_pago="31/12/2026", monto_cobrado=142.50,
    )

    assert resultado["porcentaje_descuento"] == pytest.approx(-5.0)


def test_a_credito_si_se_puede_cobrar_por_encima_de_la_lista(catalogo):
    resultado = procesar_venta(
        tipo_venta="Formal", cliente_id="V-11111111", lineas=_carrito_estandar(),
        metodo_pago="Credito", referencia_pago="COMPROMISO-1",
        fecha_limite_pago="31/12/2026", monto_cobrado=200.0,
    )

    assert resultado["porcentaje_descuento"] > 0


def test_si_falla_la_deuda_no_queda_la_venta_a_credito_registrada(catalogo, monkeypatch):
    """Invariante: nunca una venta a crédito sin su deuda. La deuda se crea
    después del COMMIT de la venta (SQLite no admite dos transacciones de
    escritura), así que si falla hay que deshacer la venta y devolver el stock.
    """
    from core.database import get_connection
    import services.ventas_service as ventas_service

    def _explotar(**kwargs):
        raise RuntimeError("falla simulada al registrar la deuda")

    monkeypatch.setattr(ventas_service.deudas_service, "crear_deuda", _explotar)

    with pytest.raises(RuntimeError):
        ventas_service.procesar_venta(
            tipo_venta="Formal", cliente_id="V-11111111", lineas=_carrito_estandar(),
            metodo_pago="Credito", referencia_pago="COMPROMISO-1",
            fecha_limite_pago="31/12/2026",
        )

    with get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM ventas").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM ventas_detalle").fetchone()[0] == 0
        existencias = {
            fila["codigo"]: fila["existencia"]
            for fila in conn.execute("SELECT codigo, existencia FROM productos").fetchall()
        }
    assert existencias["AAA"] == 20.0, "el stock descontado debe volver"
    assert existencias["BBB"] == 20.0
