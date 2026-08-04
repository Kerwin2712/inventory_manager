import os
from pathlib import Path
from dotenv import load_dotenv

# Cargar variables de entorno desde el archivo .env en la raíz
load_dotenv()

APP_NAME = "SistemaInventario"


def _default_database_path() -> str:
    """
    Resuelve la ruta por defecto de la base de datos SQLite fuera de la
    carpeta de instalación de la aplicación.

    Motivo: si `inventory.db` vive dentro del directorio donde el instalador
    (Inno Setup) coloca los binarios, una actualización que reemplace o
    limpie esa carpeta puede borrar o sobrescribir la base de datos del
    cliente. Al guardarla en el directorio de datos de usuario del sistema
    operativo (`%APPDATA%` en Windows), el instalador nunca la toca entre
    versiones.
    """
    base_dir = os.getenv("APPDATA")  # Windows: C:\Users\<usuario>\AppData\Roaming
    if not base_dir:
        # Fallback para entornos no-Windows (desarrollo/pruebas en Linux/Mac)
        base_dir = os.getenv("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")

    data_dir = Path(base_dir) / APP_NAME
    data_dir.mkdir(parents=True, exist_ok=True)
    return str(data_dir / "inventory.db")


# Configuración global de la aplicación
# Si se define DATABASE_PATH explícitamente en el .env, se respeta tal cual
# (útil para desarrollo local). Si no, se usa una ruta persistente fuera de
# la carpeta de instalación para sobrevivir a las actualizaciones del
# instalador.
DATABASE_PATH = os.getenv("DATABASE_PATH") or _default_database_path()
RECUPERAR_PASS = os.getenv("RECUPERAR_PASS", "27934140")
