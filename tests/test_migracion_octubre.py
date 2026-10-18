"""Esquema de la actualización de Octubre 2026.

Las columnas y tablas nuevas (cobro de la venta, deudas por cobrar y sus
abonos) se crean dentro de `init_db`, que es idempotente: se ejecuta en cada
arranque de la aplicación, también sobre bases ya instaladas en casa del
cliente. Estas pruebas fijan ese contrato antes de que las vistas y los
servicios nuevos empiecen a escribir en él.
"""
import pytest

from core.database import get_connection


def _columnas(conn, tabla: str) -> set[str]:
    return {fila[1] for fila in conn.execute(f"PRAGMA table_info({tabla})").fetchall()}


def _tablas(conn) -> set[str]:
    filas = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {fila[0] for fila in filas}


def test_ventas_tiene_columnas_de_cobro(db_temporal):
    """Referencia del pago, su omisión confirmada, el monto realmente cobrado,
    el porcentaje de descuento y la cuenta que cobró."""
    with get_connection() as conn:
        cols = _columnas(conn, "ventas")
    for columna in (
        "referencia_pago",
        "referencia_omitida",
        "monto_cobrado",
        "porcentaje_descuento",
        "usuario_nombre",
    ):
        assert columna in cols, f"falta `ventas.{columna}`"


def test_clientes_tiene_contacto_secundario(db_temporal):
    with get_connection() as conn:
        assert "contacto_secundario" in _columnas(conn, "clientes")


def test_tablas_de_deudas_creadas(db_temporal):
    with get_connection() as conn:
        tablas = _tablas(conn)
    for tabla in ("deudas", "deuda_abonos", "deuda_items"):
        assert tabla in tablas, f"falta la tabla `{tabla}`"


def test_deudas_tiene_los_campos_de_la_lista(db_temporal):
    """La lista "Deudas por Cobrar" necesita fecha límite, fecha de creación,
    la cuenta de usuario que la originó y el saldo vivo."""
    with get_connection() as conn:
        cols = _columnas(conn, "deudas")
    for columna in (
        "venta_id",
        "cliente_id",
        "monto_total_usd",
        "saldo_usd",
        "fecha_creacion",
        "fecha_limite_pago",
        "usuario_nombre",
        "estado",
    ):
        assert columna in cols, f"falta `deudas.{columna}`"


def test_abono_queda_ligado_a_su_deuda(db_temporal):
    """Un abono sin deuda padre debe ser rechazado por la clave foránea."""
    with get_connection() as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT INTO clientes (cedula_rif, nombre) VALUES (?, ?)",
            ("V12345678", "Fulano de Tal"),
        )
        conn.execute(
            """INSERT INTO deudas
               (cliente_id, monto_total_usd, saldo_usd, fecha_creacion, fecha_limite_pago)
               VALUES (?, ?, ?, ?, ?)""",
            ("V12345678", 30.0, 30.0, "2026-10-10", "2026-11-10"),
        )
        deuda_id = conn.execute("SELECT id FROM deudas").fetchone()[0]
        conn.execute(
            """INSERT INTO deuda_abonos
               (deuda_id, monto_usd, metodo_pago, fecha) VALUES (?, ?, ?, ?)""",
            (deuda_id, 10.0, "Efectivo", "2026-10-18"),
        )
        with pytest.raises(Exception):
            conn.execute(
                """INSERT INTO deuda_abonos
                   (deuda_id, monto_usd, metodo_pago, fecha) VALUES (?, ?, ?, ?)""",
                (deuda_id + 999, 10.0, "Efectivo", "2026-10-18"),
            )


def test_init_db_es_idempotente(db_temporal):
    """Segundo arranque sobre la misma base: no debe fallar ni duplicar nada."""
    from core.database import init_db

    init_db()
    init_db()
    with get_connection() as conn:
        assert "deudas" in _tablas(conn)
        assert "referencia_pago" in _columnas(conn, "ventas")
