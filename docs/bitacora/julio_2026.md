# Registro Diario de Desarrollo

### 19/07/2026 Inicio del Proyecto

## Inicialización de la Arquitectura y Entorno Base
- **Responsable:** Antigravity (IA Coding Assistant)
- **Actividades realizadas:**
  - Creación de la estructura modular limpia del proyecto (`core/`, `services/`, `ui/views/`, `ui/components/`).
  - Configuración de dependencias iniciales en `requirements.txt`.
  - Implementación de la vista plantilla `BaseView` y la vista inicial de autenticación `LoginView` en Flet.
  - Redacción del manual de arquitectura base en `docs/README_proyecto.md`.
  - Configuración de las reglas de control y flujo de trabajo en `prompt_inicial.md`.
- **Estado del proyecto:** Inicializado. Listo para instalar dependencias y actualizar el grafo de dependencias con Grapiphy.

## Creación del Entry Point y Configuración de Ventana
- **Responsable:** Antigravity (IA Coding Assistant)
- **Actividades realizadas:**
  - Creación del archivo `main.py` en la raíz del proyecto para inicializar la aplicación Flet.
  - Configuración de la ventana principal (título "Sistema Integrado de Inventario y Ventas", modo oscuro y dimensiones mínimas).
  - Integración de `LoginView` en la carga inicial de la aplicación.
- **Estado del proyecto:** En desarrollo. Punto de entrada listo para pruebas de ejecución.

## Configuración de Control de Versiones e Ignorado de Grafo
- **Responsable:** Antigravity (IA Coding Assistant)
- **Actividades realizadas:**
  - Modificación del archivo `.gitignore` para incluir `graphify-out/`.
  - Eliminación de los archivos de `graphify-out/` previamente confirmados en el índice de Git sin eliminarlos físicamente del disco.
- **Estado del proyecto:** En desarrollo. Estructura de control de versiones optimizada.

## Corrección de Errores de Referencia de Flet
- **Responsable:** Antigravity (IA Coding Assistant)
- **Actividades realizadas:**
  - Corrección de `AttributeError` de Flet al cambiar las referencias a `ft.Padding` (con P mayúscula) en `ui/views/base_view.py` y `ui/views/login_view.py`.
  - Sustitución de `ft.app(target=main)` por `ft.run(main)` en `main.py` para resolver la advertencia de obsolescencia.
- **Estado del proyecto:** En desarrollo. Punto de entrada funcional sin warnings ni excepciones.

## Corrección de Atributos de Colores e Iconos en Flet
- **Responsable:** Antigravity (IA Coding Assistant)
- **Actividades realizadas:**
  - Corrección de `AttributeError` al reemplazar `ft.colors` por `ft.Colors` y `ft.icons` por `ft.Icons` en `ui/views/base_view.py` y `ui/views/login_view.py`.
- **Estado del proyecto:** En desarrollo. Aplicación completamente compatible con Flet 0.86.1.

## Corrección de Argumentos de Botones en Flet
- **Responsable:** Antigravity (IA Coding Assistant)
- **Actividades realizadas:**
  - Corrección de `TypeError` al reemplazar el argumento deprecado `text` por `content` en `ft.ElevatedButton` dentro de `ui/views/login_view.py`.
- **Estado del proyecto:** En desarrollo. Interfaz gráfica adaptada a las firmas de componentes de Flet 0.86.1.

## Corrección de Firmas de Icon y Alignment en Flet
- **Responsable:** Antigravity (IA Coding Assistant)
- **Actividades realizadas:**
  - Corrección de `TypeError` en `ft.Icon` al cambiar el nombre de argumento `name` por `icon`.
  - Corrección de referencia a la clase `ft.Alignment.CENTER` en la propiedad de alineación del contenedor principal de `LoginView`.
- **Estado del proyecto:** En desarrollo. Inicialización e instanciación de la interfaz de autenticación completamente comprobada.

## Corrección del Renderizado de Pantalla en Flet
- **Responsable:** Antigravity (IA Coding Assistant)
- **Actividades realizadas:**
  - Sustitución de `page.add(login_view)` por `page.views.append(login_view)` y `page.update()` en `main.py` para dibujar correctamente la pantalla.
  - Asignación de `expand=True` al contenedor principal en `ui/views/login_view.py` para abarcar el espacio de la ventana.
- **Estado del proyecto:** En desarrollo. Pantalla de inicio de sesión renderizada correctamente con todos sus controles visibles.

