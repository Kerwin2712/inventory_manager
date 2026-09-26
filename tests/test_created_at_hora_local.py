"""Coherencia horaria de `productos.created_at`.

El DEFAULT `CURRENT_TIMESTAMP` de SQLite guarda UTC, mientras que
`fecha_ultima_modificacion` se escribe con la hora local del equipo. Un mismo
producto quedaba entonces con una "Fecha de Ingreso" adelantada respecto de su
"Última Modificación" (cuatro horas en Venezuela), y los filtros por fecha de
ingreso comparaban la fecha local que escribe el usuario contra timestamps UTC.
"""
from datetime import datetime, timedelta

import pytest

from core.database import _CLAVE_MIGRACION_CREATED_AT, _normalizar_created_at_productos
from services.inventario_service import crear_producto, listar_productos, obtener_producto


def _desfase_utc_local() -> timedelta:
    """Diferencia entre la hora local del equipo y UTC (0 si corre en UTC)."""
    return datetime.now() - datetime.utcnow()


@pytest.fixture
def producto(db_temporal):
    crear_producto(
        codigo="HORA-001",
        referencia="REF-HORA",
        descripcion_general="Producto para verificar la hora de ingreso",
        departamento="Pruebas",
        precio_dolares=10.0,
    )
    return "HORA-001"


def test_created_at_y_fecha_de_modificacion_quedan_en_el_mismo_huso(producto):
    prod = obtener_producto(producto)

    ingreso = datetime.strptime(prod["created_at"], "%Y-%m-%d %H:%M:%S")
    modificacion = datetime.strptime(prod["fecha_ultima_modificacion"], "%Y-%m-%d %H:%M:%S")

    assert abs((ingreso - modificacion).total_seconds()) < 5, (
        "la fecha de ingreso y la de modificación de un producto recién creado "
        "deben coincidir; una diferencia de horas significa husos distintos"
    )


def test_created_at_usa_la_hora_local_del_equipo(producto):
    prod = obtener_producto(producto)
    ingreso = datetime.strptime(prod["created_at"], "%Y-%m-%d %H:%M:%S")

    assert abs((ingreso - datetime.now()).total_seconds()) < 60


def test_el_filtro_por_fecha_de_ingreso_encuentra_el_producto_del_dia(producto):
    """Con `created_at` en UTC, un producto creado de noche en Venezuela ya
    figuraba con la fecha del día siguiente y el filtro de hoy no lo veía."""
    hoy = datetime.now().strftime("%Y-%m-%d")

    resultados = listar_productos(
        filtros={"fecha_ingreso_desde": hoy, "fecha_ingreso_hasta": hoy}
    )

    assert [p["codigo"] for p in resultados] == [producto]


# ── Migración de los registros anteriores ────────────────────────────────────
def test_la_migracion_convierte_los_created_at_heredados_en_utc(db_temporal, conexion):
    """Simula una fila vieja escrita con el DEFAULT en UTC y comprueba que la
    migración la deja en hora local."""
    cursor = conexion.cursor()
    cursor.execute("DELETE FROM app_settings WHERE key = ?", (_CLAVE_MIGRACION_CREATED_AT,))
    cursor.execute(
        """
        INSERT INTO productos (codigo, referencia, departamento, descripcion_general,
                               precio_dolares, created_at)
        VALUES ('VIEJO-001', 'REF', 'Pruebas', 'Registro heredado', 5.0, CURRENT_TIMESTAMP)
        """
    )
    conexion.commit()
    antes = cursor.execute(
        "SELECT created_at FROM productos WHERE codigo = 'VIEJO-001'"
    ).fetchone()["created_at"]

    assert _normalizar_created_at_productos(cursor) is True
    conexion.commit()

    despues = cursor.execute(
        "SELECT created_at FROM productos WHERE codigo = 'VIEJO-001'"
    ).fetchone()["created_at"]
    convertido = datetime.strptime(despues, "%Y-%m-%d %H:%M:%S")
    esperado = datetime.strptime(antes, "%Y-%m-%d %H:%M:%S") + _desfase_utc_local()
    assert abs((convertido - esperado).total_seconds()) < 5


def test_la_migracion_no_se_aplica_dos_veces(db_temporal, conexion):
    """Es idempotente: volver a correrla desplazaría las fechas otra vez."""
    cursor = conexion.cursor()
    cursor.execute("DELETE FROM app_settings WHERE key = ?", (_CLAVE_MIGRACION_CREATED_AT,))
    cursor.execute(
        """
        INSERT INTO productos (codigo, referencia, departamento, descripcion_general,
                               precio_dolares, created_at)
        VALUES ('VIEJO-002', 'REF', 'Pruebas', 'Registro heredado', 5.0, CURRENT_TIMESTAMP)
        """
    )
    conexion.commit()

    assert _normalizar_created_at_productos(cursor) is True
    conexion.commit()
    tras_la_primera = cursor.execute(
        "SELECT created_at FROM productos WHERE codigo = 'VIEJO-002'"
    ).fetchone()["created_at"]

    assert _normalizar_created_at_productos(cursor) is False
    conexion.commit()

    assert cursor.execute(
        "SELECT created_at FROM productos WHERE codigo = 'VIEJO-002'"
    ).fetchone()["created_at"] == tras_la_primera


def test_init_db_marca_la_migracion_como_aplicada(db_temporal, conexion):
    fila = conexion.cursor().execute(
        "SELECT value FROM app_settings WHERE key = ?", (_CLAVE_MIGRACION_CREATED_AT,)
    ).fetchone()
    assert fila is not None, "init_db() debe dejar constancia de la migración"
