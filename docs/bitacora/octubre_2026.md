# Bitácora de Desarrollo — Octubre 2026

## Actualización del Sistema según la Planificación del 17/10/2026 - 18/10/2026

- **Responsable:** Claude (IA Coding Assistant), orquestando cinco agentes en paralelo sobre worktrees aislados del repositorio.
- **Motivo:** El usuario entregó el documento *"Planificación Sistema de Ventas para el mes de Octubre"* (5 cambios y 6 funciones nuevas) y pidió implementarlo, con dos correcciones verbales que **reemplazan** lo que el PDF propone (ver "Decisiones que se apartan del PDF").
- **Método de trabajo:** El reparto se hizo por **propiedad exclusiva de archivos**, no por tema: cada agente recibió un conjunto de archivos que nadie más podía tocar, de modo que las cinco ramas se fusionaron a `main` sin un solo conflicto. Los dos archivos que varios bloques necesitaban a la vez —el esquema de la base y el servicio de deudas— se escribieron antes de lanzar a los agentes, precisamente para que dejaran de ser terreno compartido.

---

### Decisiones que se apartan del PDF

El PDF proponía usar **F1, F2 y F3 para navegar** por las ventanas. El usuario lo descartó y definió en su lugar:

- **Las flechas** navegan arriba, abajo, izquierda y derecha según los scrolls que haya en la vista; **Ctrl+flecha** va hasta el final de la vista en ese eje.
- **F1 a F6** quedan para los seis íconos de cada ítem: F1 Info, F2 Cobrar, F3 Carrito, F4 Historial Clínico, F5 Editar, F6 Borrar. El mapeo es **fijo para todos los roles**: el Historial Clínico solo existe para administradores, así que para un vendedor F4 simplemente no hace nada. Se prefirió eso a correr la numeración, porque una tecla que cambia de significado según quién tenga la sesión abierta es una trampa para quien aprende los atajos en una máquina y los usa en otra.
- **F6 (eliminar) exige la clave del usuario** de la cuenta con la que está abierta la sesión, cada vez. Se implementó también la **selección múltiple con borrado masivo**, que pide la clave una sola vez por lote.

Otras decisiones tomadas con el usuario durante la sesión:

- **Las flechas navegan solo cuando ningún campo de texto tiene el foco.** Si el cursor está en un campo, las flechas mueven el cursor como en cualquier programa. `Escape` suelta el foco además de limpiar la selección, para que el usuario pueda volver a navegar sin buscar un hueco de la pantalla donde hacer clic.
- **F1–F6 actúan solo sobre el ítem marcado.** Sin selección no hacen nada: adivinar un ítem sería disparar una acción —incluido un borrado— sobre algo que el usuario no eligió.
- **Borrar una deuda también pide la clave**, porque arrastra en cascada su historial de abonos: destruye el registro de cuánto se cobró y quién cobró.
- **En el carrito de Ventas se usa el mismo mapeo canónico** y las teclas sin ícono equivalente quedan inertes (F5 editar, F6 quitar), con el criterio de que la misma tecla haga lo mismo en todas las listas. Quitar un renglón del carrito **no** pide clave: no borra ningún dato del sistema, solo saca un artículo de una venta que todavía no se procesó.
- **El pedido de nueva mercancía suma al stock existente** en vez de fijarlo.
- **La carga masiva lee ahora los costos y el sub-departamento**, para que el pedido no llegue al administrador como información que alguien tenga que retipear.

---

### Preparación: los dos archivos compartidos

- **Migración de esquema (`core/database.py`).** Una sola migración idempotente dentro de `init_db`, que se ejecuta en cada arranque y por lo tanto actualiza también las bases ya instaladas en casa del cliente:
  - `ventas`: `referencia_pago`, `referencia_omitida`, `monto_cobrado`, `porcentaje_descuento` (con signo: negativo = OFF, positivo = ON) y `usuario_nombre`. `total_usd` / `total_bcv` siguen siendo la suma **a precio de lista**, para no perder el precio predeterminado contra el que se calcula el descuento.
  - `clientes`: `contacto_secundario`, que pide la ventana del método "Crédito" y no era un campo del registro original de la cartera.
  - `deudas`, `deuda_abonos` y `deuda_items`, con sus índices.