## Sistema de Autenticación, Hashing SQLite y Usuario Admin Inicial
- **Responsable:** Antigravity (IA Coding Assistant)
- **Actividades realizadas:**
  - Creación del módulo `core/config.py` para cargar variables de entorno (`.env`) y parámetros globales.
  - Implementación del módulo de seguridad `core/security.py` utilizando `hashlib.pbkdf2_hmac` con salt aleatorio y `hmac.compare_digest`.
  - Desarrollo del manejador de base de datos SQLite en `core/database.py` con inicialización de tabla `users` y sembrado del usuario inicial `admin` con el hash de `RECUPERAR_PASS`.
  - Creación del servicio `services/user_service.py` para autenticación y operaciones CRUD de cuentas de usuario.
  - Diseño de la interfaz de administración `ui/views/admin_users_view.py` exclusiva para el superusuario `admin`, permitiéndole registrar y modificar otros usuarios del sistema.
  - Integración de autenticación real en `ui/views/login_view.py` y enrutamiento dinámico en `main.py`.
- **Estado del proyecto:** En desarrollo. Módulo de autenticación y gestión de usuarios completado y verificado.

## Exclusión de SQLite en Gitignore y Actualización de Botones Deprecados
- **Responsable:** Antigravity (IA Coding Assistant)
- **Actividades realizadas:**
  - Adición de `inventory.db` y `*.db` a `.gitignore` y desindexado en Git (`git rm --cached`) para evitar la sincronización de archivos de base de datos locales.
  - Reemplazo de `ft.ElevatedButton` por la clase recomendada `ft.Button` en `main.py`, `login_view.py` y `admin_users_view.py`, eliminando los avisos de obsolescencia.
- **Estado del proyecto:** En desarrollo. Consola de comandos sin advertencias y control de versiones configurado correctamente.

## Sistema Centralizado de Temas y Dashboard del Super Admin
- **Responsable:** Antigravity (IA Coding Assistant)
- **Actividades realizadas:**
  - Actualización de `ui/views/base_view.py` incorporando los métodos `toggle_theme` (modo claro/oscuro) y `change_seed_color` (`color_scheme_seed`) con comentarios guía de persistencia futura en SQLite.
  - Creación del Dashboard del Super Admin en `ui/views/dashboard_view.py` con Sidebar de navegación (Inicio, Ventas, Inventario, Cartera, Gestión de Datos), Header con notificaciones y selector de 4 colores de acento (Azul, Verde, Rojo, Naranja), 3 Cards de métricas rápidas, y secciones para Inteligencia de Negocio y Auditoría Preventiva de Stock Crítico.
  - Enrutamiento dinámico y prueba visual en `main.py`.
- **Estado del proyecto:** En desarrollo. Pantalla de Dashboard e infraestructura de temas dinámicos implementadas.

## Aislamiento de Vista de Gestión de Usuarios para la Cuenta Admin Inicial
- **Responsable:** Antigravity (IA Coding Assistant)
- **Actividades realizadas:**
  - Configuración de enrutamiento estricto en `main.py`: el usuario `admin` inicial es redirigido de forma exclusiva a `AdminUsersView` para crear y modificar usuarios, mientras que el resto de los usuarios acceden al `DashboardView`.
  - Integración de los controles de personalización de temas (modo oscuro/claro y selector de color de acento) en la barra superior de `ui/views/admin_users_view.py`.
  - Limpieza de `ui/views/dashboard_view.py` removiendo enlaces administrativos irrelevantes para los usuarios convencionales.
- **Estado del proyecto:** En desarrollo. Separación de responsabilidades y vista exclusiva de administración configuradas.

## Corrección del Sistema de Acentos de Color y Legibilidad en Modo Claro
- **Responsable:** Antigravity (IA Coding Assistant)
- **Actividades realizadas:**
  - Rediseño de `ui/views/base_view.py` incorporando tokens de color adaptativos (`get_accent_color`, `get_bg_color`, `get_sidebar_bg`, `get_card_bg`, `get_text_color`, `get_subtext_color`).
  - Aplicación estricta del color de acento (`color_scheme_seed`) exclusivamente en el título de la pantalla, ícono de usuario y la opción activa de la sidebar.
  - Corrección de la apariencia en Modo Claro: Sidebar con fondo blanco impecable y todos los elementos de texto configurados en colores oscuros de alto contraste para máxima legibilidad.
- **Estado del proyecto:** En desarrollo. Personalización de temas visuales corregida y validada.

## Persistencia de Preferencias de Tema en SQLite
- **Responsable:** Antigravity (IA Coding Assistant)
- **Actividades realizadas:**
  - Adición de la tabla `app_settings` y funciones `get_setting` / `set_setting` en `core/database.py` para almacenar `theme_mode` y `seed_color`.
  - Sincronización automática en `ui/views/base_view.py` para actualizar SQLite al ejecutar `toggle_theme` o `change_seed_color`.
  - Restauración automática del tema guardado al arrancar la aplicación en `main.py`.
- **Estado del proyecto:** En desarrollo. Persistencia de tema visual implementada y verificada.

