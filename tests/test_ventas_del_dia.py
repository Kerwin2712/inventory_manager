"""Listado "Ventas Diarias" del área de Inicio (especificación 17/10/2026).

Las ventas se insertan con SQL directo y `fecha` EXPLÍCITA en vez de usar
`procesar_venta`: el servicio deja que SQLite ponga el `CURRENT_TIMESTAMP` y
estos casos necesitan fijar el instante exacto de cada venta (hoy temprano,
hoy tarde, ayer) para poder afirmar algo sobre el orden y sobre el recorte del
día. La `fecha` se escribe en hora LOCAL porque ese es el criterio con el que
`obtener_ventas_del_dia` compara el "hoy" (el mismo que la tarjeta "Ventas del
Día" del Dashboard).
"""
from datetime import datetime, timedelta

import pytest

from core.database import get_connection
from services.inventario_service import crear_producto
from services.reportes_service import obtener_ventas_del_dia

FORMATO_SQLITE = "%Y-%m-%d %H:%M:%S"


def _crear_producto(codigo: str, nombre_corto: str) -> dict:
    return crear_producto(
        codigo=codigo,
        referencia=f"REF-{codigo}",
        descripcion_general=f"Descripción general extensa del producto {codigo}",
        departamento="Ferretería",
        precio_dolares=10.0,
        precio_bcv=11.0,
        existencia=100.0,
        nombre_referencia_corto=nombre_corto,
        costo_usd_efectivo=6.0,
        rol_usuario="administrador",
    )


def _registrar_venta(
    fecha: datetime,
    lineas: list[tuple[str, float]],
    metodo_pago: str = "Efectivo",
    referencia_pago=None,
    monto_cobrado=None,
    total_usd: float = 0.0,
    total_bcv: float = 0.0,
) -> int:
    """Inserta una venta con su detalle y devuelve su id."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO ventas (
                tipo_venta, cliente_id, total_usd, total_bcv,
                metodo_pago, fecha, referencia_pago, monto_cobrado
            ) VALUES ('Informal', NULL, ?, ?, ?, ?, ?, ?)
            """,
            (
                total_usd, total_bcv, metodo_pago,
                fecha.strftime(FORMATO_SQLITE), referencia_pago, monto_cobrado,
            ),
        )
        venta_id = cursor.lastrowid
        for codigo, cantidad in lineas:
            cursor.execute(
                """
                INSERT INTO ventas_detalle (
                    venta_id, producto_codigo, cantidad,
                    precio_unitario_usd, precio_unitario_bcv,
                    subtotal_usd, subtotal_bcv
                ) VALUES (?, ?, ?, 10.0, 11.0, ?, ?)
                """,
                (venta_id, codigo, cantidad, 10.0 * cantidad, 11.0 * cantidad),
            )
    return venta_id


@pytest.fixture
def productos(db_temporal):
    """Tres productos con nombre corto reconocible para afirmar sobre la
    concatenación de descripciones."""
    _crear_producto("P1", "Tornillo 1/4")
    _crear_producto("P2", "Tuerca 1/4")
    _crear_producto("P3", "Arandela 1/4")
    return None


def _hoy_a_las(hora: int, minuto: int = 0) -> datetime:
    """Instante de HOY en hora local. Se parte del mediodía para que ningún
    caso quede cerca de la medianoche y el test no dependa de la hora en que
    se ejecute la suite."""
    return datetime.now().replace(hour=hora, minute=minuto, second=0, microsecond=0)


def test_venta_de_un_solo_articulo_expone_las_casillas_de_la_lista(productos):
    _registrar_venta(_hoy_a_las(12), [("P1", 3.0)], total_usd=30.0, monto_cobrado=30.0)

    ventas = obtener_ventas_del_dia()

    assert len(ventas) == 1
    venta = ventas[0]
    assert venta["descripcion_corta"] == "Tornillo 1/4"
    assert venta["cantidad_articulos"] == 3.0
    assert venta["total_lineas"] == 1
    assert venta["metodo_pago"] == "Efectivo"
    assert venta["monto_total"] == 30.0
    assert venta["moneda"] == "USD"
    # `dd/mm/aaaa hh:mm`: la vista lo pinta tal cual.
    assert venta["fecha_hora"] == _hoy_a_las(12).strftime("%d/%m/%Y %H:%M")