- **Servicio de deudas (`services/deudas_service.py`).** Puerta de entrada única a esas tres tablas, que necesitaban a la vez el método de pago "Crédito" en Ventas y la ventana "Deudas por Cobrar" en Cartera. La regla que hace confiable al módulo es que **el saldo y el estado son derivados, nunca autoritativos**: se recalculan como `monto_total_usd - Σ abonos` sobre `deuda_abonos`, que es la fuente de verdad del historial. Así, corregir o borrar un abono arrastra el saldo sin dejar desalineada la caché de `deudas.saldo_usd`, que existe solo para poder ordenar y filtrar en SQL. Las comparaciones de monto usan una tolerancia de un centavo: un saldo de milésimas por redondeo es una deuda pagada, no una deuda abierta que el cobrador nunca podría cerrar.

---

### Cambios del PDF

1. **Auditoría Preventiva a ancho completo (`ui/views/dashboard_view.py`, `services/reportes_service.py`).** La ventana pasó de media pantalla a ancho completo, al estilo del modo "Agrupado" del Inventario: descripción general completa en dos líneas (`max_lines=2` con elipsis), chips de código/referencia/descripción corta, departamento y marca, y el mínimo indicando si proviene del umbral propio del producto o del global. El dict de alertas publica ahora `referencia`, `descripcion_general` y `marca`, que la consulta ya leía pero no exponía.
2. **Inteligencia de Negocio a ancho completo**, apilada debajo de Auditoría.
3. **Previsualización del paso 3 compacta (`ui/views/inventario_view.py`).** Filas pegadas, una línea por campo, sin scroll y sin alto fijo: toda la información entra en una sola ventana. **"Descripción General" es la única excepción**, con alto reservado para más de 300 caracteres. Importante para quien lea esto después: el espaciado grande que se quitó se había introducido a propósito para arreglar un desborde de esa casilla, y ese arreglo sigue vivo — el valor continúa en un contenedor de ancho acotado con envoltura multilínea.
4. **Tarjeta de actualización de la Tasa BCV en el Inicio**, primera por la izquierda de las cuatro, replicando la vista del panel de Inventario y delegando la edición en `BaseView.mostrar_modal_tasa_bcv`.
5. **Atajos de teclado** — ver "Decisiones que se apartan del PDF" y "Atajos de teclado" más abajo.

### Funciones nuevas del PDF

1. **Ventas Diarias (`ui/views/dashboard_view.py`, `services/reportes_service.py`).** Lista de las ventas del día entre las cuatro tarjetas y la Auditoría, con fecha y hora, descripción corta de todos los artículos separados por coma, método de pago, referencia (solo cuando no es efectivo), cantidad de artículos y monto total pagado. La concatenación se arma en Python recorriendo el detalle ordenado por `id`, porque `GROUP_CONCAT` no garantiza el orden en SQLite. `monto_cobrado` puede venir en NULL en ventas anteriores a esta actualización, y en ese caso cae con elegancia al total de la moneda del método de pago.
2. **Deudas por Cobrar (`ui/views/cartera_view.py`).** Tercera pestaña de Cartera, con el orden de columnas del boceto: fecha límite (con el "!" de vencida), monto a cobrar —que es el **saldo vivo**, no el monto original—, cédula/RIF, nombre, teléfono y el resto del directorio, más el ítem acreditado, la fecha de creación y la cuenta de usuario que originó la deuda. Las filas van por fecha límite ascendente: las más urgentes primero, que es el orden en que hay que salir a cobrar. Botones Cobrar (abonos parciales con historial), Editar (solo fecha límite y monto total; el saldo y el estado no son editables porque el servicio los deriva) y Borrar (confirmación de la cascada y después clave del usuario).
3. **Marcador y sombreado del ítem.** Ver "Atajos de teclado".
4. **Referencia de pago obligatoria y método "Crédito" (`ui/views/ventas_view.py`, `services/ventas_service.py`, `services/cart_manager.py`).** Todo método distinto de Efectivo exige referencia, con omisión confirmada en una ventana aparte. "Crédito" cobra en USD, se ofrece solo en Venta Formal y solo con cliente vinculado, y al elegirlo abre la ventana del compromiso de pago (fecha límite, contacto, dirección, contacto secundario y correo, auto-rellenados desde el cliente cuando existen). Si el usuario cambia el tipo de venta a Mostrador con Crédito seleccionado, el método vuelve a Efectivo en lugar de quedar en un estado inválido.
5. **Descuento.** Un solo diálogo de cobro con la casilla del monto auto-rellenada según el método y su gemela "Descuento". El porcentaje se muestra en rojo como `-33,75% OFF` cuando el monto manual queda por debajo del precio de lista y en verde como `+11,23% ON` cuando queda por encima. El piso es la suma de costos del carrito; con el método Crédito el límite es `-5%` ("solo se puede aplicar hacia arriba").
6. **Generador de Archivo por Nueva Mercancía (`services/pedidos_service.py`, `ui/views/gestion_datos_view.py`).** Disponible para todos los roles —es el punto del requisito: el empleado arma el pedido sin poder modificar el stock— y **no escribe nada en la base**. El usuario busca un ítem ya registrado y solo completa costo, precio de venta, marca y cantidad; proveedor y fecha de recepción se piden una sola vez al cerrar. El Excel resultante entra por la Carga Masiva existente sin mapeo manual, y los encabezados se **derivan** de `importacion_service` en vez de repetir literales, para que el formato no se bifurque en dos definiciones que luego se desincronizan. El borrador vive en memoria aislado por `session_id`, igual que los carritos.