## Inicio de Sesión mediante Tecla Enter
- **Responsable:** Antigravity (IA Coding Assistant)
- **Actividades realizadas:**
  - Configuración del evento `on_submit=self.handle_login` en los campos `username_input` y `password_input` de `ui/views/login_view.py`.
  - Permite a los usuarios autenticarse directamente al presionar la tecla Enter desde cualquier campo de credenciales.
- **Estado del proyecto:** En desarrollo. Accesibilidad e interactividad del formulario de login mejoradas.

## Actualización de Documentación de Referencia y Manual de Inicio
- **Responsable:** Antigravity (IA Coding Assistant)
- **Actividades realizadas:**
  - Redacción técnica completa de `docs/README_proyecto.md` especificando la arquitectura Clean Architecture, módulos (`core/`, `services/`, `ui/`), hashing PBKDF2-HMAC-SHA256, enrutamiento por roles y sistema de temas con SQLite.
  - Creación de `README.md` profesional con características del software, instrucciones paso a paso de instalación/ejecución y sección de derechos de autor y propiedad intelectual.
- **Estado del proyecto:** En desarrollo. Documentación técnica y legal actualizada.

## Corrección Estructural de Bitácora y Modelado de Dominio (ERS)
- **Responsable:** Antigravity (IA Coding Assistant)
- **Actividades realizadas:**
  - Actualización de `.agents/prompt_inicial.md` y `prompt_inicial.md` especificando las Reglas 1 y 2 para el manejo de bitácoras segmentadas por mes (`docs/bitacora/julio_2026.md`).
  - Creación del módulo de modelos de dominio en `core/models.py` definiendo las clases `Cliente`, `Proveedor` y `Producto` con sus validaciones estrictas:
    - **`Cliente`:** Validación RNO-CLI-01 para obligatoriedad de Nombre/Razón Social y Cédula/RIF.
    - **`Proveedor`:** Validación RNO-PROV-01 y código de error `ERR_PROV_INS_INVALID` si falta el teléfono de contacto o los datos de la empresa/vendedor.
    - **`Producto`:** Esquema estricto de 12 campos del documento ERS (incluyendo `descripcion_general`, `nombre_referencia_corto` limitado a 30 caracteres para notas impresas y método de cálculo `calcular_precio_bcv`).
- **Estado del proyecto:** En desarrollo. Modelos de dominio base implementados y verificados.

## Persistencia y Servicio de Cartera de Clientes y Proveedores
- **Responsable:** Antigravity (IA Coding Assistant)
- **Actividades realizadas:**
  - Inclusión de sentencias DDL en `core/database.py` para la creación de las tablas `clientes` (`cedula_rif` como clave primaria) y `proveedores` (`id` autoincremental).
  - Desarrollo del módulo de servicios `services/cartera_service.py` implementando las funciones CRUD para ambas entidades con Clean Architecture.
  - Integración de validaciones de reglas de negocio:
    - **RNO-CLI-01:** Validación de no vacíos y `strip()` en Nombre/Razón Social y Cédula/RIF en `crear_cliente` y `actualizar_cliente`.
    - **RNO-PROV-01:** Validación de matriz asociativa `(Empresa + Teléfono) Ó (Contacto + Teléfono)` y emisión del código de excepción `ERR_PROV_INS_INVALID` si no se cumplen las condiciones.
- **Estado del proyecto:** En desarrollo. Persistencia y servicios de la cartera de entidades completados y validados.

## Interfaz de Usuario para Cartera de Clientes y Proveedores (CarteraView)
- **Responsable:** Antigravity (IA Coding Assistant)
- **Actividades realizadas:**
  - Creación de la vista `ui/views/cartera_view.py` (`CarteraView` heredando de `BaseView`).
  - Separación de la interfaz mediante pestañas seleccionables (`SegmentedButton`) para "Clientes" y "Proveedores".
  - Construcción de los formularios de captura y tablas `DataTable` en tiempo real para listar clientes y proveedores.
  - Implementación del manejo de excepciones y alertas flotantes `SnackBar` notificando en pantalla errores RNO-CLI-01 y el código `ERR_PROV_INS_INVALID` (RNO-PROV-01).
  - Conexión de la navegación en la barra lateral (`DashboardView`) permitiendo conmutar al módulo de Cartera de forma fluida.
- **Estado del proyecto:** En desarrollo. Módulo gráfico de Cartera de Entidades completado e integrado.