def test_venta_de_varios_articulos_concatena_los_nombres_cortos_con_coma(productos):
    _registrar_venta(
        _hoy_a_las(12),
        [("P1", 2.0), ("P2", 1.0), ("P3", 4.0)],
        total_usd=70.0,
        monto_cobrado=70.0,
    )

    venta = obtener_ventas_del_dia()[0]

    assert venta["descripcion_corta"] == "Tornillo 1/4, Tuerca 1/4, Arandela 1/4"
    # "Cantidad de Artículos" son las unidades del carrito completo, no los renglones.
    assert venta["cantidad_articulos"] == 7.0
    assert venta["total_lineas"] == 3


def test_las_ventas_se_ordenan_de_la_mas_reciente_a_la_mas_vieja(productos):
    _registrar_venta(_hoy_a_las(9), [("P1", 1.0)], total_usd=10.0)
    _registrar_venta(_hoy_a_las(17), [("P2", 1.0)], total_usd=10.0)
    _registrar_venta(_hoy_a_las(13), [("P3", 1.0)], total_usd=10.0)

    descripciones = [v["descripcion_corta"] for v in obtener_ventas_del_dia()]

    assert descripciones == ["Tuerca 1/4", "Arandela 1/4", "Tornillo 1/4"]


def test_las_ventas_de_ayer_quedan_fuera_del_listado(productos):
    _registrar_venta(_hoy_a_las(12) - timedelta(days=1), [("P1", 5.0)], total_usd=50.0)
    _registrar_venta(_hoy_a_las(12), [("P2", 1.0)], total_usd=10.0)

    ventas = obtener_ventas_del_dia()

    assert len(ventas) == 1
    assert ventas[0]["descripcion_corta"] == "Tuerca 1/4"


def test_la_referencia_de_pago_solo_viaja_en_metodos_distintos_de_efectivo(productos):
    """En Efectivo no hay comprobante que mostrar, así que la casilla va vacía
    aunque la columna traiga texto (ventas migradas o editadas a mano)."""
    _registrar_venta(
        _hoy_a_las(16), [("P1", 1.0)],
        metodo_pago="Pago Móvil", referencia_pago="0412987654",
        total_bcv=11.0, monto_cobrado=1100.0,
    )
    _registrar_venta(
        _hoy_a_las(10), [("P2", 1.0)],
        metodo_pago="Efectivo", referencia_pago="NO-DEBERIA-VERSE",
        total_usd=10.0, monto_cobrado=10.0,
    )

    movil, efectivo = obtener_ventas_del_dia()

    assert movil["metodo_pago"] == "Pago Móvil"
    assert movil["referencia_pago"] == "0412987654"
    # Pago Móvil se cobra en bolívares: el monto sale de `monto_cobrado` en Bs.
    assert movil["moneda"] == "Bs"
    assert movil["monto_total"] == 1100.0
    assert efectivo["referencia_pago"] == ""


def test_monto_cobrado_nulo_cae_al_total_de_la_moneda_del_metodo(productos):
    """Las ventas anteriores a la actualización de octubre 2026 no tienen
    `monto_cobrado`: el listado debe mostrar el total a precio de lista de la
    moneda en que se cobró, no cero ni un error."""
    _registrar_venta(
        _hoy_a_las(15), [("P1", 2.0)],
        metodo_pago="Transferencia", monto_cobrado=None,
        total_usd=20.0, total_bcv=22.0,
    )
    _registrar_venta(
        _hoy_a_las(11), [("P2", 2.0)],
        metodo_pago="Efectivo", monto_cobrado=None,
        total_usd=20.0, total_bcv=22.0,
    )

    transferencia, efectivo = obtener_ventas_del_dia()

    assert transferencia["moneda"] == "Bs"
    assert transferencia["monto_total"] == 22.0
    assert efectivo["moneda"] == "USD"
    assert efectivo["monto_total"] == 20.0


def test_sin_ventas_hoy_el_listado_viene_vacio(productos):
    _registrar_venta(_hoy_a_las(12) - timedelta(days=3), [("P1", 1.0)], total_usd=10.0)

    assert obtener_ventas_del_dia() == []