---

### Correcciones de defectos encontradas durante el trabajo

- **`ventas.fecha` se guardaba en UTC (`services/ventas_service.py`).** El `DEFAULT CURRENT_TIMESTAMP` de SQLite escribe UTC mientras el resto del sistema trabaja en hora local, y los reportes que preguntan por "hoy" comparan contra `DATE('now','localtime')`. En Venezuela (UTC-4) eso significaba que **una venta hecha después de las 20:00 hora local se guardaba con la fecha del día siguiente y desaparecía del "hoy"** de la tarjeta de Ventas del Día, del Top de Inteligencia de Negocio y de la lista nueva de Ventas Diarias. Es el mismo defecto que se corrigió en septiembre para `productos.created_at`. `procesar_venta` pasa ahora la fecha explícita en hora local, con migración idempotente marcada en `app_settings` para no aplicarse dos veces y volver a desplazar las fechas. Lo encontró el agente del área de Inicio al implementar Ventas Diarias.
- **Los diálogos de `BaseView` y de Gestión de Datos seguían con el patrón heredado.** El modal global de la Tasa BCV y los tres modales del flujo de importación (mapeo de columnas, proveedores faltantes y aviso de error) montaban el `AlertDialog` en `page.overlay` alternando `open`, que en Flet 0.86 **no dibuja el cierre** — el defecto que en septiembre dejaba un diálogo pegado en pantalla o activo pero invisible, recibiendo clics sobre botones que el usuario ya no veía. En el flujo de importación es peor que en otras pantallas porque los modales se encadenan: uno que no se cierra de verdad se queda encima y se come los clics del siguiente paso. Los helpers `abrir_dialogo` / `cerrar_dialogo` subieron a `BaseView` para que cualquier vista que herede ya los tenga en vez de volver a descubrirlos, y se agregó una guarda de regresión sobre el archivo de Gestión de Datos, porque es fácil reintroducir el patrón viejo copiando un bloque existente.
- **`abrir_dialogo` apilaba el mismo modal dos veces.** Lo encontró un test: sin guarda, un segundo clic en el botón que abre el modal lo apilaba dos veces y hacían falta dos cierres para sacarlo de pantalla, de modo que el usuario cancela, el diálogo sigue ahí y parece que el botón no responde.
- **Los abonos se guardaban sin firma (`ui/views/dashboard_view.py`).** El Dashboard construía `CarteraView` sin pasarle `user_data`, así que `deuda_abonos.usuario_nombre` quedaba en NULL y se perdía justo el dato que el requisito pide mostrar en la lista: desde qué cuenta se cobró. Regresión silenciosa — la interfaz se ve y funciona igual, y el hueco aparece semanas después al auditar una deuda sin firma.
- **`clientes.contacto_secundario` no se escribía (`services/cartera_service.py`).** La columna existía y la lista de deudas ya la leía por JOIN, pero ningún servicio público la grababa: la ventana de crédito lo pedía, el vendedor lo tecleaba, la venta se guardaba y el dato se perdía en silencio. El teléfono de respaldo nunca aparecía en la ficha justo cuando hay que salir a cobrar.

---

### Atajos de teclado

El modelo vive en `ui/components/teclado_nav.py` como **lógica pura, sin Flet**: traduce una pulsación a una *intención* y deja que la vista decida cómo ejecutarla. Está separado así porque las mismas teclas tienen que funcionar en cuatro listas distintas (Inventario separado, Inventario agrupado, carrito de Ventas y Deudas por Cobrar), y si la decisión de "qué significa esta tecla" viviera en cada vista tendríamos cuatro interpretaciones que se van separando con el tiempo. El modelo de selección vive aparte, en `ui/components/seleccion_lista.py`, igualmente desacoplado de la interfaz.

Tres detalles que son invisibles en una captura de pantalla y fáciles de romper al tocar la interfaz, cada uno con test propio:

