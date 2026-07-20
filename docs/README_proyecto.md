# Documentación de Referencia Técnica - Sistema Integrado de Inventario y Ventas

Este documento constituye la especificación de referencia del estado actual de la arquitectura, componentes y funcionamiento del **Sistema Integrado de Inventario y Ventas**.

---

## 🏛️ Arquitectura del Proyecto

El sistema está estructurado bajo los principios de la **Arquitectura Limpia (Clean Architecture)** y desarrollado con **Python** y **Flet** (Framework multiplataforma basado en Flutter).

```
inventory_manager/
│
├── core/                       # Capa de Configuración Global e Infraestructura
│   ├── __init__.py
│   ├── config.py               # Lectura de variables de entorno (.env) y constantes globales
│   ├── database.py             # Gestión de la conexión SQLite, esquemas y persistencia
│   └── security.py             # Hashing seguro con PBKDF2-HMAC-SHA256 y comparación segura
│
├── services/                   # Capa de Lógica de Negocio y Repositorios
│   ├── __init__.py
│   └── user_service.py         # Casos de uso de autenticación y CRUD de usuarios
│
├── ui/                         # Capa de Interfaz de Usuario (Frontend en Flet)
│   ├── __init__.py
│   ├── components/             # Widgets y componentes visuales reutilizables
│   └── views/                  # Vistas principales de la aplicación
│       ├── __init__.py
│       ├── base_view.py        # Plantilla unificada y motor centralizado de temas
│       ├── login_view.py       # Pantalla de inicio de sesión con soporte para tecla Enter
│       ├── admin_users_view.py # Panel aislado para la gestión exclusiva de cuentas por 'admin'
│       └── dashboard_view.py   # Dashboard con métricas de inteligencia de negocio y auditoría
│
├── docs/                       # Documentación y Bitácora de Desarrollo
│   ├── README_proyecto.md      # Manual de referencia técnica del proyecto
│   └── bitacora/               # Registro cronológico diario de actividades
│       └── julio_2026.md
│
├── .env                        # Configuración de entorno local (contraseñas iniciales)
├── .gitignore                  # Exclusión de archivos binarios, base de datos y grafos
├── main.py                     # Punto de entrada principal y enrutador de vistas
└── requirements.txt            # Dependencias del proyecto
```

---

## 🛠️ Funcionamiento de los Módulos Principales

### 1. Capa de Seguridad y Persistencia Base (`core/`)
- **`config.py`**: Centraliza la lectura de variables desde `.env` (`RECUPERAR_PASS`) y la ubicación de la base de datos `inventory.db`.
- **`security.py`**:
  - `hash_password(password)`: Genera un hash con sal aleatoria de 16 bytes mediante `PBKDF2-HMAC-SHA256` con 100,000 iteraciones (formato `salt_hex:hash_hex`).
  - `verify_password(password, stored_hash)`: Compara la contraseña utilizando `hmac.compare_digest` para prevenir ataques de tiempo.
- **`database.py`**:
  - Inicializa SQLite y crea automáticamente la tabla `users` y la tabla de configuración `app_settings`.
  - **Sembrado Automático por Primera Vez**: Al arrancar la aplicación en una instalación limpia, detecta si la cuenta `admin` existe. Si no existe, la crea asociándole el hash de la clave definida en `RECUPERAR_PASS`.
  - Proporciona las funciones `get_setting(key, default)` y `set_setting(key, value)` para almacenar las preferencias de la aplicación.

### 2. Capa de Servicios y Negocio (`services/`)
- **`user_service.py`**:
  - `authenticate_user(username, password)`: Valida las credenciales ingresadas en la BD.
  - `create_user(username, password, role)`: Registra nuevos usuarios con contraseña hasheada.
  - `get_all_users()` y `update_user(...)`: Permite listar y editar información de las cuentas existentes.

### 3. Capa de Interfaz y Sistema de Temas (`ui/`)
- **`base_view.py` (Clase Base):**
  - **Tokens de Color Adaptativos:** Métodos `get_accent_color()`, `get_bg_color()`, `get_sidebar_bg()`, `get_card_bg()`, `get_text_color()`, `get_subtext_color()` y `get_border_color()`.
  - **Alternancia Claro / Oscuro (`toggle_theme`):** En Modo Claro, la sidebar es blanca (`#FFFFFF`) y los textos adoptan tonos oscuros de alto contraste (`#0F172A`).
  - **Color de Acento (`change_seed_color`):** Aplica el color seleccionado (Azul `#2196F3`, Verde `#4CAF50`, Rojo `#E91E63`, Naranja `#FF9800`) exclusivamente al título de la pantalla, la opción activa del menú y la insignia del usuario.
  - **Persistencia Directa:** Guarda y recupera los cambios de tema de forma automática en SQLite (`app_settings`).
- **`login_view.py`:** Formulario de inicio de sesión centrado. Permite enviar las credenciales mediante el botón o presionando la tecla **Enter** (`on_submit`).
- **`admin_users_view.py`:** Pantalla aislada destinada únicamente a la cuenta inicial `admin`, con formulario de creación/edición de usuarios y tabla de cuentas registradas.
- **`dashboard_view.py`:** Dashboard interactivo con:
  - Sidebar con opciones de navegación.
  - Header dinámico con notificaciones, alternador de modo visual y selector de color.
  - Fila de 3 tarjetas de métricas resumidas (Ventas del Día, Productos en Stock, Alertas de Stock Bajo).
  - Dos secciones con datos: *Inteligencia de Negocio* (Top productos más vendidos) y *Auditoría Preventiva* (Ítems por debajo del stock mínimo con su proveedor).

---

## 🔄 Flujo de Navegación y Control de Accesos (`main.py`)

1. **Arranque:** `main.py` ejecuta `init_db()`, recupera las preferencias guardadas en SQLite y las aplica al tema global de la ventana.
2. **Autenticación:**
   - Si el usuario autenticado es **`admin`** (superusuario inicial): Se redirige de manera **aislada a `AdminUsersView`** para administrar las cuentas de la aplicación.
   - Si se autentica cualquier **otro usuario** (administrador real o vendedor): Se redirige al **`DashboardView`** comercial.
