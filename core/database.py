import sqlite3
from core.config import DATABASE_PATH, RECUPERAR_PASS
from core.security import hash_password

def get_connection():
    """Obtiene una conexión a la base de datos SQLite."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn

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
        
        # Verificar si el usuario admin inicial ya existe
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
