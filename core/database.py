import sqlite3
from core.config import DATABASE_PATH, RECUPERAR_PASS
from core.security import hash_password

def get_connection():
    """Obtiene una conexión a la base de datos SQLite."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def _agregar_columna_si_falta(cursor, tabla: str, columna: str, tipo_sql: str) -> bool:
    """Migración incremental idempotente: agrega `columna` a `tabla` solo si no
    existe, consultando `PRAGMA table_info` en vez de confiar en el error del
    ALTER TABLE. Devuelve True si la columna se creó en esta llamada."""
    cursor.execute(f"PRAGMA table_info({tabla})")
    existentes = {fila[1] for fila in cursor.fetchall()}
    if columna in existentes:
        return False
    cursor.execute(f"ALTER TABLE {tabla} ADD COLUMN {columna} {tipo_sql}")
    return True


def _sincronizar_catalogo_departamentos(cursor) -> None:
    """Backfill del catálogo Departamento → Sub-Departamento a partir de los
    valores de texto que ya viven en `productos`. Idempotente: usa INSERT OR
    IGNORE contra los UNIQUE del catálogo.

    Trabaja sobre un cursor recibido para poder ejecutarse dentro de la misma
    transacción de `init_db()` (evita abrir una segunda conexión al archivo).
    """
    cursor.execute(
        "SELECT DISTINCT TRIM(departamento) AS nombre FROM productos "
        "WHERE departamento IS NOT NULL AND TRIM(departamento) <> ''"
    )
    for fila in cursor.fetchall():
        cursor.execute(
            "INSERT OR IGNORE INTO departamentos (nombre) VALUES (?)", (fila["nombre"],)
        )

    cursor.execute(
        "SELECT DISTINCT TRIM(departamento) AS padre, TRIM(sub_departamento) AS hijo "
        "FROM productos "
        "WHERE departamento IS NOT NULL AND TRIM(departamento) <> '' "
        "AND sub_departamento IS NOT NULL AND TRIM(sub_departamento) <> ''"
    )
    for fila in cursor.fetchall():
        cursor.execute(
            "SELECT id FROM departamentos WHERE nombre = ? COLLATE NOCASE", (fila["padre"],)
        )
        padre = cursor.fetchone()
        if not padre:
            continue
        cursor.execute(
            "INSERT OR IGNORE INTO sub_departamentos (departamento_id, nombre) VALUES (?, ?)",
            (padre["id"], fila["hijo"]),
        )


_CLAVE_MIGRACION_CREATED_AT = "migracion_created_at_local_productos"


def _normalizar_created_at_productos(cursor) -> bool:
    """Pasa a hora LOCAL los `created_at` de productos guardados en UTC.

    El DEFAULT `CURRENT_TIMESTAMP` de SQLite escribe UTC, mientras que
    `fecha_ultima_modificacion` se escribe con la hora local del equipo. Un
    mismo producto quedaba así con una fecha de ingreso adelantada respecto de
    su última modificación, y los filtros por fecha de ingreso comparaban la
    fecha local que escribe el usuario contra timestamps en UTC.

    Los productos nuevos ya se insertan con hora local (ver
    `services.inventario_service.crear_producto`); esta migración arregla los
    registros anteriores y corre UNA sola vez, marcada en `app_settings`.
    Devuelve True si hizo la conversión.
    """
    cursor.execute(
        "SELECT value FROM app_settings WHERE key = ?", (_CLAVE_MIGRACION_CREATED_AT,)
    )
    if cursor.fetchone():
        return False

    cursor.execute(
        "UPDATE productos SET created_at = datetime(created_at, 'localtime') "
        "WHERE created_at IS NOT NULL AND TRIM(created_at) <> ''"
    )
    cursor.execute(
        "INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, 'done')",
        (_CLAVE_MIGRACION_CREATED_AT,),
    )
    return True


def init_db():
    """Inicializa las tablas de la base de datos y los datos por defecto."""
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Crear tabla de usuarios
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Crear tabla de preferencias de la aplicación
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        # Crear tabla de clientes (Sección 1.2 ERS)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS clientes (
                cedula_rif TEXT PRIMARY KEY,
                nombre TEXT NOT NULL,
                direccion TEXT,
                telefono TEXT,
                correo TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Crear tabla de proveedores (Sección 1.3 ERS)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS proveedores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                empresa TEXT,
                contacto TEXT,
                telefono TEXT NOT NULL,
                correo TEXT,
                rif TEXT,
                descripcion TEXT,
                adjuntos TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        try:
            cursor.execute("ALTER TABLE proveedores ADD COLUMN rif TEXT")
        except Exception:
            pass
        
        # Crear tabla de productos — Módulo de Inventario (Sección 2 ERS)
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS productos (
                codigo          TEXT PRIMARY KEY,
                referencia      TEXT NOT NULL,
                departamento    TEXT NOT NULL,
                descripcion_general TEXT NOT NULL,
                marca           TEXT,
                precio_dolares  REAL NOT NULL DEFAULT 0,
                precio_bcv      REAL NOT NULL DEFAULT 0,
                proveedor_id    INTEGER,
                existencia      REAL NOT NULL DEFAULT 0,
                codigo_barras   TEXT,
                nombre_referencia_corto TEXT,
                fecha_ultima_modificacion TEXT,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (proveedor_id) REFERENCES proveedores(id)
                    ON UPDATE CASCADE ON DELETE SET NULL
            )
        """)

        # Migración incremental de productos: COSTOS del negocio (distintos de
        # los PRECIOS de venta `precio_dolares`/`precio_bcv`), jerarquía de
        # sub-departamento y umbral de alerta propio del producto.
        # Nullable en el esquema; la obligatoriedad del costo efectivo es una
        # regla de negocio validada en `services/inventario_service.py`.
        for _columna, _tipo in (
            ("costo_usd_efectivo", "REAL"),
            ("costo_usd_bcv", "REAL"),
            ("sub_departamento", "TEXT"),
            ("alerta_stock_minimo", "INTEGER"),
        ):
            _agregar_columna_si_falta(cursor, "productos", _columna, _tipo)

        _normalizar_created_at_productos(cursor)

        # Catálogo jerárquico Departamento → Sub-Departamento. `productos`
        # sigue guardando TEXT (compatibilidad con filtros y consultas
        # existentes); estas tablas son la fuente de verdad de los selectores.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS departamentos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL UNIQUE COLLATE NOCASE
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sub_departamentos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                departamento_id INTEGER NOT NULL REFERENCES departamentos(id) ON DELETE CASCADE,
                nombre TEXT NOT NULL,
                UNIQUE(departamento_id, nombre)
            )
        """)

        # Crear tabla de ventas (Cabecera - ERS 3.4 / 3.5)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ventas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tipo_venta TEXT NOT NULL,
                cliente_id TEXT,
                total_usd REAL NOT NULL DEFAULT 0,
                total_bcv REAL NOT NULL DEFAULT 0,
                metodo_pago TEXT NOT NULL DEFAULT 'Efectivo',
                fecha DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (cliente_id) REFERENCES clientes(cedula_rif)
                    ON UPDATE CASCADE ON DELETE SET NULL
            )
        """)
        try:
            cursor.execute("ALTER TABLE ventas ADD COLUMN metodo_pago TEXT NOT NULL DEFAULT 'Efectivo'")
        except Exception:
            pass

        # Crear tabla de ventas_detalle (Líneas - ERS 3.4 / 3.5)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ventas_detalle (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                venta_id INTEGER NOT NULL,
                producto_codigo TEXT NOT NULL,
                cantidad REAL NOT NULL,
                precio_unitario_usd REAL NOT NULL,
                precio_unitario_bcv REAL NOT NULL,
                subtotal_usd REAL NOT NULL,
                subtotal_bcv REAL NOT NULL,
                FOREIGN KEY (venta_id) REFERENCES ventas(id)
                    ON DELETE CASCADE,
                FOREIGN KEY (producto_codigo) REFERENCES productos(codigo)
                    ON UPDATE CASCADE
            )
        """)

        conn.commit()
        cursor.execute("SELECT id FROM users WHERE username = ?", ("admin",))
        admin_user = cursor.fetchone()
        
        if not admin_user:
            hashed_pw = hash_password(RECUPERAR_PASS)
            cursor.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                ("admin", hashed_pw, "superadmin")
            )
            print("[INFO] Usuario 'admin' inicial creado exitosamente en la base de datos.")

        # Insertar preferencias por defecto si no existen
        cursor.execute("INSERT OR IGNORE INTO app_settings (key, value) VALUES ('theme_mode', 'dark')")
        cursor.execute("INSERT OR IGNORE INTO app_settings (key, value) VALUES ('seed_color', '#2196F3')")

        # Backfill del catálogo: las instalaciones ya existentes arrancan con
        # sus departamentos/sub-departamentos poblados desde `productos`.
        _sincronizar_catalogo_departamentos(cursor)

        conn.commit()

def get_setting(key: str, default: str = "") -> str:
    """Recupera el valor de una configuración persistente desde SQLite."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM app_settings WHERE key = ?", (key,))
            row = cursor.fetchone()
            if row:
                return row["value"]
    except Exception:
        pass
    return default

def set_setting(key: str, value: str):
    """Guarda o actualiza una preferencia en SQLite."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO app_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value)
            )
            conn.commit()
    except Exception as e:
        print(f"[ERROR] No se pudo guardar la preferencia {key}: {e}")