- **`RegistroFoco` usa un conjunto y no una bandera booleana.** Los eventos de foco llegan desordenados: al pasar de un campo a otro, Flet puede entregar el `on_focus` del nuevo antes que el `on_blur` del anterior. Con una bandera, ese cruce la dejaría en falso teniendo el cursor todavía dentro de un campo, y las flechas empezarían a mover la pantalla mientras el usuario escribe.
- **`ControlTeclado` guarda una referencia estable al handler.** `self.manejar` crea un método ligado nuevo en cada acceso, de modo que la comparación por identidad de la guarda de reinstalación era siempre falsa, el control acababa encadenado a sí mismo y **una sola flecha se procesaba cientos de veces**. Lo encontró un test.
- **Los destinos de scroll son invocables, no controles guardados.** La tabla se reconstruye en cada repintado, así que un control capturado al instalar el teclado es un control que ya no está en pantalla. Por la misma razón, el Dashboard **olvida** sus destinos en cada construcción del cuerpo y solo la rama de Inicio los vuelve a poner: si sobrevivieran a un cambio de sección, las flechas desplazarían un control desmontado mientras el usuario mira Ventas, sin más síntoma que "las flechas no responden acá".

El handler es `async` porque `Control.scroll_to(...)` es una corutina: uno síncrono la crearía y la descartaría sin ejecutarla y sin lanzar error, de modo que las flechas no harían nada y no habría rastro de por qué. Y el handler de teclado anterior de la página se guarda y se sigue invocando **siempre**, incluso cuando la vista ya consumió la tecla: estas vistas comparten la página con el Dashboard y otra parte de la aplicación puede tener un atajo legítimo sobre la misma tecla.

La clave del usuario se pide con `ui/components/dialogo_clave.py`, genérico para servir a un ítem, a un lote y a cualquier otra acción sensible. La clave **nunca** va a un log, a un snackbar ni al texto de un error, y el mensaje de fallo es genérico sin distinguir casos.

#### Mapeo por lista

| Lista | F1 | F2 | F3 | F4 | F5 | F6 |
|---|---|---|---|---|---|---|
| Inventario | Info | Cobrar | Carrito | Historial (solo admin) | Editar | Borrar (pide clave) |
| Carrito de Ventas | — | — | — | — | Editar renglón | Quitar del carrito (sin clave) |
| Deudas por Cobrar | — | Cobrar | — | — | Editar | Borrar (pide clave) |
| Inicio y Gestión de Datos | — | — | — | — | — | — |

Las teclas sin ícono equivalente quedan **inertes** en vez de recibir una equivalencia inventada: el criterio es que la misma tecla haga lo mismo en todas las listas. Quitar un renglón del carrito no pide clave porque no borra ningún dato del sistema, solo saca un artículo de una venta que todavía no se procesó.

#### Tres defectos del teclado encontrados al cablearlo

Los tres venían del mismo hecho: **el Dashboard reemplaza sus vistas en cada repintado**, y una vista que se fue de la pantalla seguía enganchada al teclado.

- **La cadena de handlers crecía sin tope.** Cada instancia nueva guardaba la anterior como handler previo, así que una sola pulsación recorría todas las instancias pasadas y las viejas seguían actuando sobre controles desmontados. El síntoma concreto: tras un `rebuild_ui()` en Ventas, F5 y F6 se ejecutaban **dos veces**, y la segunda abría un diálogo sobre una tabla fuera de pantalla. Se resolvió dando a cada vista una `identidad` lógica: dos controles con la misma identidad son la misma pantalla reconstruida, de modo que el nuevo **releva** al viejo —heredando su handler previo, para no costarle el teclado al Dashboard que estaba debajo— en lugar de encadenarse a él.
- **Una vista fuera de pantalla seguía accionando.** En Inventario, una **F2 pulsada mientras el usuario miraba Ventas** la procesaba la vista anterior y mandaba a cobrar un producto que ya no tenía delante (F2 sale de la vista por un callback del Dashboard, así que tenía efecto real; las otras cinco morían calladas al no encontrar página). Ahora la vista suelta el teclado al desmontarse, con una bandera de respaldo que no depende de que el aviso de desmontaje llegue.
- **El marcador sobrevivía al repintado.** En Ventas se suelta en `rebuild_ui`, y la selección es **de instancia y no de clase** —al revés que las preferencias de columnas de ese archivo—: compartida, el marcador de un vendedor deshabilitaría los botones de otro conectado al mismo proceso.

---

### Correcciones pedidas al revisar el resultado