## UI Avanzada de Cartera: Pantalla Completa, Flujo Buscar-Antes-de-Crear y Paginación
- **Responsable:** Antigravity (IA Coding Assistant)
- **Actividades realizadas:**
  - Configuración del inicio de la aplicación en pantalla completa (`MAXIMIZED`) en `main.py`.
  - Ampliación de `services/cartera_service.py` con métodos de búsqueda (`buscar_cliente_por_cedula`, `buscar_proveedores`) y funciones de eliminación segura (`eliminar_cliente`, `eliminar_proveedor`) con simulación de comprobación de dependencias.
  - Rediseño integral de `ui/views/cartera_view.py`:
    - **Flujo "Buscar Antes de Crear":** Formularios de creación ocultos por defecto (`visible=False`). Si la entidad existe, despliega tarjeta de detalle con opciones de edición y eliminación. Si no existe, lanza un aviso `SnackBar` suave y muestra el formulario de registro.
    - **Paginación Local:** DataGrid con límite de 10 registros por página y navegadores "Anterior" / "Siguiente".
    - **DataGrid con Acciones:** Columna "Acciones" en cada fila con botones de íconos para editar y eliminar de forma segura, capturando excepciones de integridad con `SnackBar`.
- **Estado del proyecto:** En desarrollo. Módulo avanzado de Cartera de Entidades completado y verificado.

## Corrección de Actualización de Control Secundario en CarteraView
- **Responsable:** Antigravity (IA Coding Assistant)
- **Actividades realizadas:**
  - Solución del error `RuntimeError: Control must be added to the page first` al intentar eliminar o editar registros en `ui/views/cartera_view.py`.
  - Implementación de los métodos `get_current_page(e)` y `safe_update(e)` para resolver de manera segura la instancia de `page` activa desde el evento del botón o el árbol de controles.
  - Actualización de las alertas emergentes `show_alert_error`, `show_alert_success` y `show_alert_info` garantizando el refresco suave de la interfaz en controles anidados.
- **Estado del proyecto:** En desarrollo. Manejo de estado y renderizado seguro en CarteraView corregidos y validados.

## Selectores Desplegables de Tipo de Documento en CarteraView
- **Responsable:** Antigravity (IA Coding Assistant)
- **Actividades realizadas:**
  - Rediseño de las barras de búsqueda y formularios de captura de Clientes y Proveedores en `ui/views/cartera_view.py`.
  - Integración de selectores desplegables `ft.Dropdown` (`V`, `E`, `J`, `G`, `P`) combinados con campos de texto exclusivamente numéricos `keyboard_type=ft.KeyboardType.NUMBER`.
  - Implementación de las funciones auxiliares `parse_documento` y `format_documento` para formatear y descomponer automáticamente la identificación estándar (ej: `V-12345678`, `J-987654321`).
- **Estado del proyecto:** En desarrollo. Captura estructurada de Cédula y RIF implementada y verificada.

## Optimización de Búsqueda Flexible e Informativa en Cartera
- **Responsable:** Antigravity (IA Coding Assistant)
- **Actividades realizadas:**
  - Actualización de `buscar_cliente_por_cedula` en `services/cartera_service.py` para realizar búsquedas por coincidencia exacta y por dígitos numéricos.
  - Mejora de los manejadores `handle_buscar_cliente` y `handle_buscar_proveedor` en `ui/views/cartera_view.py`:
    - Captura automática de la entrada desde la barra de búsqueda o desde el campo del formulario si la barra está desocupada.
    - Notificación suave mediante `SnackBar` (*"El cliente con Cédula/RIF 'V-12345678' no existe. Proceda a registrarlo a continuación."*) cuando la entidad no está registrada.
    - Apertura automática del formulario de captura desplegando los campos de tipo y número con los valores buscados listos para completar.
- **Estado del proyecto:** En desarrollo. Flujo de búsqueda inteligente y mensajes de estado completados.

## Bloqueo y Auto-completado de Documento Buscado en Cartera
- **Responsable:** Antigravity (IA Coding Assistant)
- **Actividades realizadas:**
  - Automatización de la transferencia de Cédula / RIF desde la búsqueda hacia el formulario de registro en `ui/views/cartera_view.py`.
  - Configuración de `disabled = True` en los campos `cli_tipo_doc`, `cli_num_doc`, `prov_tipo_doc` y `prov_num_doc` al no encontrar la entidad en la búsqueda.
  - Evita la re-escritura manual del número de documento y garantiza la integridad de los datos entre la búsqueda y la creación en SQLite.
- **Estado del proyecto:** En desarrollo. Flujo de registro automático con bloqueo de documento verificado.

