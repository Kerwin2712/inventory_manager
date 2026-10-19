"""Coherencia horaria de `ventas.fecha`.

El DEFAULT `CURRENT_TIMESTAMP` de SQLite guarda UTC, mientras que los reportes
preguntan por el día en curso con `DATE('now','localtime')`. En Venezuela
(UTC-4) una venta hecha después de las 20:00 locales quedaba con la fecha UTC
del día siguiente y desaparecía de "Ventas del Día", del Top de Inteligencia
de Negocio y de la lista de Ventas Diarias. Es el mismo bug que ya se corrigió
para `productos.created_at` (ver `tests/test_created_at_hora_local.py`).
"""
from datetime import datetime, timedelta

import pytest

from core.database import get_connection
from services.inventario_service import crear_producto
from services.ventas_service import (
    CLAVE_MIGRACION_FECHA_VENTAS,
    migrar_fechas_ventas_a_hora_local,
    procesar_venta,
)


def _desfase_utc_local() -> timedelta:
    """Diferencia entre la hora local del equipo y UTC (0 si corre en UTC)."""
    return datetime.now() - datetime.utcnow()


@pytest.fixture
def producto(db_temporal):
    crear_producto(
        codigo="HORA-VENTA",
        referencia="REF-HORA",
        descripcion_general="Producto para verificar la hora de la venta",
        departamento="Pruebas",
        precio_dolares=10.0,
        existencia=50.0,
        costo_usd_efectivo=4.0,
        rol_usuario="administrador",
    )
    return "HORA-VENTA"


def _vender() -> int:
    resultado = procesar_venta(
        tipo_venta="Informal",
        lineas=[{"producto_codigo": "HORA-VENTA", "cantidad": 1.0}],
        metodo_pago="Efectivo",
    )
    return resultado["venta_id"]


def _fecha(venta_id: int) -> str:
    with get_connection() as conn:
        return conn.execute("SELECT fecha FROM ventas WHERE id = ?", (venta_id,)).fetchone()["fecha"]


def _limpiar_marca_migracion() -> None:
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM app_settings WHERE key = ?", (CLAVE_MIGRACION_FECHA_VENTAS,)
        )
        conn.commit()


def _insertar_venta_heredada(codigo_fecha: str = "CURRENT_TIMESTAMP") -> int:
    """Simula una venta vieja escrita con el DEFAULT de SQLite (UTC)."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"""
            INSERT INTO ventas (tipo_venta, total_usd, total_bcv, metodo_pago, fecha)
            VALUES ('Informal', 10.0, 400.0, 'Efectivo', {codigo_fecha})
            """
        )
        venta_id = cursor.lastrowid
        conn.commit()
    return venta_id


# ─── 1. La venta nueva se guarda en hora local ───────────────────────────────

def test_la_fecha_de_una_venta_nueva_usa_la_hora_local_del_equipo(producto):
    venta_id = _vender()

    registrada = datetime.strptime(_fecha(venta_id), "%Y-%m-%d %H:%M:%S")

    assert abs((registrada - datetime.now()).total_seconds()) < 60


def test_una_venta_de_la_noche_sigue_perteneciendo_al_dia_en_curso(producto):
    """Con la fecha en UTC, una venta hecha después de las 20:00 en Venezuela
    ya figuraba con la fecha del día siguiente y "hoy" no la encontraba."""
    venta_id = _vender()

    with get_connection() as conn:
        encontradas = conn.execute(
            "SELECT id FROM ventas WHERE DATE(fecha) = DATE('now','localtime')"
        ).fetchall()

    assert [fila["id"] for fila in encontradas] == [venta_id]


def test_la_fecha_de_la_venta_queda_en_el_mismo_huso_que_la_del_producto(producto):
    """Las dos fechas se escriben en hora local: compararlas tiene que dar
    minutos de diferencia, no horas."""
    venta_id = _vender()

    with get_connection() as conn:
        creado = conn.execute(
            "SELECT created_at FROM productos WHERE codigo = ?", (producto,)
        ).fetchone()["created_at"]

    ingreso = datetime.strptime(creado, "%Y-%m-%d %H:%M:%S")
    vendido = datetime.strptime(_fecha(venta_id), "%Y-%m-%d %H:%M:%S")
    assert abs((vendido - ingreso).total_seconds()) < 60


# ─── 2. Migración de los registros heredados ─────────────────────────────────

def test_la_migracion_convierte_las_fechas_heredadas_en_utc(db_temporal):
    _limpiar_marca_migracion()
    venta_id = _insertar_venta_heredada()
    antes = _fecha(venta_id)

    assert migrar_fechas_ventas_a_hora_local() is True

    convertida = datetime.strptime(_fecha(venta_id), "%Y-%m-%d %H:%M:%S")
    esperada = datetime.strptime(antes, "%Y-%m-%d %H:%M:%S") + _desfase_utc_local()
    assert abs((convertida - esperada).total_seconds()) < 5


def test_la_migracion_deja_constancia_en_app_settings(db_temporal):
    _limpiar_marca_migracion()

    migrar_fechas_ventas_a_hora_local()

    with get_connection() as conn:
        fila = conn.execute(
            "SELECT value FROM app_settings WHERE key = ?", (CLAVE_MIGRACION_FECHA_VENTAS,)
        ).fetchone()
    assert fila is not None


def test_la_migracion_no_se_aplica_dos_veces(db_temporal):
    """Es idempotente: volver a correrla desplazaría las fechas otra vez, esta
    vez sin ningún UTC que corregir."""
    _limpiar_marca_migracion()
    venta_id = _insertar_venta_heredada()

    assert migrar_fechas_ventas_a_hora_local() is True
    tras_la_primera = _fecha(venta_id)

    assert migrar_fechas_ventas_a_hora_local() is False

    assert _fecha(venta_id) == tras_la_primera


def test_registrar_una_venta_dispara_la_migracion_antes_de_insertar(producto):
    """El orden es el punto: si la migración corriera DESPUÉS de empezar a
    escribir fechas locales, desplazaría también esas filas ya correctas."""
    _limpiar_marca_migracion()
    heredada_id = _insertar_venta_heredada()
    antes_heredada = _fecha(heredada_id)

    nueva_id = _vender()

    heredada = datetime.strptime(_fecha(heredada_id), "%Y-%m-%d %H:%M:%S")
    esperada = datetime.strptime(antes_heredada, "%Y-%m-%d %H:%M:%S") + _desfase_utc_local()
    assert abs((heredada - esperada).total_seconds()) < 5, "la heredada debe haberse convertido"

    nueva = datetime.strptime(_fecha(nueva_id), "%Y-%m-%d %H:%M:%S")
    assert abs((nueva - datetime.now()).total_seconds()) < 60, "la nueva no debe desplazarse"


def test_una_venta_posterior_no_vuelve_a_desplazar_las_fechas(producto):
    """La segunda venta no reabre la migración (la marca ya está puesta)."""
    _limpiar_marca_migracion()
    primera = _vender()
    fecha_primera = _fecha(primera)

    _vender()

    assert _fecha(primera) == fecha_primera