El usuario revisó el generador de pedidos y pidió dos cambios, ambos con una trampa que vale documentar.

- **El pedido suma al stock existente** en vez de fijarlo (5 unidades + un pedido de 10 = 15). Lo delicado es que **no se podía convertir toda la Carga Masiva en "sumar"**: ese mismo camino se usa para la carga inicial de catálogo y para restaurar un respaldo, de modo que sumar siempre habría **duplicado las existencias de toda la base cada vez que alguien reimporta un respaldo**, en silencio y sin forma fácil de deshacerlo. La distinción es explícita y verificable en el archivo: se exigen **las dos cosas**, la hoja `Resumen del Pedido` y un literal propio en una celda, porque el nombre de una hoja es un indicio débil (cualquiera puede llamar así a una hoja suya) y ese literal no lo escribe nadie por accidente. Criterio fail-closed: cualquier problema para leer el marcador cae en "fijar", que es lo que no multiplica stock. Se decidió **no** hacerlo idempotente, y está documentado: exigiría recordar qué pedidos ya entraron y mentiría cuando el proveedor manda dos veces la misma remesa.
- **La carga masiva lee los costos y el sub-departamento**, reutilizando `normalizar_costo` y `validar_costo_obligatorio` de `core/models.py` en vez de duplicar las reglas. Una fila con existencia y sin costo se **rechaza** con un mensaje que nombra la hoja, la fila y el código — pero solo cuando el archivo trae la columna de costo, porque un archivo viejo que no la menciona no puede volverse inválido de golpe.

**Defecto colateral que apareció ahí y es el más peligroso de esta tanda:** `INSERT OR REPLACE` borra la fila y la vuelve a insertar, así que **toda columna que no viaje en el archivo queda en NULL**. Sin cuidado, al empezar a leer los costos, reimportar un respaldo viejo habría **borrado en silencio los costos y el sub-departamento de todo el catálogo**. Ahora el valor almacenado se conserva cuando la columna no viaja o viaja en blanco. Lo mismo ocurría ya con `alerta_stock_minimo`, que no viaja en ningún archivo y se perdía en cada carga masiva: defecto preexistente, mismo mecanismo, corregido con su test.

### Acceso a Gestión de Datos y contenido del respaldo

Al revisar lo anterior apareció que **"Gestión de Datos" se listaba en el menú para todos los roles**, y ahí viven la Carga Masiva —que reescribe el stock de todo el catálogo— y la Copia de Seguridad. Es decir: un vendedor podía reescribir el inventario **desde el mismo módulo que existe para que no pudiera**, porque el Generador de Pedido se agregó precisamente para que el empleado registre la mercancía sin tocar el stock. Por decisión del usuario, esas dos tarjetas quedan solo para administradores y el Generador sigue visible para todos. Ocultar la tarjeta no es autorizar, así que los dos handlers vuelven a comprobar el rol en el punto donde la acción ocurre, con criterio fail-closed: una vista construida sin usuario esconde las dos operaciones en lugar de habilitarlas.

La **Copia de Seguridad incluye ahora los costos y el sub-departamento**, con los encabezados exactos que la Carga Masiva reconoce. Antes exportaba doce columnas y ninguna era de costo, de modo que restaurar un respaldo en una base vacía perdía los costos de todo el catálogo: el dato que nadie puede reconstruir de memoria. Un respaldo que no se puede reimportar no es un respaldo, y uno que pierde datos por el camino es peor, porque da la tranquilidad sin el respaldo; por eso el test cierra el círculo completo —exporta, vacía la base e importa el propio archivo por el camino real de la Carga Masiva— en vez de limitarse a comprobar que las columnas están.

---

### Pendientes conocidos

- **`proveedor_id` se pierde en el camino del asistente de mapeo** de la importación: ese camino solo tiene el nombre del proveedor, no su ID. El camino heurístico sí lo preserva, porque el respaldo exporta la columna.
- **Dos modales de Ventas siguen con el patrón heredado de diálogos** (`abrir_modal_crear_cliente` y `abrir_modal_buscar_inventario`). Sus handlers de cierre ya liberan el foco, así que la migración a la pila nativa es mecánica.
- **`View.page` es de solo lectura en Flet 0.86**, así que la asignación `vista.page = self.page` que el Dashboard hace dentro de un `try/except` **nunca surte efecto**. Inventario lo resolvió enganchando el teclado al montarse el cuerpo; conviene revisar si alguna otra vista depende de ese `self.page` para algo.
- `celda_acciones_grid` en `inventario_view.py` es código muerto desde antes de esta actualización.