## Motor de Tasa BCV y Módulo de Inventario — Capa de Servicios y SQLite
- **Responsable:** Antigravity (IA Coding Assistant)
- **Actividades realizadas:**
  - Creación de `services/bcv_service.py`:
    - `actualizar_tasa(tasa)`: Persiste la tasa BCV y un timestamp ISO 8601 en `app_settings` (claves `tasa_bcv` y `fecha_tasa_bcv`).
    - `obtener_estado_tasa()`: Retorna la tasa actual y una descripción legible del tiempo transcurrido (*"Actualizado hace 4 horas"*, *"Tiene 2 días sin actualizarse"*, *"Sin tasa BCV configurada"*).
  - Actualización de `core/database.py` con `CREATE TABLE IF NOT EXISTS productos`:
    - 12 campos exactos del ERS: `codigo` (PK), `referencia`, `departamento`, `descripcion_general`, `marca`, `precio_dolares`, `precio_bcv`, `proveedor_id` (FK → `proveedores.id` con `ON DELETE SET NULL`), `existencia`, `codigo_barras`, `nombre_referencia_corto`, `fecha_ultima_modificacion`.
    - `PRAGMA foreign_keys = ON` activado para respetar la integridad referencial.
  - Creación de `services/inventario_service.py` con CRUD completo:
    - `crear_producto` / `actualizar_producto`: Aplican reglas ERS 3.1 (campos obligatorios, lógica existencia-precio, cálculo automático de `precio_bcv` desde tasa BCV, nombre corto auto-generado ≤30 caracteres, detección de código duplicado con `ERR_PROD_DUPLICADO`).
    - `listar_productos`: Filtros opcionales de departamento, búsqueda libre y proveedor con paginación.
    - `eliminar_producto`: Con verificación de existencia previa.
- **Verificaciones realizadas:** Todos los casos de prueba pasaron (columnas correctas, FK definida, cálculo BCV automático 100×50.25=5025.0, duplicado capturado, validación precio-existencia funcional).
- **Estado del proyecto:** En desarrollo. Motor de tasa BCV y capa de servicios de inventario implementados y verificados.

## UI del Módulo de Inventario — InventarioView (ERS 3.1 / 3.2)
- **Responsable:** Antigravity (IA Coding Assistant)
- **Actividades realizadas:**
  - Creación de `ui/views/inventario_view.py` con la clase `InventarioView` heredando de `BaseView`.
  - **Panel BCV:** Indicador de tasa actual con tiempo transcurrido. Si han pasado más de 24 horas, el indicador cambia a ámbar/naranja con ícono de advertencia. Campo numérico y botón "Actualizar Tasa" que llama a `bcv_service.actualizar_tasa()` y refresca el indicador en tiempo real.
  - **Filtros en Cascada (ERS 3.2):** Cuatro campos (Código, Descripción, Marca, Departamento) con evento `on_change` que ejecuta búsqueda en tiempo real combinando todos los filtros en AND dinámico. Botón "Limpiar filtros" para resetear todos los campos y recargar el inventario completo.
  - **DataTable Paginado:** Muestra 15 productos por página con navegadores de página. Columnas: Código, Referencia, Descripción, Depto., Marca, Precio $ (verde), Precio Bs (ámbar), Existencia y Acciones (editar/eliminar).
  - **Flujo de Ingreso en 3 Pasos (ERS 3.1):**
    - **Paso 1 (Verificación):** `AlertDialog` con campo de código y botón "Verificar". Si el código existe, abre diálogo de duplicado con opciones "Ver Producto" o "Limpiar Código". Si no existe, avanza al formulario.
    - **Paso 2 (Formulario Dinámico):** 11 campos del ERS incluyendo `ft.Dropdown` de proveedores desde `cartera_service.listar_proveedores()`. El `on_change` del campo existencia oculta la fila de precios cuando el valor es 0.
    - **Paso 3 (Confirmación):** Diálogo "¿ESTÁS SEGURO DE REGISTRAR EL SIGUIENTE ÍTEM?" listando todos los campos con valor o "— no llenado —". Opciones: "Cancelar", "Editar" (vuelve al Paso 2) y "Aceptar — Guardar" (ejecuta el COMMIT).
  - **Integración en Dashboard:** `dashboard_view.py` importa `InventarioView` y la instancia al navegar al módulo "Inventario" desde la Sidebar.
- **Verificaciones realizadas:** `InventarioView()`, `get_body()` y todos los atributos de control instanciados sin errores.
- **Estado del proyecto:** En desarrollo. Módulo de Inventario (UI completa) implementado e integrado en el Dashboard.

