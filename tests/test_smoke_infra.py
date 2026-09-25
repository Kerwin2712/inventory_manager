"""Verificación del andamiaje: la base temporal se crea aislada y con esquema."""


def test_db_temporal_aislada_y_con_esquema(db_temporal, conexion):
    cursor = conexion.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tablas = {r["name"] for r in cursor.fetchall()}
    assert {"productos", "users", "ventas", "ventas_detalle", "clientes", "proveedores"} <= tablas
    assert db_temporal.exists()
