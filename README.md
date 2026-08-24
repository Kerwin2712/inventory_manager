# 📦 Sistema Integrado de Inventario y Ventas

Un software moderno de escritorio para la gestión integral de inventarios, control de ventas y administración de usuarios, desarrollado con **Python** y **Flet** bajo los principios de la **Arquitectura Limpia (Clean Architecture)**.

---

## 🚀 Características Principales

- **Arquitectura Limpia (Clean Architecture):** Separación estricta de responsabilidades en capas (`core/`, `services/`, `ui/`, `docs/`).
- **Interfaz Gráfica Moderna (Flet / Flutter):** Diseño responsivo, fluido y adaptable a la resolución de la pantalla.
- **Sistema de Temas Personalizable y Persistente:**
  - Alternancia dinámica entre **Modo Claro** (con sidebar blanca y contraste óptimo) y **Modo Oscuro**.
  - Paleta de colores de acento (Azul, Verde, Rojo, Naranja).
  - Persistencia automática de las preferencias visuales en SQLite.
- **Seguridad y Control de Accesos:**
  - Almacenamiento seguro de contraseñas mediante **PBKDF2-HMAC-SHA256** con sal aleatoria y verificación segura con `hmac.compare_digest`.
  - **Superusuario Inicial (`admin`):** Sembrado automático al instalar por primera vez con la clave configurada en `.env`.
  - **Enrutamiento por Permisos:** Pantalla aislada de administración de cuentas para `admin` y Dashboard comercial para los demás usuarios.
  - Inicio de sesión rápido mediante la tecla **Enter**.
- **Dashboard de Inteligencia de Negocio y Auditoría:**
  - Métricas rápidas de ventas y volumen de inventario.
  - Tablas de productos más vendidos y alertas de stock crítico por debajo del mínimo indicando el proveedor.

---

## 📋 Requisitos Previos

- **Python 3.10** o superior instalado en el sistema.
- Entorno de comandos compatible (**PowerShell** o **CMD** en Windows).

---

## ⚙️ Instalación y Configuración

Sigue los siguientes pasos para poner en marcha la aplicación en tu entorno local:

### 1. Clonar el Repositorio
```powershell
git clone https://github.com/Kerwin2712/inventory_manager.git
cd inventory_manager
```

### 2. Crear y Activar el Entorno Virtual
```powershell
python -m venv env
.\env\Scripts\activate
```

### 3. Instalar las Dependencias
```powershell
pip install -r requirements.txt
```

### 4. Configurar las Variables de Entorno
Crea un archivo llamado `.env` en la raíz del proyecto (o edita el existente) y define la clave inicial del superusuario `admin`:

```env
RECUPERAR_PASS=123456789
```

> **Ubicación de la base de datos:** si no defines `DATABASE_PATH`, la aplicación guarda `inventory.db` automáticamente en el directorio de datos de usuario del sistema (`%APPDATA%\SistemaInventario\inventory.db` en Windows). Esto es intencional: mantiene la base de datos fuera de la carpeta de instalación para que un instalador (Inno Setup) no la sobrescriba ni la elimine al actualizar la aplicación. Solo define `DATABASE_PATH` en el `.env` si necesitas forzar una ruta distinta (por ejemplo, en desarrollo local).

---

## 🏁 Ejecución de la Aplicación

Para lanzar la interfaz gráfica de la aplicación, ejecuta el punto de entrada principal:

```powershell
python main.py
```

### 🔐 Credenciales Iniciales de Instalación
Al ejecutar la aplicación por primera vez en un equipo nuevo, el sistema creará automáticamente la base de datos local y sembrará la cuenta inicial de instalación:

- **Usuario:** `admin`
- **Contraseña:** El valor asignado a la variable `RECUPERAR_PASS` en tu archivo `.env` (ej. `123456789`).

---

## 📦 Build de Escritorio e Instalador de Windows

`main.py` corre en modo escritorio (ventana nativa) al ejecutarse directamente
con `python main.py`. Para generar un `.exe` distribuible y un instalador de
Windows con asistente gráfico (PyInstaller + Inno Setup 6), incluyendo el
ícono de la aplicación, ver la guía completa en
[installer/README.md](installer/README.md).

---

## 📄 Derechos de Autor y Licencia

> **IMPORTANT:** 
> **© Todos los derechos reservados.**
> 
> Este proyecto, su código fuente, arquitectura, diseño de interfaz y elementos asociados son propiedad intelectual exclusiva de su autor (**Kerwin Quintero / Kerwin2712**). 
> 
> Queda estrictamente prohibida la reproducción, distribución, modificación, comercialización o uso no autorizado de este software o cualquiera de sus componentes sin la autorización previa y por escrito del titular de los derechos de autor.