## Motor Transaccional y Tablas de Ventas (ERS 3.4 / 3.5)
- **Responsable:** Antigravity (IA Coding Assistant)
- **Actividades realizadas:**
  - **Esquema de Base de Datos (`core/database.py`):**
    - Adición de las sentencias `CREATE TABLE IF NOT EXISTS ventas` (cabecera con `id`, `tipo_venta`, `cliente_id` FK a `clientes`, `total_usd`, `total_bcv` y `fecha`).
    - Adición de `CREATE TABLE IF NOT EXISTS ventas_detalle` (líneas con `id`, `venta_id` FK a `ventas` con `ON DELETE CASCADE`, `producto_codigo` FK a `productos`, `cantidad`, `precio_unitario_usd`, `precio_unitario_bcv`, `subtotal_usd`, `subtotal_bcv`).
  - **Capa de Servicios ACID (`services/ventas_service.py`):**
    - Creación del servicio `procesar_venta(tipo_venta: str, cliente_id: str = None, lineas: list)`.
    - Validaciones estrictas ERS 3.4: Si `tipo_venta` es 'Formal', se exige `cliente_id` no nulo/vacío y su existencia en la base de datos `clientes`. Si es 'Informal', se ignora el cliente.
    - Lógica transaccional ACID en SQLite (`BEGIN TRANSACTION`, `COMMIT`, `ROLLBACK`): verifica existencia y stock suficiente por ítem, inserta en `ventas_detalle` y descuenta el campo `existencia` en `productos`. Si ocurre cualquier falla, revierte todos los cambios.
- **Verificaciones realizadas:** Suite de pruebas automatizada comprobando validación de cliente obligatorio, cliente inexistente, stock insuficiente con rollback y ventas exitosas con descuento de inventario.
- **Estado del proyecto:** En desarrollo. Motor transaccional del Módulo de Ventas completado y verificado.

## Servicio de Notas de Entrega PDF y Poblado de Datos Realistas (ERS 3.5 & Seed)
- **Responsable:** Antigravity (IA Coding Assistant)
- **Actividades realizadas:**
  - **Integración de Dependencia:** Adición e instalación de `fpdf2` en `requirements.txt`.
  - **Servicio de PDF (`services/pdf_service.py`):**
    - Desarrollo de `generar_nota_entrega_pdf(venta_id: int, divisa_impresion: str)`.
    - **Regla Estricta ERS 3.5:** Impresión exclusiva del campo `nombre_referencia_corto` de la tabla `productos`, omitiendo la descripción general.
    - Soporte bimoneda ('USD' y 'BCV') formateando subtotales y totales en dólares o bolívares.
    - Exportación de archivos PDF a la carpeta `exports/` (`exports/Nota_Entrega_{venta_id}.pdf`).
  - **Script de Sembrado (`seed.py`):**
    - Creación y ejecución de `seed.py` para popular SQLite con datos de prueba realistas.
    - Inserción en orden obligatorio: Tasa BCV inicial (732.48 con 2 decimales visible), 3 Proveedores (RNO-PROV-01), 5 Clientes (RNO-CLI-01) y 15 Productos variados (con y sin existencia, vinculados a sus `proveedor_id` correspondientes).
- **Verificaciones realizadas:** Ejecución exitosa de `seed.py` poblando tablas base, y generación verificada de Notas de Entrega PDF en la carpeta `exports/`.
- **Estado del proyecto:** En desarrollo. Generador de PDF y base de datos poblada para pruebas de interfaz comercial.

## Módulo de Ventas e Interfaz de Notas de Entrega PDF (ERS 3.4 & 3.5)
- **Responsable:** Antigravity (IA Coding Assistant)
- **Actividades realizadas:**
  - **Refactorización de Servicio PDF (`services/pdf_service.py`):**
    - Modificación de `generar_nota_entrega_pdf` aceptando el parámetro `ruta_destino: str`.
    - Remoción de la creación forzada del directorio `exports/`, permitiendo guardar el PDF en cualquier ruta seleccionada por el usuario.
  - **Creación de VentasView (`ui/views/ventas_view.py`):**
    - Instanciación e integración de `ft.FilePicker` vinculado a `page.overlay`.
    - Persistencia del directorio preferido en SQLite (`get_setting("last_pdf_dir")` y `set_setting("last_pdf_dir")`).
    - Cabecera con selector `SegmentedButton` para Venta Formal/Informal. Panel de cliente con búsqueda por Cédula/RIF (oculto en Informal).
    - Selección interactiva de productos por código, verificación de existencias y gestión de carrito (`DataTable` temporal).
    - Panel de resumen de venta con subtotales y totales bimoneda ($ / Bs).
    - Flujo de procesamiento transaccional (`procesar_venta`) con alertas `SnackBar` y diálogo de confirmación `AlertDialog` para generar la Nota de Entrega PDF en USD o BCV mediante `save_file()`.
  - **Navegación e Integración (`ui/views/dashboard_view.py`):** Conexión de la opción "Ventas" en la barra lateral para navegar a `VentasView`.
- **Verificaciones realizadas:** Simulación del flujo completo de ventas (Formal/Informal, validación de existencias, commit ACID y generación de PDF nativo).
- **Estado del proyecto:** En desarrollo. Módulo de Ventas y Notas de Entrega PDF completado e integrado en el Dashboard.

