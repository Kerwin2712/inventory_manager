"""Fixtures compartidas por toda la suite de pruebas.

Aislamiento de la base de datos (crítico): `core.database` importa
`DATABASE_PATH` desde `core.config` en tiempo de importación del módulo, y
`get_connection()` lo lee como global del módulo. Por eso el aislamiento se
hace re-apuntando `core.database.DATABASE_PATH` a un archivo SQLite temporal
por test — nunca se toca la base real del usuario en %APPDATA%.
"""
import os
import sys
from pathlib import Path

import pytest

# Permitir `import core.*`, `services.*`, `ui.*` al ejecutar pytest desde la raíz.
RAIZ_PROYECTO = Path(__file__).resolve().parent.parent
if str(RAIZ_PROYECTO) not in sys.path:
    sys.path.insert(0, str(RAIZ_PROYECTO))


@pytest.fixture
def db_temporal(tmp_path, monkeypatch):
    """Crea una base SQLite virgen (esquema completo vía `init_db`) y redirige
    todas las conexiones del proyecto hacia ella. Devuelve la ruta del archivo."""
    import core.database as database

    ruta = tmp_path / "inventory_test.db"
    monkeypatch.setattr(database, "DATABASE_PATH", str(ruta))
    monkeypatch.setenv("DATABASE_PATH", str(ruta))
    database.init_db()
    return ruta


@pytest.fixture
def conexion(db_temporal):
    """Conexión abierta a la base temporal (se cierra al finalizar el test)."""
    from core.database import get_connection

    conn = get_connection()
    yield conn
    conn.close()
