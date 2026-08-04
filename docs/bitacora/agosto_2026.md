# Registro Diario de Desarrollo - Agosto 2026

## Rediseño y Optimización Visual Premium de la Vista de Login - 01/08/2026
- **Responsable:** Antigravity (IA Coding Assistant)
- **Actividades realizadas:**
  - **LoginView ([login_view.py](file:///c:/Users/EQUIPO%20DELL/Documents/GitHub/inventory_manager/ui/views/login_view.py)):**
    - Sobreescritura del método `setup_layout` para omitir el Header ("Control de Acceso") y el divisor de `BaseView`, logrando un fondo limpio de login.
    - Configuración del fondo general plano de la ventana a un tono oscuro neutro (`#0B0C10` en modo oscuro y `#F1F5F9` en modo claro) de acuerdo al diseño minimalista solicitado.
    - Eliminación del avatar e icono de seguridad superior para adoptar un título único estilizado y en negrita: "Iniciar sesión" (size=24, weight=BOLD).
    - Ajuste de los campos de texto (`username_input` y `password_input`) eliminando los iconos prefijos y aplicando bordes redondeados (`border_radius=8`), relleno oscuro (`#1D1E27`) y bordes en tono gris (`#343644`), los cuales cambian reactivamente a un celeste claro (`#90CAF9`) al enfocarse.
    - Implementación de un botón de inicio de sesión de tipo píldora (`border_radius=22` y `height=44`) con fondo oscuro (`#15161D`) y texto celeste (`#90CAF9`) conforme a la referencia visual.
    - Reducción del tamaño del contenedor de login (`border_radius=16` y `width=380`) asignando una altura fija de `370` e incorporando `tight=True` en la columna de controles para evitar el estiramiento vertical automático en Flet, logrando una estructura rectangular perfectamente compacta, ajustada y centrada en pantalla.
    - Corrección del error de atributo en padding mediante `ft.Padding(30, 30, 30, 30)`.
    - Corrección de `AttributeError` en Flet al reemplazar las coordenadas del gradiente lineal `ft.alignment.top_left`/`bottom_right` por las constantes universales en mayúscula `ft.Alignment.TOP_LEFT` y `ft.Alignment.BOTTOM_RIGHT`.
    - Envoltura de la inicialización del layout en un bloque `try-except` con volcado de traceback a la consola (`sys.stderr`) e integración de un botón interactivo "Copiar detalles del error" con compatibilidad de portapapeles polimórfico (`page.clipboard` y fallback `page.set_clipboard`).
  - **BaseView ([base_view.py](file:///c:/Users/EQUIPO%20DELL/Documents/GitHub/inventory_manager/ui/views/base_view.py)):**
    - Adición de un bloque `try-except` genérico en `setup_layout` que captura y vuelca el traceback de inicialización en consola, ofreciendo además un botón interactivo de copia del error compatible de forma polimórfica con múltiples versiones de Flet.
- **Verificaciones realizadas:** Ejecución de la aplicación verificando el arranque correcto del login con diseño premium tipo tarjeta flotante sobre gradiente, y validando la resiliencia de la interfaz ante excepciones de renderizado.
- **Estado del proyecto:** En desarrollo. Pantalla de login rediseñada con altos estándares estéticos y robustez mejorada.

### Cambio de punto de entrada a modo web (Flet) - 03/08/2026
- **Responsable:** Antigravity (IA Coding Assistant)
- **Actividades realizadas:**
  - **main.py:** Se modificó la llamada final `ft.run(main)` a `ft.run(main, view=ft.AppView.WEB_BROWSER, port=8550)` para permitir ejecutar y probar la aplicación como servidor web (navegador) en entornos que no soportan la ventana nativa de escritorio (sin Flutter/GUI disponible). Se dejó un comentario indicando que para el build de escritorio (producción/instalador) debe usarse `ft.run(main)` sin el parámetro `view`.
  - **core/config.py:** Se añadió `_default_database_path()`, que calcula la ruta por defecto de `inventory.db` en el directorio de datos de usuario del sistema operativo (`%APPDATA%\SistemaInventario\inventory.db` en Windows, con fallback a `XDG_DATA_HOME`/`~/.local/share` en otros SO) en lugar de una ruta relativa a la carpeta de instalación. `DATABASE_PATH` solo usa un valor fijo si se define explícitamente en `.env`; si no, cae en este default persistente. Objetivo: que un instalador Inno Setup que reemplace la carpeta `{app}` en cada actualización no borre ni sobrescriba la base de datos del cliente.
  - **README.md / docs/README_proyecto.md:** Documentado el nuevo comportamiento por defecto de `DATABASE_PATH` y eliminado el ejemplo que sugería fijarlo a `inventory.db` en el `.env`.
- **Verificaciones realizadas:** No fue posible ejecutar la aplicación (`python main.py`) ni probar el inicio de sesión (incluyendo `kerwin`/`1234`) porque el entorno de ejecución (sandbox de Cowork) falló repetidamente al iniciar por falta de espacio en disco; no hubo shell/Python disponible en esta sesión. Se revisó `core/database.py` y se confirmó que el sembrado automático de `init_db()` solo crea el usuario `admin`; no existe un usuario `kerwin` por defecto, por lo que esa cuenta debe crearse manualmente desde `AdminUsersView` o vía `create_user()` antes de poder iniciar sesión con ella. El cambio de `DATABASE_PATH` tampoco pudo probarse en ejecución real (crear carpeta en `%APPDATA%`, migrar datos existentes si los hubiera).
- **Estado del proyecto:** Cambios de código aplicados (main.py, core/config.py, documentación) pero **pendientes de verificación manual y de commit** — el sandbox de ejecución no estuvo disponible durante toda la sesión para correr la app, probar el login ni ejecutar `git commit`.