## Corrección del Bug de Serialización de Conjuntos (Set) en Flet
- **Responsable:** Antigravity (IA Coding Assistant)
- **Actividades realizadas:**
  - Diagnóstico de `TypeError: can not serialize 'set' object` en `msgpack` al renderizar `SegmentedButton` en `ui/views/ventas_view.py`.
  - Reemplazo de la sintaxis literal `selected={"Formal"}` (conjunto/set) por `selected=["Formal"]` (lista serializable por msgpack).
- **Verificaciones realizadas:** Verificación de tipo con `assert isinstance(selected, list)` y prueba de instanciación completa.
- **Estado del proyecto:** En desarrollo. Bug de empaquetado Flet resuelto y validado.

## Incorporación de Desplazamiento Vertical (Scroll) en VentasView
- **Responsable:** Antigravity (IA Coding Assistant)
- **Actividades realizadas:**
  - Configuración de `scroll = ft.ScrollMode.AUTO` en el contenedor principal de `ui/views/ventas_view.py`.
  - Habilitación de `wrap = True` en el contenedor del carrito y panel de totales para permitir reajuste dinámico en resoluciones reducidas.
  - Aseguramiento de reasignación en lista `e.control.selected = [val]` al cambiar de tipo de venta.
- **Verificaciones realizadas:** Verificación de propiedad `scroll == ScrollMode.AUTO` y prueba de renderizado.
- **Estado del proyecto:** En desarrollo. Scroll vertical y visibilidad de resumen de venta optimizados.

## Optimización de Layout e Indicador de Carrito Vacío en VentasView
- **Responsable:** Antigravity (IA Coding Assistant)
- **Actividades realizadas:**
  - Solución del rectángulo gris provocado por anidaciones redundantes de contenedores con `expand=True` dentro de `Row` en `ui/views/ventas_view.py`.
  - Reestructuración de la fila inferior con dimensiones explícitas: alineación lateral directa de `tabla_carrito_container` y `panel_totales`.
  - Rediseño de `build_tabla_carrito()` agregando ícono informativo, título en tipografía destacada y guía descriptiva con fondo adaptativo `get_card_bg()`.
- **Verificaciones realizadas:** Prueba automatizada de renderizado para carrito vacío y carrito poblado pasando con éxito.
- **Estado del proyecto:** En desarrollo. Módulo de Ventas visualmente corregido, responsivo e integrado.

## Eliminación de Carpeta Exports y Ajuste de Botón Procesar Venta
- **Responsable:** Antigravity (IA Coding Assistant)
- **Actividades realizadas:**
  - Remoción de la etiqueta `(COMMIT)` del botón principal en `ui/views/ventas_view.py` cambiando su leyenda a `"PROCESAR VENTA"`.
  - Eliminación física de la carpeta `exports/` del proyecto para basar el flujo de guardado exclusivamente en la ventana nativa de Windows **Guardar como** mediante `ft.FilePicker`.
  - Persistencia del directorio seleccionado por el usuario en la tabla `app_settings` (`last_pdf_dir`) en SQLite para recordarlo en posteriores exportaciones.
- **Verificaciones realizadas:** Eliminación de `exports/` comprobada con `Test-Path`, pruebas de instanciación e integración de FilePicker.
- **Estado del proyecto:** En desarrollo. Diálogo de exportación PDF nativo con persistencia de directorio configurado.

## Corrección del Lanzamiento Asíncrono de FilePicker.save_file (Flet 0.86.1)
- **Responsable:** Antigravity (IA Coding Assistant)
- **Actividades realizadas:**
  - Solución a la advertencia `RuntimeWarning: coroutine 'FilePicker.save_file' was never awaited` en `ui/views/ventas_view.py`.
  - Invocación de la corrutina asíncrona mediante `page.run_task(self.file_picker.save_file, **kwargs_save)`.
  - Habilita la apertura limpia del cuadro de diálogo nativo de Windows **Guardar como** desde el entorno de ejecución de Flet.
- **Verificaciones realizadas:** Prueba de instanciación con `run_task` ejecutada limpiamente sin advertencias de corrutina.
- **Estado del proyecto:** En desarrollo. Apertura asíncrona de cuadro de diálogo PDF nativo resuelta y validada.

## Registro Permanente de FilePicker en page.overlay (Solución TimeoutException)
- **Responsable:** Antigravity (IA Coding Assistant)
- **Actividades realizadas:**
  - Diagnóstico del error `RuntimeError: TimeoutException: Timeout waiting for invoke method listener for FilePicker` al guardar PDFs.
  - Registro de una instancia global permanente de `ft.FilePicker()` en `page.overlay` al arrancar `main(page)` en `main.py`.
  - Actualización de `ensure_file_picker_in_overlay()` en `ui/views/ventas_view.py` para reutilizar automáticamente el `FilePicker` activo en `page.overlay`.
