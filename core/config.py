import os
from dotenv import load_dotenv

# Cargar variables de entorno desde el archivo .env en la raíz
load_dotenv()

# Configuración global de la aplicación
DATABASE_PATH = os.getenv("DATABASE_PATH", "inventory.db")
RECUPERAR_PASS = os.getenv("RECUPERAR_PASS", "27934140")