- **Verificaciones realizadas:** Prueba automatizada verificando la reutilización transparente de `FilePicker` en `page.overlay`.
- **Estado del proyecto:** En desarrollo. FilePicker nativo registrado permanentemente en el socket de Flet.

## Corrección del Error 'Unknown control: FilePicker' en Pantalla de Login
- **Responsable:** Antigravity (IA Coding Assistant)
- **Actividades realizadas:**
  - Diagnóstico de la advertencia visual "Unknown control: FilePicker" mostrada al iniciar sesión.
  - Eliminación de la instanciación global prematura de `FilePicker` en `main.py`.
  - Refactorización de `ensure_file_picker_in_overlay` en `ui/views/ventas_view.py` para asociar el `FilePicker` al `page.overlay` únicamente en el momento oportuno al exportar la Nota de Entrega.
- **Verificaciones realizadas:** Prueba automatizada de instanciación aislada de `LoginView`, `DashboardView` y `VentasView`.
- **Estado del proyecto:** En desarrollo. Interfaz de Login y flujo de ventas aislados y limpios sin advertencias de controles desconocidos.

## Reemplazo Definitivo de Flet FilePicker por Diálogo Nativo de Windows (Tkinter)
- **Responsable:** Antigravity (IA Coding Assistant)
- **Actividades realizadas:**
  - Eliminación total de `ft.FilePicker`, listeners `on_result` y referencias a `page.overlay` en `ui/views/ventas_view.py` para resolver de forma definitiva los problemas de sincronización de websocket y `TimeoutException`.
  - Implementación del método síncrono `abrir_dialogo_guardado` utilizando `tkinter.filedialog.asksaveasfilename` configurado con `-topmost` True para garantizar su despliegue al frente en Windows.
  - Integración del flujo en `confirmar_generar_pdf`: lectura de `last_pdf_dir`, despliegue del cuadro de diálogo nativo, generación de la Nota de Entrega PDF en la ubicación elegida, actualización de `last_pdf_dir` en SQLite y notificación con `SnackBar`.
- **Verificaciones realizadas:** Prueba de instanciación síncrona verificando la ausencia de `file_picker` y la presencia del método nativo `abrir_dialogo_guardado`.
- **Estado del proyecto:** En desarrollo. Diálogo de exportación PDF nativo, síncrono y robusto operativo en Windows.

## Conexión Analítica del Dashboard y Módulo de Gestión de Datos & Respaldos (ERS 1.1 & 3.6)
- **Responsable:** Antigravity (IA Coding Assistant)
- **Actividades realizadas:**
  - **Creación de Servicio Analítico (`services/reportes_service.py`):**
    - Implementación de `obtener_metricas_dashboard()` calculando ventas reales del día en USD, productos en almacén, departamentos activos y stock crítico.
    - Implementación de `obtener_top_ventas(rango_temporal, limite)` con filtros dinámicos por tiempo ('Hoy', 'Semana', 'Mes', 'Año') y límite de la dimensión (Top 10 / Top 100).
    - Implementación de `obtener_alertas_stock(minimo=5)` realizando un `JOIN` con la tabla `proveedores` para aislar e incluir el contacto y teléfono del proveedor responsable (ERS 3.6).
  - **Integración en Tiempo Real en Dashboard (`ui/views/dashboard_view.py`):**
    - Conexión de las tarjetas de métricas superiores y renderizado dinámico del Top Más Vendidos con desplegables interactivos.
    - Renderizado de la tabla de Auditoría Preventiva mostrando ítems críticos junto con su proveedor y número telefónico de contacto.
  - **Creación de Módulo de Gestión de Datos (`ui/views/gestion_datos_view.py`):**
    - Diseño de interfaz con tarjetas para Carga Masiva e Importación/Exportación a Excel (ERS 1.1).
    - Implementación del flujo de respaldos utilizando `pandas`, `openpyxl` y el diálogo nativo `tkinter.filedialog.asksaveasfilename` sugiriendo el nombre `Backup_Inventario_YYYYMMDD_HHMMSS.xlsx`.
    - Generación del libro Excel con 3 pestañas (sheets) separadas: `Productos`, `Clientes` y `Proveedores`, guardando la carpeta contenedora en SQLite (`last_excel_dir`).
  - **Enrutamiento de Navegación:** Conexión de la opción "Gestión de Datos" del Sidebar a `GestionDatosView`.
- **Verificaciones realizadas:** Pruebas unitarias de consultas SQL, test de instanciación de vistas y prueba de navegación fluida.
- **Estado del proyecto:** Completo. Motor analítico en tiempo real y sistema de respaldo a Excel operativos.




































