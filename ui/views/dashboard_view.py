import flet as ft
from ui.views.base_view import BaseView
from ui.views.cartera_view import CarteraView
from ui.views.inventario_view import InventarioView
from ui.views.ventas_view import VentasView
from ui.views.gestion_datos_view import GestionDatosView
from ui.components.dialogo_alcance import (
    ALCANCE_TODOS, DialogoAlcance, DialogoElegirItem, hace_falta_preguntar,
)
from ui.components.pila_dialogos import sincronizar_al_descartar
from ui.components.scroll_nav import build_floating_v_nav, build_inline_h_nav
from ui.components.seleccion_lista import SeleccionLista
from ui.components.teclado_nav import (
    ACCIONES_SOLO_ADMIN, ControlTeclado, etiqueta_atajo, tooltip_con_atajo,
)
from services.bcv_service import obtener_estado_tasa
from services.reportes_service import (
    obtener_metricas_dashboard,
    obtener_top_ventas,
    obtener_ventas_del_dia,
    obtener_alertas_stock,
    obtener_contactos_proveedores,
    obtener_stock_minimo,
    actualizar_stock_minimo,
)
from services.printer_service import (
    detectar_impresora_termica,
    imprimir_ticket_prueba,
    listar_impresoras_sistema,
    guardar_impresora_termica_configurada,
    obtener_impresora_termica_configurada,
    imprimir_reporte_ventas_diarias,
    imprimir_reporte_auditoria,
)

class DashboardView(BaseView):
    """Vista principal de Dashboard adaptada al tema dinámico con navegación interna por módulos."""

    # ERS 3.6: módulo exclusivo de uso administrativo/gerencial.
    ROLES_CON_ACCESO_AUDITORIA = ("administrador", "superadmin", "gerencia")

    # ── Modos de vista de la Auditoría Preventiva ────────────────────────────
    # Los mismos tres que el catálogo de Inventario, y por el mismo pedido del
    # usuario: "poder tener distintos tipos de vistas". Se repiten los nombres
    # a propósito —"separado", "agrupado", "tarjetas"— para que el selector
    # signifique lo mismo en las dos pantallas.
    #
    # El modo por omisión es "agrupado" y no "separado" como en Inventario:
    # esta lista ya venía mostrándose agrupada (descripción completa en dos
    # líneas, chips de código y referencia), y arrancar en otro formato le
    # cambiaría la pantalla de la mañana a quien no pidió nada.
    #
    # A diferencia de Inventario, la elección NO se persiste: `preferencias_service`
    # solo conoce la preferencia del catálogo y no es un archivo de este trabajo.
    # El modo sobrevive a los cambios de sección porque el Dashboard es una sola
    # instancia durante toda la sesión, pero se olvida al cerrar el programa.
    MODOS_VISTA_AUDITORIA = ("separado", "agrupado", "tarjetas")
    MODO_VISTA_AUDITORIA_DEFECTO = "agrupado"

    # ── Acciones de un ítem de la Auditoría ──────────────────────────────────
    # SOLO las de reposición, por decisión expresa del usuario del proyecto:
    # ver detalle, historial clínico, editar y contactar al proveedor. Cobrar y
    # Carrito se descartaron con el criterio de que "es una lista para reponer
    # stock, no para vender", y Borrar no está entre las elegidas.
    #
    # El orden es el de `teclado_nav.ATAJOS_ITEM` (F1 info … F5 editar) y es el
    # mismo en que se dibujan los íconos: la tecla y la posición del ícono
    # cuentan la misma historia. "proveedor" va al final porque NO tiene tecla:
    # no existe en el mapeo canónico, y no se le inventó una ni se reutilizó
    # F2/F3/F6 porque eso rompería la regla de que la misma tecla hace lo mismo
    # en todas las listas de la aplicación. Queda accesible con el mouse.
    ACCIONES_AUDITORIA = ("info", "historial", "editar", "proveedor")

    # Acciones que NO tienen sentido en lote: ver el detalle de cinco productos
    # a la vez no significa nada, el historial de cinco tampoco, y editarlos
    # juntos menos. Cuando el usuario pide aplicarlas a todo lo marcado se le
    # ofrece elegir uno (`DialogoElegirItem`) en vez de mandarlo a desmarcar.
    ACCIONES_AUDITORIA_UNO_A_UNO = ("info", "historial", "editar")

    # Nombre de cada acción EN PALABRAS DEL USUARIO: viaja al tooltip, al
    # título de los diálogos y a la pregunta de alcance, de modo que las tres
    # cosas la nombren igual.
    ETIQUETAS_ACCION_AUDITORIA = {
        "info": "Ver detalle del ítem",
        "historial": "Historial Clínico",
        "editar": "Editar",
        "proveedor": "Contactar proveedor",
    }

    # Ícono de cada acción. Los tres que ya existen en el catálogo conservan el
    # suyo: reconocer el ícono sin leer el tooltip solo funciona si es el mismo
    # dibujo en las dos pantallas.
    ICONOS_ACCION_AUDITORIA = {
        "info": ft.Icons.INFO_OUTLINE_ROUNDED,
        "historial": ft.Icons.HISTORY_ROUNDED,
        "editar": ft.Icons.EDIT_OUTLINED,
        "proveedor": ft.Icons.PHONE_IN_TALK_ROUNDED,
    }

    # ── Botones de acción de la fila ─────────────────────────────────────────
    # Mismos números que el catálogo de Inventario, y por la misma razón: la
    # etiqueta del atajo va SUPERPUESTA en la esquina del cuadrado del ícono,
    # así que la celda de acciones no crece ni a lo ancho ni a lo alto.
    _LADO_BOTON_ACCION = 34
    _TAM_ICONO_ACCION = 20
    _TAM_ETIQUETA_ATAJO = 8

    # Alto reservado al pie de la tabla de Auditoría para que el cluster
    # flotante de navegación vertical no se dibuje encima de la última fila
    # (mismo criterio y mismo valor que en el catálogo de Inventario).
    _HOLGURA_NAV_FLOTANTE = 44

    # El título de la vista activa viaja DENTRO de `build_header()`: una sola
    # franja horizontal con título de la vista + usuario + opciones + salir.
    mostrar_titulo_por_defecto = False

    def __init__(self, user_info: dict = None, on_logout_callback=None):
        self.user_info = user_info or {"username": "usuario", "role": "administrador"}
        self.on_logout_callback = on_logout_callback
        self.current_section = "Inicio"
        self.rango_top_ventas = "Hoy"
        self.limite_top_ventas = 10
        self.sidebar_collapsed = True
        # Destinos de scroll del area de Inicio, capturados al construir el
        # cuerpo. Se guardan para que el teclado los resuelva EN EL MOMENTO de
        # la pulsacion: el cuerpo se reconstruye en cada repintado, asi que un
        # control capturado al instalar el teclado seria uno que ya no esta en
        # pantalla.
        self._scroll_inicio_v = None
        self._scroll_inicio_h = None

        # ── Estado de la lista de Ventas Diarias ─────────────────────────────
        self._modo_vista_ventas_diarias = "separado"  # "separado", "agrupado", "tarjetas"
        self._columnas_ocultables_ventas_diarias = [
            "fecha_hora", "descripcion_corta", "metodo_pago",
            "referencia_pago", "cantidad_articulos", "monto_total",
        ]
        self._columnas_labels_ventas_diarias = {
            "fecha_hora": "Fecha y hora",
            "descripcion_corta": "Descripción Corta",
            "metodo_pago": "Método de Pago",
            "referencia_pago": "Referencia de Pago",
            "cantidad_articulos": "Cantidad de Artículos",
            "monto_total": "Monto Total Pagado",
        }
        self._columnas_visibles_ventas_diarias = {
            k: True for k in self._columnas_ocultables_ventas_diarias
        }

        # ── Estado de la lista de Auditoría Preventiva ──────────────────────
        # Modo de vista elegido y alertas que hay en pantalla, indexadas por
        # código. El índice existe para que una acción invocada por NOMBRE (un
        # atajo de teclado no tiene ninguna fila de la cual sacar el ítem)
        # pueda resolver el producto sin depender del `dict` de un clic.
        self._modo_vista_auditoria = self.MODO_VISTA_AUDITORIA_DEFECTO
        self._alertas_en_pantalla: dict[str, dict] = {}

        # ── Visibilidad de columnas de la lista separada ────────────────────
        # Mismo criterio que el catálogo: "marcador" y "acciones" son
        # estructurales y por eso no figuran entre las ocultables.
        self._columnas_ocultables_auditoria = [
            # "marcador" y "acciones" NO figuran aquí: son estructurales.
            "codigo", "referencia", "descripcion", "nombre_corto",
            "departamento", "marca", "existencia", "minimo",
            "proveedor", "contacto",
        ]
        self._columnas_labels_auditoria = {
            "marcador": "Sel.",
            "codigo": "Código",
            "referencia": "Referencia",
            "descripcion": "Descripción",
            "nombre_corto": "Nombre Corto",
            "departamento": "Depto.",
            "marca": "Marca",
            "existencia": "Stock Actual",
            "minimo": "Mínimo",
            "proveedor": "Proveedor",
            "contacto": "Contacto",
            "acciones": "Acciones",
        }
        self._columnas_visibles_auditoria = {
            k: True for k in self._columnas_ocultables_auditoria
        }

        # ── Pila de diálogos propios del área de Inicio ─────────────────────
        # Es una PILA y no una referencia única porque un diálogo puede abrir
        # otro encima (la pregunta de alcance abre la de "cuál de todos"): al
        # cerrar el de arriba hay que volver a apuntar al de abajo y no
        # perderlo. Los modales que presta la vista de Inventario (detalle,
        # historial, formulario de edición) llevan la suya.
        self._dialogos_inicio: list[ft.AlertDialog] = []

        # Vista de Inventario que presta sus modales a las acciones de la
        # Auditoría. Se crea al primer uso y nunca se dibuja; ver
        # `_vista_inventario_para_modales`.
        self._vista_inventario_auxiliar = None

        # ── Marcador de selección de la lista de Auditoría ──────────────────
        # El modelo vive en `ui.components.seleccion_lista`, el MISMO que usan
        # el catálogo de Inventario, el carrito de Ventas y las Deudas por
        # Cobrar: la mecánica del marcador tiene que ser idéntica en las cuatro
        # listas, y esta vista solo traduce clics y teclas a sus operaciones.
        self._seleccion_auditoria = SeleccionLista(
            on_cambio=self._al_cambiar_seleccion_auditoria,
        )
        # True mientras se está repintando la lista: corta el repintado que el
        # modelo dispararía al descartar marcados fantasma desde dentro del
        # propio repintado (ver `_descartar_marcados_fantasma`).
        self._cargando_filas_auditoria = False

        self._teclado = ControlTeclado(
            # Resolución tardía a propósito: pasar `self.get_current_page`
            # directamente congelaría el método que exista en este instante,
            # de modo que cualquier reemplazo posterior (una subclase, o un
            # doble de prueba que sustituye la página) quedaría ignorado y el
            # teclado buscaría la página por un camino viejo.
            obtener_pagina=lambda e=None: self.get_current_page(e),
            destino_vertical=lambda: self._scroll_inicio_v,
            destino_horizontal=lambda: self._scroll_inicio_h,
            # Modelo de selección de la lista de Auditoría: es lo que hace que
            # [Esc] limpie el marcador y que las teclas de función sepan si hay
            # un ítem sobre el que actuar.
            seleccion=self._seleccion_auditoria,
            # F1, F4 y F5 actúan SOLO sobre el ítem marcado: el punto de
            # entrada recibe el nombre de la acción y resuelve el código él
            # mismo, así que la tecla no tiene que adivinar ninguna fila.
            ejecutar_accion=self._accionar_por_teclado,
            al_limpiar=self.limpiar_seleccion_auditoria,
            # Identidad logica de la vista: el Dashboard la reemplaza en cada
            # repintado, asi que el control nuevo RELEVA al de la instancia
            # anterior en vez de encadenarse a el. Sin esto la cadena de
            # handlers crece sin tope y las instancias viejas siguen actuando
            # sobre controles que ya no estan en pantalla.
            identidad="dashboard",
        )
        super().__init__(route="/dashboard", title="Inicio")

    @property
    def es_admin(self) -> bool:
        """ERS 3.6: acceso al módulo de auditoría/reportes restringido a admin/gerencia."""
        return (self.user_info or {}).get("role") in self.ROLES_CON_ACCESO_AUDITORIA

    def toggle_sidebar(self, e=None):
        """Conmuta el estado minimizado/expandido de la barra lateral."""
        self.sidebar_collapsed = not self.sidebar_collapsed
        self.rebuild_ui()

    def handle_nav_change(self, section_name: str):
        """Cambia la sección activa de la vista principal."""
        self.current_section = section_name
        self.view_title = section_name
        self.rebuild_ui()

    def procesar_venta_desde_inventario(self, producto: dict, e=None):
        """Flujo Directo Inventario→Ventas (ERS 3.3): instancia una nueva nota
        de venta, carga el producto con cantidad=1 y navega a Ventas."""
        from services.cart_manager import crear_nuevo_carrito, agregar_o_actualizar_producto
        sid = self.get_session_id(e)
        crear_nuevo_carrito(sid)
        agregar_o_actualizar_producto(sid, producto, cantidad=1.0)
        self.current_section = "Ventas"
        self.view_title = "Ventas"
        self.rebuild_ui()

    def iniciar_venta_desde_cartera(self, cliente: dict, e=None):
        """Flujo Directo Cartera→Ventas (ERS 3.3): si el cliente ya tiene un
        carrito guardado en curso, lo recupera (evita duplicados mientras el
        cliente resuelve su pago); si no, crea uno nuevo y lo vincula."""
        from services.cart_manager import (
            obtener_todos_los_carritos, cambiar_carrito_activo,
            crear_nuevo_carrito, vincular_cliente_a_carrito,
        )
        sid = self.get_session_id(e)
        carrito_existente = next(
            (cid for cid, c in obtener_todos_los_carritos(sid).items()
             if c.get("cliente") and c["cliente"]["cedula_rif"] == cliente["cedula_rif"]),
            None
        )
        if carrito_existente:
            cambiar_carrito_activo(sid, carrito_existente)
        else:
            crear_nuevo_carrito(sid)
            vincular_cliente_a_carrito(sid, cliente)
        self.current_section = "Ventas"
        self.view_title = "Ventas"
        self.rebuild_ui()

    def get_body(self) -> ft.Control:
        # Los destinos de scroll se olvidan en CADA construcción, y solo la
        # rama de Inicio los vuelve a poner. Es lo que evita el error sutil de
        # esta pantalla: al cambiar de sección, el cuerpo del Inicio deja de
        # estar montado, y un destino que sobreviviera haría que las flechas
        # desplazaran un control invisible mientras el usuario mira Ventas o
        # Inventario. Sin destino, las flechas de esta vista no hacen nada y
        # el teclado se lo cede a la vista anidada, que tiene los suyos.
        self._scroll_inicio_v = None
        self._scroll_inicio_h = None

        # Lo MISMO vale para la selección de la Auditoría: al cambiar de
        # sección la lista deja de estar montada, y un ítem que siguiera
        # marcado haría que una tecla de función abriera un modal sobre una
        # lista que el usuario no tiene delante. Se olvida solo al SALIR del
        # Inicio, nunca al repintarlo: ahí el marcado es justamente lo que hay
        # que conservar.
        if self.current_section != "Inicio":
            self._olvidar_seleccion_auditoria()

        # Selección del contenido principal según la sección activa
        if self.current_section == "Ventas":
            # `get_current_page()` en lugar de `self.page`: este último lanza
            # RuntimeError mientras la vista no está montada en la página, y al
            # ocurrir dentro de `setup_layout()` el módulo caía al panel de
            # "Error al Cargar Módulo" en vez de renderizar Ventas.
            ventas_view = VentasView(
                page=self.get_current_page(),
                user_data=self.user_info,
                on_update_callback=self.rebuild_ui,
            )
            try:
                if self.page:
                    ventas_view.page = self.page
            except (RuntimeError, AttributeError):
                pass
            main_content = ventas_view.get_body()

        elif self.current_section == "Cartera":
            # `user_data` no es decorativo: su nombre de usuario viaja a cada
            # abono de una deuda (`deuda_abonos.usuario_nombre`) para que
            # quede constancia de quién cobró. Sin pasarlo, los cobros se
            # registran sin firma.
            cartera_view = CarteraView(
                on_iniciar_venta=self.iniciar_venta_desde_cartera,
                user_data=self.user_info,
            )
            try:
                if self.page:
                    cartera_view.page = self.page
            except (RuntimeError, AttributeError):
                pass
            main_content = cartera_view.get_body()

        elif self.current_section == "Inventario":
            inv_view = InventarioView(
                on_procesar_venta=self.procesar_venta_desde_inventario,
                es_admin=self.es_admin,
                # `username` namespacea las preferencias de interfaz (modo de
                # vista del catálogo); `rol_usuario` habilita los costos.
                username=(self.user_info or {}).get("username"),
                rol_usuario=(self.user_info or {}).get("role"),
            )
            try:
                if self.page:
                    inv_view.page = self.page
            except (RuntimeError, AttributeError):
                pass
            main_content = inv_view.get_body()

        elif self.current_section == "Gestión de Datos":
            # `user_data` decide aquí quién ve la Carga Masiva y la Copia de
            # Seguridad, que reescriben o se llevan la base entera. Sin
            # pasarlo, la vista aplica su criterio fail-closed y las esconde
            # incluso a un administrador.
            gd_view = GestionDatosView(user_data=self.user_info)
            try:
                if self.page:
                    gd_view.page = self.page
            except (RuntimeError, AttributeError):
                pass
            main_content = gd_view.get_body()

        elif self.current_section == "Inicio":
            # Orden del cuerpo del Inicio (especificación 17/10/2026): las
            # cuatro tarjetas (con la Tasa BCV primera por la izquierda), la
            # ventana "Ventas Diarias", y debajo la Auditoría Preventiva y la
            # Inteligencia de Negocio a ancho completo.
            #
            # "Ventas Diarias" queda FUERA de la restricción de ERS 3.6: es el
            # registro de lo que se vendió hoy, no inteligencia de negocio, y
            # un vendedor necesita consultarlo durante su turno.
            #
            # El cuerpo se crea VACÍO y se llena después. Es la forma de
            # romper un círculo: el panel de Auditoría necesita al cuerpo como
            # destino del cluster de flechas ↑/↓ (el eje vertical es del
            # cuerpo, no de la tabla), y el cuerpo necesita al panel como
            # contenido. Registrando el destino antes de construir las
            # secciones, las flechas de pantalla y las del teclado apuntan al
            # MISMO control, que es la condición para que hagan lo mismo.
            main_content = ft.Column(
                controls=[],
                scroll=ft.ScrollMode.AUTO,
                spacing=20,
            )
            self._scroll_inicio_v = main_content

            secciones_inicio = [
                self.build_metrics_cards(),
                ft.Container(height=10),
                self.build_ventas_diarias(),
            ]
            # ERS 3.6: el panel de Inteligencia de Negocio y Auditoría de Stock
            # es exclusivo para roles administrativos/gerenciales.
            if self.es_admin:
                secciones_inicio.append(self.build_data_sections())
            else:
                secciones_inicio.append(
                    self.create_card(
                        content=ft.Row(
                            controls=[
                                ft.Icon(ft.Icons.LOCK_OUTLINE_ROUNDED, color=self.get_subtext_color()),
                                ft.Text(
                                    "El panel de Inteligencia de Negocio y Auditoría de Stock (ERS 3.6) "
                                    "está reservado para usuarios administrativos/gerenciales.",
                                    color=self.get_subtext_color(), size=13,
                                ),
                            ],
                            spacing=10,
                        ),
                        padding=18, border_radius=16,
                    )
                )
            main_content.controls = secciones_inicio
        else:
            main_content = ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Icon(ft.Icons.CONSTRUCTION_ROUNDED, size=50, color=self.get_accent_color()),
                        ft.Text(f"Módulo de {self.current_section}", size=22, weight=ft.FontWeight.BOLD, color=self.get_text_color()),
                        ft.Text("Esta sección se encuentra actualmente en desarrollo.", color=self.get_subtext_color()),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    alignment=ft.MainAxisAlignment.CENTER,
                    spacing=10,
                ),
                alignment=ft.Alignment.CENTER,
                expand=True,
            )

        # Instalación perezosa: al construirse la vista todavía no hay `page`
        # (se instancia headless y se monta después), así que el primer intento
        # falla sin consecuencias y el siguiente repintado lo engancha.
        # `instalar()` es idempotente.
        self._teclado.instalar()

        return ft.Row(
            controls=[
                self.build_sidebar(),
                ft.Container(
                    content=ft.Column(
                        controls=[
                            self.build_header(),
                            ft.Divider(height=10, color=self.get_border_color()),
                            ft.Container(
                                content=main_content,
                                expand=True,
                            )
                        ],
                        spacing=15,
                        expand=True,
                    ),
                    expand=True,
                    padding=15,
                )
            ],
            expand=True,
            spacing=0,
        )

    def build_sidebar(self) -> ft.Control:
        """Construye el Sidebar flotante redondeado con estado minimizado/expandido y tooltips."""
        nav_items = [
            ("Inicio", ft.Icons.DASHBOARD_ROUNDED),
            ("Ventas", ft.Icons.POINT_OF_SALE_ROUNDED),
            ("Inventario", ft.Icons.INVENTORY_2_ROUNDED),
            ("Cartera", ft.Icons.ACCOUNT_BALANCE_WALLET_ROUNDED),
            ("Gestión de Datos", ft.Icons.DATASET_ROUNDED),
        ]

        item_controls = []
        accent = self.get_accent_color()

        for label, icon in nav_items:
            is_active = (label == self.current_section)
            if is_active:
                bg = accent
                fg = ft.Colors.WHITE
            else:
                bg = None
                fg = self.get_text_color()

            if self.sidebar_collapsed:
                btn = ft.Container(
                    content=ft.Icon(icon, color=fg, size=22),
                    padding=ft.Padding.symmetric(horizontal=10, vertical=12),
                    border_radius=12,
                    bgcolor=bg,
                    alignment=ft.Alignment.CENTER,
                    tooltip=label,
                    on_click=lambda e, l=label: self.handle_nav_change(l),
                )
            else:
                btn = ft.Container(
                    content=ft.Row(
                        controls=[
                            ft.Icon(icon, color=fg, size=20),
                            ft.Text(label, color=fg, weight=ft.FontWeight.W_600 if is_active else ft.FontWeight.NORMAL),
                        ],
                        spacing=12,
                    ),
                    padding=ft.Padding.symmetric(horizontal=15, vertical=12),
                    border_radius=12,
                    bgcolor=bg,
                    on_click=lambda e, l=label: self.handle_nav_change(l),
                )
            item_controls.append(btn)

        if self.sidebar_collapsed:
            header_control = ft.Row(
                controls=[
                    ft.IconButton(
                        icon=ft.Icons.MENU_ROUNDED,
                        icon_color=accent,
                        tooltip="Expandir menú",
                        on_click=self.toggle_sidebar,
                    )
                ],
                alignment=ft.MainAxisAlignment.CENTER,
            )
            sidebar_width = 70
            sidebar_padding = 10
        else:
            header_control = ft.Row(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Icon(ft.Icons.STOREFRONT_ROUNDED, color=accent, size=28),
                            ft.Text("InventoryApp", size=18, weight=ft.FontWeight.BOLD, color=self.get_text_color()),
                        ],
                        spacing=10,
                    ),
                    ft.IconButton(
                        icon=ft.Icons.CHEVRON_LEFT_ROUNDED,
                        icon_color=self.get_subtext_color(),
                        tooltip="Colapsar menú",
                        on_click=self.toggle_sidebar,
                    )
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            )
            sidebar_width = 230
            sidebar_padding = 15

        return ft.Container(
            width=sidebar_width,
            padding=sidebar_padding,
            margin=ft.Margin(10, 10, 5, 10),
            border_radius=16,
            bgcolor=self.get_sidebar_bg(),
            border=ft.Border.all(1, self.get_border_color()),
            shadow=self.get_card_shadow(),
            content=ft.Column(
                controls=[
                    header_control,
                    ft.Divider(height=20, color=self.get_border_color()),
                    ft.Column(controls=item_controls, spacing=5, expand=True),
                ],
                spacing=10,
            )
        )

    def _mostrar_alertas_stock(self, e=None):
        """Resumen rápido de stock crítico desde el ícono de notificaciones
        (antes era un `print` de marcador de posición)."""
        try:
            total = len(obtener_alertas_stock())
        except Exception:
            total = 0
        if total:
            self.show_alert_info(f"{total} producto(s) con stock crítico. Revise Inicio → Auditoría de Stock.", e)
        else:
            self.show_alert_success("Sin alertas de stock activas.", e)

    def build_header(self) -> ft.Control:
        """Franja superior ÚNICA: título de la vista · usuario · opciones de
        interfaz · cerrar sesión.

        El bloque de título toma el ancho sobrante y elide con puntos
        suspensivos, mientras la zona de acciones va `tight` para que en
        ventanas angostas los botones nunca salgan de pantalla."""
        accent = self.get_accent_color()
        role_label = self.user_info.get('role', 'usuario').capitalize()

        user_badge = ft.Container(
            content=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.PERSON, color=accent, size=22),
                    ft.Text(f"{self.user_info.get('username')} | {role_label}", weight=ft.FontWeight.BOLD, color=self.get_text_color()),
                ],
                spacing=8,
            ),
            bgcolor=self.get_card_bg(),
            border=ft.Border.all(1, self.get_border_color()),
            padding=ft.Padding.symmetric(horizontal=12, vertical=6),
            border_radius=20,
        )

        # Indicador / Configuración rápida de impresora térmica (MP80-12)
        info_imp = detectar_impresora_termica()
        imp_ok = bool(info_imp and info_imp.get("conectada"))
        imp_nom = info_imp["nombre"] if info_imp else "No detectada"

        printer_btn = ft.Container(
            content=ft.Row(
                controls=[
                    ft.Icon(
                        ft.Icons.PRINT if imp_ok else ft.Icons.PRINT_DISABLED_OUTLINED,
                        color=ft.Colors.GREEN_400 if imp_ok else ft.Colors.GREY_500,
                        size=18,
                    ),
                    ft.Text(
                        "Térmica 80mm" if imp_ok else "Sin Impresora",
                        size=11,
                        weight=ft.FontWeight.W_500,
                        color=self.get_text_color(),
                    ),
                ],
                tight=True,
                spacing=5,
            ),
            bgcolor=self.get_card_bg(),
            padding=ft.Padding.symmetric(horizontal=10, vertical=6),
            border_radius=20,
            border=ft.Border.all(1, self.get_border_color()),
            tooltip=f"Impresora Térmica: {imp_nom} ({'Conectada' if imp_ok else 'No detectada'}). Clic para configurar o probar.",
            on_click=self.abrir_dialogo_configuracion_impresora,
        )

        notifications_icon = ft.IconButton(
            icon=ft.Icons.NOTIFICATIONS_OUTLINED,
            icon_color=ft.Colors.AMBER_500,
            tooltip="Alertas de Stock Crítico",
            on_click=self._mostrar_alertas_stock,
        )

        theme_toggle_btn = ft.IconButton(
            icon=ft.Icons.LIGHT_MODE_OUTLINED if self.is_dark else ft.Icons.DARK_MODE_OUTLINED,
            icon_color=self.get_text_color(),
            tooltip="Alternar Modo Claro / Oscuro",
            on_click=self.toggle_theme,
        )

        color_options = [
            ("Azul", "#2196F3", ft.Colors.BLUE_400),
            ("Verde", "#4CAF50", ft.Colors.GREEN_400),
            ("Rojo", "#E91E63", ft.Colors.PINK_400),
            ("Naranja", "#FF9800", ft.Colors.ORANGE_400),
        ]

        color_menu_items = []
        for name, hex_val, display_color in color_options:
            color_menu_items.append(
                ft.PopupMenuItem(
                    content=ft.Row(
                        controls=[
                            ft.Container(width=16, height=16, border_radius=8, bgcolor=display_color),
                            ft.Text(name, color=self.get_text_color()),
                        ],
                        spacing=10,
                    ),
                    on_click=lambda e, h=hex_val: self.change_seed_color(h),
                )
            )

        color_picker_btn = ft.PopupMenuButton(
            icon=ft.Icons.PALETTE_OUTLINED,
            icon_color=accent,
            tooltip="Seleccionar Color de Acento",
            items=color_menu_items,
        )

        logout_btn = ft.IconButton(
            icon=ft.Icons.LOGOUT_ROUNDED,
            icon_color=ft.Colors.RED_400 if self.is_dark else ft.Colors.RED_600,
            tooltip="Cerrar Sesión",
            on_click=lambda e: self.on_logout_callback() if self.on_logout_callback else None,
        )

        header_title = self.current_section

        # Título de la vista actual en un solo bloque. El texto lleva `expand` para
        # que sea él (y no los botones) el que ceda ancho y elida si la ventana es angosta.
        bloque_titulo = ft.Container(
            content=ft.Row(
                controls=[
                    ft.Text(
                        header_title,
                        size=20,
                        weight=ft.FontWeight.BOLD,
                        color=accent,
                        no_wrap=True,
                        max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS,
                        expand=True,
                    ),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            expand=True,
        )

        return ft.Row(
            controls=[
                bloque_titulo,
                ft.Row(
                    controls=[
                        user_badge,
                        printer_btn,
                        notifications_icon,
                        theme_toggle_btn,
                        color_picker_btn,
                        logout_btn,
                    ],
                    spacing=6,
                    tight=True,
                )
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def abrir_dialogo_configuracion_impresora(self, e=None):
        """Abre el diálogo modal de configuración de la impresora térmica y prueba de impresión."""
        impresoras = listar_impresoras_sistema()
        opciones = [ft.dropdown.Option("", "(Detección Automática de Térmica)")]
        for imp in impresoras:
            nombre = imp["nombre"]
            estado = " (Desconectada)" if imp.get("is_offline") else ""
            pred = " [Predeterminada]" if imp.get("is_default") else ""
            opciones.append(ft.dropdown.Option(nombre, f"{nombre}{pred}{estado}"))

        actual = obtener_impresora_termica_configurada()

        dd_impresoras = ft.Dropdown(
            label="Impresora Térmica Seleccionada",
            value=actual if any(o.key == actual for o in opciones) else "",
            options=opciones,
            width=380,
            border_radius=12
        )

        procesando_accion = False

        lbl_estado = ft.Row([
            ft.ProgressRing(width=16, height=16, stroke_width=2),
            ft.Text("Procesando...", size=12, italic=True)
        ], visible=False, tight=True, spacing=8)

        btn_cerrar = ft.TextButton("Cerrar")
        btn_probar = ft.OutlinedButton("Imprimir Ticket de Prueba", icon=ft.Icons.RECEIPT)
        btn_guardar = ft.Button("Guardar", icon=ft.Icons.CHECK,
                                style=ft.ButtonStyle(bgcolor=ft.Colors.GREEN_700, color=ft.Colors.WHITE))

        def _bloquear_botones(bloqueado: bool, mensaje: str = "Procesando..."):
            btn_cerrar.disabled = bloqueado
            btn_probar.disabled = bloqueado
            btn_guardar.disabled = bloqueado
            lbl_estado.visible = bloqueado
            lbl_estado.controls[1].value = mensaje
            try:
                dlg_conf.update()
            except Exception:
                pass

        def guardar_config(ev):
            nonlocal procesando_accion
            if procesando_accion:
                return
            procesando_accion = True
            _bloquear_botones(True, "Guardando configuración...")
            seleccion = dd_impresoras.value or ""
            guardar_impresora_termica_configurada(seleccion)
            self.cerrar_dialogo(dlg_conf, ev)
            self.show_alert_success(f"Configuración guardada: {seleccion or 'Detección automática'}", ev)
            self.rebuild_ui()

        def probar_impresion(ev):
            nonlocal procesando_accion
            if procesando_accion:
                return
            procesando_accion = True
            _bloquear_botones(True, "Enviando ticket a la impresora...")
            try:
                sel = dd_impresoras.value or None
                ok, msg = imprimir_ticket_prueba(nombre_impresora=sel)
                if ok:
                    self.show_alert_success("¡Ticket de prueba enviado con éxito a la impresora!", ev)
                else:
                    self.show_alert_error(f"Error al enviar prueba: {msg}", ev)
            finally:
                procesando_accion = False
                _bloquear_botones(False)

        btn_cerrar.on_click = lambda ev: self.cerrar_dialogo(dlg_conf, ev)
        btn_probar.on_click = probar_impresion
        btn_guardar.on_click = guardar_config

        dlg_conf = ft.AlertDialog(
            title=ft.Row([ft.Icon(ft.Icons.PRINT_ROUNDED, color=ft.Colors.BLUE_400), ft.Text("Configurar Impresora Térmica")]),
            content=ft.Column([
                ft.Text("Seleccione la impresora para emitir los tickets de venta (80mm)."),
                dd_impresoras,
                lbl_estado,
                ft.Text("Compatible con MP80-12, MPT-II, POS-80 (USB / Bluetooth).", size=11, color=self.get_subtext_color()),
            ], tight=True, spacing=12),
            actions=[btn_cerrar, btn_probar, btn_guardar],
            actions_alignment=ft.MainAxisAlignment.END
        )
        self.abrir_dialogo(dlg_conf, e)

    # Ancho común de las tarjetas de la fila superior del Inicio. Cuatro de
    # ellas más el espaciado entran en ~1120 px, el mismo ancho útil que usan
    # las tablas de Auditoría y Ventas Diarias de más abajo.
    ANCHO_TARJETA_METRICA = 265

    def build_tarjeta_tasa_bcv(self) -> ft.Control:
        """Tarjeta pequeña para ver y actualizar la Tasa BCV del día desde el
        Inicio (cambio 4 de la especificación 17/10/2026).

        El Inicio es la primera ventana que se ve al abrir el programa y la
        tasa es el primer dato que el usuario corrige cada mañana, así que la
        tarjeta va a la izquierda de las demás.

        Replica la VISTA del panel BCV de Inventario —indicador verde/ámbar,
        la tasa con su antigüedad y el botón "Actualizar Tasa"— pero delega la
        edición al modal global `BaseView.mostrar_modal_tasa_bcv` en vez de
        repetir la caja de texto del panel: la tarjeta debe ser pequeña y el
        modal ya valida el valor, avisa y reconstruye la vista al guardar."""
        estado = obtener_estado_tasa()
        tasa = estado["tasa"]
        descripcion = estado["descripcion"]

        # Mismo criterio que el panel de Inventario: si la antigüedad se mide
        # en días (no en horas) la tasa está vencida y el indicador pasa a
        # ámbar. Se compara sobre el texto porque es lo que expone el servicio.
        vencida = "día" in descripcion or "días" in descripcion
        color_estado = ft.Colors.AMBER_400 if vencida else ft.Colors.GREEN_400
        icono_estado = (
            ft.Icons.WARNING_AMBER_ROUNDED if vencida
            else ft.Icons.CHECK_CIRCLE_OUTLINE_ROUNDED
        )

        accent = self.get_accent_color()
        valor = f"{tasa:,.2f} Bs/$" if tasa > 0 else "Sin tasa"

        return self.create_card(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Icon(ft.Icons.CURRENCY_EXCHANGE, color=accent, size=32),
                            ft.Column(
                                controls=[
                                    ft.Text(
                                        "Tasa de Cambio BCV", size=11,
                                        color=self.get_subtext_color(), weight=ft.FontWeight.W_600,
                                    ),
                                    ft.Text(
                                        valor, size=20, weight=ft.FontWeight.BOLD,
                                        color=self.get_text_color(),
                                        max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                                    ),
                                ],
                                spacing=2, tight=True, expand=True,
                            ),
                        ],
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Row(
                        controls=[
                            ft.Icon(icono_estado, color=color_estado, size=16),
                            ft.Text(
                                descripcion, size=11, color=color_estado,
                                weight=ft.FontWeight.W_600, max_lines=2,
                                overflow=ft.TextOverflow.ELLIPSIS, expand=True,
                            ),
                        ],
                        spacing=6,
                    ),
                    ft.Button(
                        content=ft.Row(
                            controls=[
                                ft.Icon(ft.Icons.CURRENCY_EXCHANGE, size=16, color=ft.Colors.WHITE),
                                ft.Text("Actualizar Tasa", weight=ft.FontWeight.BOLD, size=13),
                            ],
                            spacing=6, tight=True,
                            alignment=ft.MainAxisAlignment.CENTER,
                        ),
                        style=ft.ButtonStyle(
                            bgcolor=accent,
                            color=ft.Colors.WHITE,
                            shape=ft.RoundedRectangleBorder(radius=12),
                        ),
                        tooltip="Actualizar la tasa BCV del día",
                        on_click=self.mostrar_modal_tasa_bcv,
                    ),
                ],
                spacing=10,
                tight=True,
            ),
            padding=18,
            border_radius=18,
            width=self.ANCHO_TARJETA_METRICA,
        )

    def build_metrics_cards(self) -> ft.Control:
        """Construye las tarjetas de métricas con datos reales de la base de datos."""
        metricas = obtener_metricas_dashboard()

        ventas_val = f"$ {metricas['ventas_hoy_usd']:,.2f}"
        variacion_str = f"{metricas['variacion_pct']:+.1f}% vs ayer" if metricas['ventas_ayer_usd'] > 0 else "Ventas registradas hoy"

        stock_val = f"{metricas['total_unidades']:,.0f} Unidades"
        stock_sub = f"{metricas['total_categorias']} Departamentos"

        criticos_val = f"{metricas['total_criticos']} Críticos"
        criticos_sub = "Requieren reposición" if metricas['total_criticos'] > 0 else "Sin alertas activas"

        cards_data = [
            ("Ventas del Día", ventas_val, variacion_str, ft.Icons.ATTACH_MONEY_ROUNDED, self.get_accent_color()),
            ("Productos en Stock", stock_val, stock_sub, ft.Icons.INVENTORY_ROUNDED, self.get_accent_color()),
            ("Alertas de Stock Bajo", criticos_val, criticos_sub, ft.Icons.WARNING_AMBER_ROUNDED, self.get_accent_color()),
        ]

        card_widgets = []
        for title, value, subtitle, icon, color in cards_data:
            c = ft.Container(
                content=ft.Row(
                    controls=[
                        # Columna izquierda: Icono y Valor
                        ft.Column(
                            controls=[
                                ft.Icon(icon, color=color, size=32),
                                ft.Text(value, size=22, weight=ft.FontWeight.BOLD, color=self.get_text_color()),
                            ],
                            spacing=6,
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        # Columna derecha: Título y Subtítulo
                        ft.Column(
                            controls=[
                                ft.Text(title, size=11, color=self.get_subtext_color(), weight=ft.FontWeight.W_600, text_align=ft.TextAlign.RIGHT),
                                ft.Container(height=8),
                                ft.Text(subtitle, size=11, color=color if "Críticos" in value or "Bajo" in title else self.get_subtext_color(), text_align=ft.TextAlign.RIGHT),
                            ],
                            alignment=ft.MainAxisAlignment.START,
                            horizontal_alignment=ft.CrossAxisAlignment.END,
                            expand=True,
                        )
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                ),
                padding=18,
                width=self.ANCHO_TARJETA_METRICA,
                bgcolor=self.get_card_bg(),
                border_radius=18,
                border=ft.Border.all(1, self.get_border_color()),
                shadow=self.get_card_shadow(),
            )
            card_widgets.append(c)

        # La tarjeta de Tasa BCV encabeza la fila (sugerencia explícita del
        # cliente: "es más cómodo que esté a la izquierda de las demás").
        return ft.Row(
            controls=[self.build_tarjeta_tasa_bcv(), *card_widgets],
            spacing=20,
            wrap=True,
        )

    def _build_selector_columnas_ventas_diarias(self, accent, text_color) -> ft.PopupMenuButton:
        items = []
        for key in self._columnas_ocultables_ventas_diarias:
            item = ft.PopupMenuItem(
                content=ft.Text(self._columnas_labels_ventas_diarias[key]),
                checked=self._columnas_visibles_ventas_diarias.get(key, True),
                on_click=lambda e, k=key: self._toggle_columna_ventas_diarias(k, e),
            )
            items.append(item)

        return ft.PopupMenuButton(
            icon=ft.Icons.VIEW_COLUMN_ROUNDED,
            icon_color=accent,
            tooltip="Mostrar/ocultar columnas de ventas diarias",
            items=items,
        )

    def _toggle_columna_ventas_diarias(self, key: str, e=None):
        visibles = [k for k in self._columnas_ocultables_ventas_diarias if self._columnas_visibles_ventas_diarias.get(k, True)]
        if self._columnas_visibles_ventas_diarias.get(key, True) and len(visibles) <= 1:
            self.show_alert_info("Debe quedar al menos una columna visible.", e)
            return
        self._columnas_visibles_ventas_diarias[key] = not self._columnas_visibles_ventas_diarias.get(key, True)
        self.rebuild_ui()

    def _handle_cambio_modo_ventas_diarias(self, e):
        if e.control.selected:
            self._modo_vista_ventas_diarias = list(e.control.selected)[0]
            self.rebuild_ui()

    def _handle_imprimir_ventas_diarias(self, e):
        if getattr(self, "_imprimiendo_ventas_diarias", False):
            return
        self._imprimiendo_ventas_diarias = True
        self.show_alert_info("Enviando reporte de ventas del día a la impresora térmica...", e)
        try:
            ok, msg = imprimir_reporte_ventas_diarias()
            if ok:
                self.show_alert_success("¡Reporte de Ventas Diarias impreso con éxito!", e)
            else:
                self.show_alert_error(f"Error al imprimir ventas diarias: {msg}", e)
        finally:
            self._imprimiendo_ventas_diarias = False

    def _handle_imprimir_auditoria(self, e):
        if getattr(self, "_imprimiendo_auditoria", False):
            return
        self._imprimiendo_auditoria = True
        self.show_alert_info("Enviando reporte de stock crítico a la impresora térmica...", e)
        try:
            ok, msg = imprimir_reporte_auditoria(stock_minimo=obtener_stock_minimo())
            if ok:
                self.show_alert_success("¡Reporte de Auditoría Preventiva impreso con éxito!", e)
            else:
                self.show_alert_error(f"Error al imprimir auditoría: {msg}", e)
        finally:
            self._imprimiendo_auditoria = False

    def build_ventas_diarias(self) -> ft.Control:
        """Ventana "Ventas Diarias" del Inicio con selector de vista (separado, agrupado, tarjetas),
        selector de columnas visibles e impresión directa en impresora térmica de 80mm."""
        text_color = self.get_text_color()
        subtext = self.get_subtext_color()
        accent = self.get_accent_color()
        border = self.get_border_color()

        ventas = obtener_ventas_del_dia()

        if ventas:
            if self._modo_vista_ventas_diarias == "agrupado":
                grupos = {}
                for v in ventas:
                    met = v.get("metodo_pago") or "Efectivo"
                    if met not in grupos:
                        grupos[met] = []
                    grupos[met].append(v)

                bloques_grupos = []
                for met, items_grupo in grupos.items():
                    tot_usd = sum(float(x.get("monto_total") or 0.0) for x in items_grupo if x.get("moneda") != "Bs")
                    tot_bs = sum(float(x.get("monto_total") or 0.0) for x in items_grupo if x.get("moneda") == "Bs")

                    resumen_txt = []
                    if tot_usd > 0:
                        resumen_txt.append(f"$ {tot_usd:,.2f}")
                    if tot_bs > 0:
                        resumen_txt.append(f"Bs. {tot_bs:,.2f}")
                    txt_totales = " / ".join(resumen_txt) if resumen_txt else "$ 0.00"

                    filas_grp = []
                    for v in items_grupo:
                        simbolo = "Bs" if v["moneda"] == "Bs" else "$"
                        filas_grp.append(
                            ft.Container(
                                content=ft.Row([
                                    ft.Text(v["fecha_hora"], size=11, color=subtext, width=120),
                                    ft.Text(f"#{v['venta_id']:05d}", size=11, weight=ft.FontWeight.BOLD, color=text_color, width=70),
                                    ft.Text(v["descripcion_corta"], size=12, color=text_color, expand=True, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                                    ft.Text(v["referencia_pago"] or "-", size=11, color=subtext, width=110, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                                    ft.Text(f"{simbolo} {v['monto_total']:,.2f}", size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_400, width=100, text_align=ft.TextAlign.RIGHT),
                                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                                padding=ft.Padding.symmetric(vertical=4, horizontal=8),
                                border=ft.Border.only(bottom=ft.BorderSide(1, border)),
                            )
                        )

                    bloques_grupos.append(
                        ft.Container(
                            content=ft.Column([
                                ft.Row([
                                    ft.Row([
                                        ft.Icon(ft.Icons.PAYMENTS_OUTLINED, color=accent, size=18),
                                        ft.Text(met, size=13, weight=ft.FontWeight.BOLD, color=text_color),
                                        ft.Container(
                                            content=ft.Text(f"{len(items_grupo)} venta(s)", size=10, weight=ft.FontWeight.W_600, color=accent),
                                            bgcolor=ft.Colors.with_opacity(0.12, accent),
                                            padding=ft.Padding.symmetric(horizontal=8, vertical=2),
                                            border_radius=8,
                                        ),
                                    ], spacing=6),
                                    ft.Text(f"Subtotal: {txt_totales}", size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_400),
                                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                                ft.Column(filas_grp, spacing=2),
                            ], spacing=6),
                            padding=10,
                            bgcolor=self.get_card_bg(),
                            border=ft.Border.all(1, border),
                            border_radius=12,
                        )
                    )
                contenido = ft.Column(bloques_grupos, spacing=10)

            elif self._modo_vista_ventas_diarias == "tarjetas":
                tarjetas_items = []
                for venta in ventas:
                    simbolo = "Bs" if venta["moneda"] == "Bs" else "$"

                    tarjetas_items.append(
                        ft.Container(
                            content=ft.Column([
                                ft.Row([
                                    ft.Row([
                                        ft.Icon(ft.Icons.RECEIPT_LONG, size=14, color=accent),
                                        ft.Text(f"#{venta['venta_id']:05d}", size=11, weight=ft.FontWeight.BOLD, color=text_color),
                                    ], spacing=4),
                                    ft.Text(venta["fecha_hora"][-5:], size=11, color=subtext),
                                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                                ft.Text(
                                    venta["descripcion_corta"], size=12, color=text_color,
                                    max_lines=2, overflow=ft.TextOverflow.ELLIPSIS
                                ),
                                ft.Row([
                                    ft.Container(
                                        content=ft.Text(venta["metodo_pago"], size=10, weight=ft.FontWeight.W_500, color=subtext),
                                        padding=ft.Padding.symmetric(horizontal=6, vertical=2),
                                        border=ft.Border.all(1, border),
                                        border_radius=6,
                                    ),
                                    ft.Text(
                                        f"{simbolo} {venta['monto_total']:,.2f}",
                                        size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_400
                                    ),
                                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                            ], spacing=6),
                            padding=12,
                            width=260,
                            bgcolor=self.get_card_bg(),
                            border=ft.Border.all(1, border),
                            border_radius=12,
                        )
                    )
                contenido = ft.Row(tarjetas_items, wrap=True, spacing=10)

            else:
                columnas_activas = [k for k in self._columnas_ocultables_ventas_diarias if self._columnas_visibles_ventas_diarias.get(k, True)]
                filas = []
                for venta in ventas:
                    cantidad = venta["cantidad_articulos"]
                    cantidad_txt = (
                        f"{cantidad:,.0f}" if float(cantidad).is_integer() else f"{cantidad:,.2f}"
                    )
                    simbolo = "Bs" if venta["moneda"] == "Bs" else "$"
                    referencia = venta["referencia_pago"]

                    celdas = []
                    for col_key in columnas_activas:
                        if col_key == "fecha_hora":
                            celdas.append(ft.DataCell(ft.Container(
                                content=ft.Text(venta["fecha_hora"], size=12, color=text_color, weight=ft.FontWeight.W_600),
                                width=150,
                            )))
                        elif col_key == "descripcion_corta":
                            celdas.append(ft.DataCell(ft.Container(
                                content=ft.Text(
                                    venta["descripcion_corta"], size=13, color=text_color,
                                    max_lines=2, overflow=ft.TextOverflow.ELLIPSIS,
                                ),
                                width=380,
                                padding=ft.Padding.symmetric(vertical=6),
                            )))
                        elif col_key == "metodo_pago":
                            celdas.append(ft.DataCell(ft.Container(
                                content=ft.Text(venta["metodo_pago"], size=12, color=text_color),
                                width=140,
                            )))
                        elif col_key == "referencia_pago":
                            celdas.append(ft.DataCell(ft.Container(
                                content=ft.Text(
                                    referencia or "-", size=12,
                                    color=text_color if referencia else subtext,
                                    max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                                ),
                                width=160,
                            )))
                        elif col_key == "cantidad_articulos":
                            celdas.append(ft.DataCell(ft.Container(
                                content=ft.Text(cantidad_txt, size=12, color=text_color, weight=ft.FontWeight.W_600),
                                width=130,
                            )))
                        elif col_key == "monto_total":
                            celdas.append(ft.DataCell(ft.Container(
                                content=ft.Text(
                                    f"{simbolo} {venta['monto_total']:,.2f}",
                                    size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_400,
                                ),
                                width=160,
                            )))

                    filas.append(ft.DataRow(cells=celdas))

                columnas_dt = [
                    ft.DataColumn(ft.Text(self._columnas_labels_ventas_diarias[k], color=text_color, weight=ft.FontWeight.BOLD))
                    for k in columnas_activas
                ]

                contenido = ft.DataTable(
                    columns=columnas_dt,
                    rows=filas,
                    data_row_min_height=56,
                    data_row_max_height=80,
                )
        else:
            contenido = ft.Container(
                content=ft.Column([
                    ft.Icon(ft.Icons.RECEIPT_LONG_OUTLINED, color=subtext, size=32),
                    ft.Text("Todavía no se ha registrado ninguna venta hoy.", color=subtext, size=13),
                ], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                padding=30,
            )

        btn_imprimir_ventas = ft.IconButton(
            icon=ft.Icons.PRINT_ROUNDED,
            icon_color=accent,
            tooltip="Imprimir Reporte Diario en Térmica (80mm)",
            on_click=self._handle_imprimir_ventas_diarias,
        )

        btn_modo_vista = ft.SegmentedButton(
            selected=[self._modo_vista_ventas_diarias],
            segments=[
                ft.Segment(
                    value="separado",
                    label=ft.Text("Separado", size=11, weight=ft.FontWeight.W_600),
                    icon=ft.Icon(ft.Icons.VIEW_COLUMN_ROUNDED, size=16),
                ),
                ft.Segment(
                    value="agrupado",
                    label=ft.Text("Agrupado", size=11, weight=ft.FontWeight.W_600),
                    icon=ft.Icon(ft.Icons.VIEW_LIST_ROUNDED, size=16),
                ),
                ft.Segment(
                    value="tarjetas",
                    label=ft.Text("Tarjetas", size=11, weight=ft.FontWeight.W_600),
                    icon=ft.Icon(ft.Icons.GRID_VIEW_ROUNDED, size=16),
                ),
            ],
            on_change=self._handle_cambio_modo_ventas_diarias,
        )

        tarjeta = self.create_card(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Row([
                                ft.Icon(ft.Icons.RECEIPT_LONG_ROUNDED, color=accent),
                                ft.Text("Ventas Diarias", size=15, weight=ft.FontWeight.BOLD, color=text_color),
                                ft.Text(
                                    f"{len(ventas)} venta(s) hoy", size=12,
                                    color=subtext, weight=ft.FontWeight.W_600,
                                ),
                            ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                            ft.Row([
                                btn_imprimir_ventas,
                                btn_modo_vista,
                                self._build_selector_columnas_ventas_diarias(accent, text_color),
                            ], spacing=6, wrap=True, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        wrap=True,
                    ),
                    ft.Divider(height=10, color=self.get_border_color()),
                    self._tabla_a_ancho_completo(contenido),
                ],
                spacing=10,
            ),
            padding=15,
            border_radius=18,
            col={"sm": 12, "lg": 12},
        )

        return ft.ResponsiveRow(controls=[tarjeta], spacing=20)

    def build_data_sections(self) -> ft.Control:
        """Auditoría Preventiva e Inteligencia de Negocio, ambas a ANCHO COMPLETO
        y en ese orden (especificación 17/10/2026, cambios 1 y 2).

        Antes convivían a `lg: 6` (media pantalla cada una) y la Auditoría solo
        alcanzaba a mostrar el nombre corto del producto, que es justo lo que el
        cliente pedía ampliar. Con `lg: 12` las dos tarjetas ocupan el ancho
        completo y se apilan dentro del mismo `ResponsiveRow`."""
        text_color = self.get_text_color()
        accent = self.get_accent_color()

        # ── 1. Inteligencia de Negocio (Top Más Vendidos) ────────────────────
        def handle_cambio_rango(e):
            self.rango_top_ventas = e.control.value
            self.rebuild_ui()

        def handle_cambio_limite(e):
            self.limite_top_ventas = int(e.control.value)
            self.rebuild_ui()

        dd_rango = ft.Dropdown(
            value=self.rango_top_ventas,
            options=[
                ft.dropdown.Option("Hoy"),
                ft.dropdown.Option("Semana"),
                ft.dropdown.Option("Mes"),
                ft.dropdown.Option("Año"),
            ],
            width=110,
            content_padding=5,
            border_radius=12,
            border_color=self.get_border_color(),
            focused_border_color=accent,
        )
        dd_rango.on_change = handle_cambio_rango

        dd_limite = ft.Dropdown(
            value=str(self.limite_top_ventas),
            options=[
                ft.dropdown.Option("10", "Top 10"),
                ft.dropdown.Option("100", "Top 100"),
            ],
            width=100,
            content_padding=5,
            border_radius=12,
            border_color=self.get_border_color(),
            focused_border_color=accent,
        )
        dd_limite.on_change = handle_cambio_limite


        top_products = obtener_top_ventas(self.rango_top_ventas, self.limite_top_ventas)

        if top_products:
            top_rows = []
            for item in top_products:
                top_rows.append(
                    ft.DataRow(
                        cells=[
                            ft.DataCell(ft.Text(item["posicion"], weight=ft.FontWeight.BOLD, color=text_color)),
                            ft.DataCell(ft.Text(item["nombre_corto"], color=text_color)),
                            ft.DataCell(ft.Text(item["categoria"], color=self.get_subtext_color())),
                            ft.DataCell(ft.Text(f"{item['total_vendido']:.0f} Uds", color=accent, weight=ft.FontWeight.BOLD)),
                        ]
                    )
                )

            top_content = ft.DataTable(
                columns=[
                    ft.DataColumn(ft.Text("#", color=text_color)),
                    ft.DataColumn(ft.Text("Producto", color=text_color)),
                    ft.DataColumn(ft.Text("Departamento", color=text_color)),
                    ft.DataColumn(ft.Text("Cantidad Vendida", color=text_color)),
                ],
                rows=top_rows,
            )
        else:
            top_content = ft.Container(
                content=ft.Column([
                    ft.Icon(ft.Icons.INFO_OUTLINED, color=self.get_subtext_color(), size=32),
                    ft.Text(f"No hay ventas registradas para el período '{self.rango_top_ventas}'.", color=self.get_subtext_color(), size=13)
                ], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                padding=30
            )

        seccion_inteligencia = self.create_card(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Row([
                                ft.Icon(ft.Icons.LEADERBOARD_ROUNDED, color=accent),
                                ft.Text("Inteligencia de Negocio", size=15, weight=ft.FontWeight.BOLD, color=text_color),
                            ], spacing=8),
                            ft.Row([dd_rango, dd_limite], spacing=5)
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        wrap=True
                    ),
                    ft.Divider(height=10, color=self.get_border_color()),
                    top_content,
                ],
                spacing=10,
            ),
            padding=15,
            border_radius=18,
            col={"sm": 12, "lg": 12},
        )

        # ── 2. Auditoría Preventiva (Stock Crítico + Contacto Proveedor - ERS 3.6) ──
        seccion_auditoria = self._build_panel_auditoria(accent, text_color)

        # La Auditoría va primero: es la ventana que el cliente consulta al
        # abrir el programa (qué reponer hoy). La Inteligencia de Negocio queda
        # debajo, también a ancho completo (cambio 2 de la especificación).
        return ft.ResponsiveRow(
            controls=[
                seccion_auditoria,
                seccion_inteligencia,
            ],
            spacing=20,
        )

    def _tabla_a_ancho_completo(self, tabla: ft.Control) -> ft.Control:
        """Envuelve una tabla ancha en su propio eje HORIZONTAL.

        Los anchos de las tablas del Inicio están calculados para entrar
        completas en una pantalla normal (sin deslizable horizontal, como pide
        la especificación), pero en una ventana angosta la tabla se recortaría
        contra el borde de la tarjeta. Este `Row` con scroll AUTO solo aparece
        cuando hace falta. No rompe la regla de "un solo dueño por eje": el
        cuerpo del Inicio es dueño del eje VERTICAL y este Row del HORIZONTAL."""
        fila = ft.Row(controls=[tabla], scroll=ft.ScrollMode.AUTO, expand=True)
        # Destino de RESPALDO para las flechas horizontales. Hay dos tablas con
        # eje horizontal propio en el Inicio y una sola pulsación no puede
        # desplazar las dos: la dueña de las flechas es la lista de Auditoría
        # Preventiva, que se registra ella misma en `_build_panel_auditoria`
        # (es la lista con la que el usuario trabaja: marca, acciona y
        # recorre). Esta asignación solo cubre el caso en que la Auditoría no
        # está en pantalla —un vendedor, que por ERS 3.6 no la ve— para que las
        # flechas sigan moviendo algo útil en vez de quedarse muertas.
        if self._scroll_inicio_h is None:
            self._scroll_inicio_h = fila
        return fila

    # =========================================================================
    # AUDITORÍA PREVENTIVA — LISTA COMPLETA (ERS 3.6)
    # =========================================================================
    # Pedido textual del usuario del proyecto: "En Inicio, en Auditoría
    # Preventiva, hay que hacer lo mismo que en las otras vistas para poder
    # tener distintos tipos de vistas, acciones incluso, y navegación con
    # botones ... Es mejor que esta vista sea más manejable, más revisable".
    #
    # O sea: lo que era una tabla pasiva pasa a comportarse como la lista del
    # catálogo de Inventario. El formato lo elige el usuario con el selector de
    # modo, el eje horizontal es exclusivo de esta lista (el vertical sigue
    # siendo del cuerpo del Inicio, un solo dueño por eje) y los anchos siguen
    # calculados para entrar en una pantalla normal sin deslizable.

    # ─────────────────────────────────────────────────────────────────────────
    # MARCADOR Y SOMBREADO DE LA FILA (igual que en el catálogo)
    # ─────────────────────────────────────────────────────────────────────────
    # Mecánica, tal como la pidió el usuario del proyecto ("marcador y
    # selección múltiple: sí, igual que Inventario"):
    #   - Un clic en cualquier parte de la fila (no solo en la casilla) marca
    #     el ítem: se sombrea y la casilla izquierda queda marcada. El marcado
    #     sobrevive al desplazamiento horizontal porque es estado del modelo,
    #     no del control que recibió el clic.
    #   - Solo hay DOS formas de deseleccionar: clic DENTRO de la casilla
    #     marcada, o [Esc].
    #   - Con un ítem marcado, solo ese ítem puede accionar sus íconos; los de
    #     las demás filas quedan deshabilitados VISIBLEMENTE.
    #   - Sin nada marcado, todo funciona como antes: es la regla "Importante"
    #     del PDF y la más fácil de romper al cablear la lista.
    def _al_cambiar_seleccion_auditoria(self):
        """Repinta la lista cuando la selección cambió DE VERDAD.

        Lo llama el modelo (`SeleccionLista.on_cambio`), así que cualquier
        camino que altere la selección —clic, casilla, [Esc], cambio de
        sección— termina repintando por aquí y no hay que acordarse en cada
        handler. Se repinta SOLO la lista y no el Inicio entero: una selección
        no cambia la tasa BCV ni las ventas del día, y un `rebuild_ui()` por
        cada clic en una fila volvería a consultar la base cuatro veces."""
        if self._cargando_filas_auditoria:
            # Ya estamos dentro del repintado (ver `_descartar_marcados_fantasma`).
            return
        if self.current_section != "Inicio" or not hasattr(self, "_vista_auditoria"):
            # Fuera del Inicio no hay lista que repintar: el cuerpo que la
            # contenía ya no está montado.
            return
        self._actualizar_barra_seleccion_auditoria()
        self._cargar_filas_auditoria()
        self.safe_update()

    def _olvidar_seleccion_auditoria(self) -> None:
        """Deja la selección como recién abierta la pantalla.

        Se usa al salir del Inicio. También se vacía el índice de alertas: un
        índice de una lista desmontada solo puede servir para accionar sobre
        algo que ya no está en pantalla.

        El MODO de selección no se toca a propósito: que el conmutador de
        selección múltiple esté encendido es una elección del usuario, igual
        que el modo de vista, y apagárselo por haber pasado por Ventas sería
        deshacerle algo que él puso."""
        self._alertas_en_pantalla = {}
        self._seleccion_auditoria.limpiar()

    def seleccionar_item_auditoria(self, codigo: str, e=None):
        """Clic en cualquier parte de la fila: marca (nunca desmarca).

        Reintenta `instalar()` (es idempotente) porque la página puede haber
        llegado después de `get_body()`, y [Esc] es justamente la tecla que
        hace falta en cuanto hay algo marcado."""
        self._teclado.instalar(e)
        self._seleccion_auditoria.seleccionar(codigo)

    def alternar_item_auditoria(self, codigo: str, e=None):
        """Clic DENTRO de la casilla marcadora: marca o desmarca."""
        self._teclado.instalar(e)
        self._seleccion_auditoria.alternar(codigo)

    def limpiar_seleccion_auditoria(self, e=None):
        """Quita la selección (tecla [Esc] o botón de la barra)."""
        self._seleccion_auditoria.limpiar()
        self._actualizar_barra_seleccion_auditoria()
        self.safe_update(e)

    def alternar_modo_seleccion_auditoria(self, e=None):
        """Entra o sale del modo de selección múltiple.

        Las transiciones las decide el modelo compartido: entrar CONSERVA lo
        que ya estaba marcado (el ítem que el usuario venía señalando pasa a
        ser el primero del lote) y salir limpia, porque volver al marcador
        único con cinco ítems marcados dejaría un estado que ese modo no puede
        representar y una lista sombreada a medias."""
        self._teclado.instalar(e)
        self._seleccion_auditoria.alternar_modo()
        self._actualizar_barra_seleccion_auditoria()
        self.safe_update(e)

    # ── Barra de estado de la selección ─────────────────────────────────────
    def _build_barra_seleccion_auditoria(self, accent, subtext) -> ft.Row:
        """Controles para ver y manejar la selección sin adivinar.

        El conmutador va CON ETIQUETA VISIBLE, no como un ícono suelto: en el
        catálogo de Inventario el usuario no encontró la selección múltiple
        justamente por eso —un ícono gris sin texto, pegado a la leyenda "Sin
        selección", se lee como un indicador de estado y no como algo que se
        pueda pulsar—, y ya se corrigió allí. Una función que existe pero nadie
        descubre es una función que no existe."""
        self._lbl_seleccion_auditoria = ft.Text(
            self._seleccion_auditoria.descripcion_estado(), size=11, color=subtext,
        )
        self._btn_modo_seleccion_auditoria = ft.Button(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.CHECKLIST_ROUNDED, size=16),
                    ft.Text("Selección múltiple", size=11, weight=ft.FontWeight.W_600),
                ],
                spacing=6, tight=True,
            ),
            style=ft.ButtonStyle(
                bgcolor=ft.Colors.TRANSPARENT,
                color=subtext,
                shape=ft.RoundedRectangleBorder(radius=12),
                side=ft.BorderSide(1, subtext),
                padding=ft.Padding.symmetric(horizontal=10, vertical=4),
            ),
            tooltip="Marcar varios ítems a la vez para accionar sobre todos",
            on_click=self.alternar_modo_seleccion_auditoria,
        )
        self._btn_limpiar_seleccion_auditoria = ft.IconButton(
            ft.Icons.HIGHLIGHT_OFF_ROUNDED,
            icon_color=subtext,
            tooltip="Quitar la selección (equivale a pulsar Esc)",
            visible=False,
            on_click=self.limpiar_seleccion_auditoria,
        )
        self._barra_seleccion_auditoria = ft.Row(
            controls=[
                self._btn_modo_seleccion_auditoria,
                self._lbl_seleccion_auditoria,
                self._btn_limpiar_seleccion_auditoria,
            ],
            spacing=4,
        )
        return self._barra_seleccion_auditoria

    def _actualizar_barra_seleccion_auditoria(self):
        """Sincroniza etiqueta, ícono y visibilidad con el estado del modelo."""
        if not hasattr(self, "_lbl_seleccion_auditoria"):
            return
        accent = self.get_accent_color()
        subtext = self.get_subtext_color()
        multiple = self._seleccion_auditoria.es_multiple

        self._lbl_seleccion_auditoria.value = self._seleccion_auditoria.descripcion_estado()
        self._lbl_seleccion_auditoria.color = (
            accent if self._seleccion_auditoria.hay_seleccion else subtext
        )
        # El botón dice en qué modo está y qué hace el próximo clic, en vez de
        # limitarse a cambiar de color: un botón que solo se tiñe deja al
        # usuario adivinando si ya lo pulsó.
        color_modo = accent if multiple else subtext
        self._btn_modo_seleccion_auditoria.content = ft.Row(
            [
                ft.Icon(
                    ft.Icons.CHECKLIST_RTL_ROUNDED if multiple else ft.Icons.CHECKLIST_ROUNDED,
                    size=16,
                ),
                ft.Text(
                    "Salir de selección múltiple" if multiple else "Selección múltiple",
                    size=11, weight=ft.FontWeight.W_600,
                ),
            ],
            spacing=6, tight=True,
        )
        self._btn_modo_seleccion_auditoria.style = ft.ButtonStyle(
            bgcolor=ft.Colors.with_opacity(0.14, accent) if multiple else ft.Colors.TRANSPARENT,
            color=color_modo,
            shape=ft.RoundedRectangleBorder(radius=12),
            side=ft.BorderSide(1, color_modo),
            padding=ft.Padding.symmetric(horizontal=10, vertical=4),
        )
        self._btn_modo_seleccion_auditoria.tooltip = (
            "Volver a marcar un solo ítem"
            if multiple
            else "Marcar varios ítems a la vez para accionar sobre todos"
        )
        self._btn_limpiar_seleccion_auditoria.visible = self._seleccion_auditoria.hay_seleccion

    def _descartar_marcados_fantasma(self) -> None:
        """Olvida los ítems marcados que ya no están en la lista.

        Sin esto, el código de un producto que salió de la reposición —porque
        el usuario acaba de subirle el stock— seguiría marcado y bloquearía los
        íconos de todas las filas vivas por una selección que no se ve en
        ninguna parte. El repintado que el modelo dispararía se corta con
        `_cargando_filas_auditoria`: ya estamos dentro del repintado, y volver
        a entrar sería recursión."""
        fantasmas = [
            c for c in self._seleccion_auditoria.seleccionados
            if c not in self._alertas_en_pantalla
        ]
        if not fantasmas:
            return
        self._cargando_filas_auditoria = True
        try:
            self._seleccion_auditoria.descartar(fantasmas)
        finally:
            self._cargando_filas_auditoria = False

    # ── Diálogos propios del área de Inicio ─────────────────────────────────
    def _paleta_dialogo_inicio(self) -> dict:
        """Paleta que esperan los componentes de diálogo (`dialogo_alcance`,
        `producto_detalle_modal`): se pasa por parámetro para que el
        componente no herede de `BaseView` ni conozca el tema."""
        return {
            "texto": self.get_text_color(),
            "subtexto": self.get_subtext_color(),
            "acento": self.get_accent_color(),
            "fondo": self.get_card_bg(),
            "borde": self.get_border_color(),
        }

    def _abrir_dialogo_inicio(self, dialogo: ft.AlertDialog, e=None):
        """Apila un diálogo del Inicio y lo muestra sobre el que hubiera debajo."""
        # Un diálogo que Flet descarte solo (tocando fuera, si no es modal)
        # dejaría un fantasma en esta pila y el siguiente cierre descartaría el
        # diálogo equivocado: el usuario pulsa Cancelar, no se cierra nada
        # visible y la pantalla parece colgada. Ver `ui/components/pila_dialogos.py`.
        sincronizar_al_descartar(dialogo, self._dialogos_inicio)
        if dialogo not in self._dialogos_inicio:
            self._dialogos_inicio.append(dialogo)
        self.abrir_dialogo(dialogo, e)

    def _cerrar_dialogo_inicio(self, dialogo: ft.AlertDialog = None, e=None):
        """Descarta el diálogo del tope (o el indicado) y deja activo el de abajo."""
        if dialogo is None:
            dialogo = self._dialogos_inicio[-1] if self._dialogos_inicio else None
        if dialogo is None:
            return
        if dialogo in self._dialogos_inicio:
            self._dialogos_inicio.remove(dialogo)
        # `BaseView.cerrar_dialogo` llama a `pop_dialog()` ANTES de bajar
        # `open`, que es el orden que exige Flet 0.86.
        self.cerrar_dialogo(dialogo, e)

    # ─────────────────────────────────────────────────────────────────────────
    # ACCIONES DE UN ÍTEM DE LA AUDITORÍA
    # ─────────────────────────────────────────────────────────────────────────
    # Cada ícono de la fila entra por `ejecutar_accion_auditoria`, con un
    # nombre estable y un solo argumento (el código del ítem): así los atajos
    # de teclado se enlazan al ítem marcado sin tener que alcanzar closures
    # anónimas enterradas en el cargador de filas, y los dos caminos —el clic y
    # la tecla— recorren exactamente el mismo código.

    def _vista_inventario_para_modales(self, e=None):
        """Vista de Inventario auxiliar que le presta sus modales a esta lista.

        Tres de las cuatro acciones ya existen en el catálogo —ver detalle,
        historial clínico y editar—, y la de editar arrastra los tres pasos del
        formulario con su validación y su manejo de la pila de diálogos de Flet
        0.86. Copiarlas aquí sería duplicar centenares de líneas y, peor, dos
        criterios que se van a desincronizar en cuanto alguien corrija uno. En
        vez de eso se instancia UNA vez una vista de Inventario que no se
        dibuja nunca y se le piden sus modales.

        Tres detalles que no son opcionales:

        1. El registro de foco se COMPARTE con el de esta vista. Sin eso, al
           escribir en el formulario de edición las flechas desplazarían el
           Inicio que está detrás, que es exactamente el defecto que el
           registro existe para evitar.
        2. `_refrescar_tabla` se sustituye por el refresco de ESTA lista: al
           guardar el formulario, la lista que tiene que enterarse de que el
           stock cambió es la Auditoría, no el catálogo que no está en
           pantalla.
        3. Su cuerpo NUNCA se monta, así que su propio `ControlTeclado` no se
           instala y no compite por el teclado con el del Dashboard.
        """
        vista = self._vista_inventario_auxiliar
        if vista is None:
            vista = InventarioView(
                es_admin=self.es_admin,
                username=(self.user_info or {}).get("username"),
                rol_usuario=(self.user_info or {}).get("role"),
            )
            vista._teclado.foco = self._teclado.foco
            vista._refrescar_tabla = self._refrescar_auditoria
            self._vista_inventario_auxiliar = vista
        # La página puede llegar después de la construcción (la vista se
        # instancia headless y se monta más tarde), así que se reasigna en cada
        # uso en vez de confiar en la que hubiera al crearla.
        pagina = self.get_current_page(e)
        if pagina is not None:
            try:
                vista.page = pagina
            except (RuntimeError, AttributeError):
                pass
        return vista

    def _refrescar_auditoria(self, e=None):
        """Vuelve a consultar las alertas y repinta la lista.

        Lo invoca el formulario de edición al guardar: subirle la existencia a
        un producto tiene que sacarlo de la lista de reposición en el momento,
        no al siguiente cambio de sección."""
        self._cargar_filas_auditoria()
        self.safe_update(e)

    def _alerta_en_pantalla(self, codigo: str) -> dict | None:
        """Alerta de la lista por su código, o `None` si ya no está."""
        return self._alertas_en_pantalla.get((codigo or "").strip())

    def _etiqueta_item_auditoria(self, codigo: str) -> str:
        """Descripción corta con la que se nombra un ítem ante el usuario.

        El código solo no le dice nada a quien atiende el mostrador: viaja al
        diálogo de "cuál de todos" y a los contactos del proveedor."""
        item = self._alerta_en_pantalla(codigo) or {}
        return item.get("nombre_corto") or item.get("descripcion_general") or codigo

    def accion_info_auditoria(self, codigo: str, e=None):
        """Ficha completa del producto, en el MISMO modal que usa el catálogo
        (el ítem se relee con el rol, así que los costos llegan solo a quien
        corresponde)."""
        self._vista_inventario_para_modales(e)._abrir_modal_detalle({"codigo": codigo}, e)

    def accion_historial_auditoria(self, codigo: str, e=None):
        """Historial Clínico de Producto (ERS 3.6), exclusivo admin/gerencia."""
        self._vista_inventario_para_modales(e)._abrir_modal_historial(codigo, e)

    def accion_editar_auditoria(self, codigo: str, e=None):
        """Formulario de edición del producto. Es la acción con la que el
        usuario corrige el stock o el umbral que disparó la alerta."""
        self._vista_inventario_para_modales(e)._abrir_flujo_edicion(codigo, e)

    def accion_proveedor_auditoria(self, codigo: str, e=None):
        """Contacto de reposición del proveedor del ítem."""
        self._mostrar_contactos_proveedores([codigo], e)

    def _handlers_accion_auditoria(self) -> dict:
        return {
            "info": self.accion_info_auditoria,
            "historial": self.accion_historial_auditoria,
            "editar": self.accion_editar_auditoria,
            "proveedor": self.accion_proveedor_auditoria,
        }

    def _validar_accion_auditoria(self, accion: str, codigo: str, e=None) -> str | None:
        """Comprobaciones comunes a TODOS los caminos de una acción.

        Devuelve el código normalizado si la acción puede ejecutarse sobre él,
        o `None` si no aplica. Lanza `ValueError` si la acción no existe en
        esta lista, porque eso es un error de programación y no una situación
        del usuario. Está aparte porque la misma acción llega por tres
        caminos —el ícono, la tecla y el ítem elegido en un diálogo— y las tres
        tienen que pasar por las mismas puertas."""
        if accion not in self._handlers_accion_auditoria():
            raise ValueError(f"Acción de auditoría desconocida: {accion!r}")
        # El Historial Clínico es exclusivo admin/gerencia (ERS 3.6). Se
        # comprueba por la lista compartida y no por el rol a mano para que el
        # criterio sea el mismo que en el catálogo de Inventario.
        if accion in ACCIONES_SOLO_ADMIN and not self.es_admin:
            return None
        # Hoy el panel COMPLETO es admin/gerencia, así que sin ese rol no hay
        # lista ni íconos; la guarda está igual porque quien entre por nombre o
        # por teclado no pasa por los íconos.
        if not self.es_admin:
            return None
        codigo = (codigo or "").strip()
        if not codigo:
            return None
        # Se vuelve a comprobar la regla del marcador aunque el ícono ya venga
        # deshabilitado: tiene que valer también para quien invoque la acción
        # por teclado o por código, no solo para quien hace clic.
        if not self._seleccion_auditoria.puede_accionar(codigo):
            self.show_alert_info(
                "Hay otro ítem marcado. Haga clic en su casilla o pulse Esc para liberarlo.",
                e,
            )
            return None
        return codigo

    def ejecutar_accion_auditoria(self, accion: str, codigo: str, e=None) -> bool:
        """Punto de entrada ÚNICO de los íconos de la fila.

        Con VARIOS ítems marcados pregunta SIEMPRE sobre cuáles actúa
        (`DialogoAlcance`), tal como lo pidió el usuario del proyecto: el clic
        fue sobre el ícono de una fila concreta, pero puede querer actuar sobre
        todo el lote. Adivinar es inaceptable en las dos direcciones — aplicar
        a todo lo que creía ser uno, y aplicar a uno lo que creía ser todo y
        quedarse con el trabajo a medias sin avisar.

        Devuelve `False` cuando la acción no aplica, sin dejar nada a medias."""
        codigo = self._validar_accion_auditoria(accion, codigo, e)
        if codigo is None:
            return False
        marcados = self._seleccion_auditoria.seleccionados
        if hace_falta_preguntar(marcados):
            self._preguntar_alcance_auditoria(accion, codigo, marcados, e)
            return True
        return self._ejecutar_accion_auditoria_directa(accion, codigo, e)

    def _ejecutar_accion_auditoria_directa(self, accion: str, codigo: str, e=None) -> bool:
        """La acción sobre UN ítem, sin más preguntas.

        Es donde terminan los tres caminos: el ícono cuando no hay ambigüedad,
        la tecla con un solo ítem marcado, y el ítem que el usuario eligió en
        `DialogoAlcance` o en `DialogoElegirItem`."""
        codigo = self._validar_accion_auditoria(accion, codigo, e)
        if codigo is None:
            return False
        self._handlers_accion_auditoria()[accion](codigo, e)
        return True

    def ejecutar_accion_auditoria_sobre_seleccionado(self, accion: str, e=None) -> bool:
        """Misma acción, aplicada a LO MARCADO: es lo que invocan las teclas.

        Sin ítem marcado no hace NADA (devuelve `False`): adivinar una fila
        sería abrir un formulario de edición sobre algo que el usuario no
        eligió. Con uno, actúa sobre él. Con varios, la tecla significa "sobre
        todo lo marcado", así que se resuelve como el lote — y para las
        acciones que no tienen sentido en lote, eso es preguntar cuál."""
        marcados = self._seleccion_auditoria.seleccionados
        if not marcados:
            return False
        if len(marcados) == 1:
            return self._ejecutar_accion_auditoria_directa(accion, marcados[0], e)
        return self._aplicar_accion_auditoria_a_todos(accion, marcados, e)

    def _aplicar_accion_auditoria_a_todos(self, accion: str, marcados, e=None) -> bool:
        """La acción sobre TODO el lote marcado.

        Dos destinos distintos según la acción:

        - Ver detalle, Historial y Editar NO tienen sentido en lote (ver cinco
          fichas a la vez no significa nada, y editar cinco productos juntos
          menos). Se muestra `DialogoElegirItem` con la descripción corta de
          cada uno, en vez de mandar al usuario a desmarcar lo que acababa de
          marcar.
        - Contactar proveedor SÍ lo tiene, y es su mejor forma: un bloque por
          proveedor involucrado, sin repetir ninguno.
        """
        if accion not in self._handlers_accion_auditoria():
            raise ValueError(f"Acción de auditoría desconocida: {accion!r}")
        if accion in ACCIONES_SOLO_ADMIN and not self.es_admin:
            return False
        if not self.es_admin:
            return False
        marcados = [c for c in marcados if c]
        if not marcados:
            return False
        if accion in self.ACCIONES_AUDITORIA_UNO_A_UNO:
            self._preguntar_cual_item_auditoria(accion, marcados, e)
            return True
        self._mostrar_contactos_proveedores(marcados, e)
        return True

    # ── Las dos preguntas sobre qué ítems actúa una acción ──────────────────
    def _preguntar_alcance_auditoria(self, accion: str, codigo: str, marcados, e=None):
        """"¿Solo este, o los N marcados?" (`DialogoAlcance`)."""
        etiqueta = self.ETIQUETAS_ACCION_AUDITORIA[accion]
        comp = DialogoAlcance(
            titulo=etiqueta,
            accion=etiqueta,
            codigo=codigo,
            marcados=list(marcados),
            on_elegir=lambda alcance, ev=None: self._resolver_alcance_auditoria(
                accion, codigo, list(marcados), alcance, ev or e,
            ),
            # Cerrar es responsabilidad de quien apiló: el componente no sabe
            # de la pila de esta vista.
            on_cerrar=lambda ev=None: self._cerrar_dialogo_inicio(comp.dialogo, ev or e),
            paleta=self._paleta_dialogo_inicio(),
        )
        self._abrir_dialogo_inicio(comp.dialogo, e)

    def _resolver_alcance_auditoria(self, accion, codigo, marcados, alcance, e=None) -> bool:
        if alcance == ALCANCE_TODOS:
            return self._aplicar_accion_auditoria_a_todos(accion, marcados, e)
        return self._ejecutar_accion_auditoria_directa(accion, codigo, e)

    def _preguntar_cual_item_auditoria(self, accion: str, marcados, e=None):
        """"¿Cuál de todos?" (`DialogoElegirItem`), para las acciones que se
        hacen de a uno.

        Las etiquetas llevan la descripción corta del producto y no solo el
        código: a quien atiende el mostrador, un código no le dice nada."""
        etiqueta = self.ETIQUETAS_ACCION_AUDITORIA[accion]
        comp = DialogoElegirItem(
            titulo=etiqueta,
            accion=etiqueta,
            marcados=list(marcados),
            etiquetas={c: self._etiqueta_item_auditoria(c) for c in marcados},
            on_elegir=lambda codigo, ev=None: self._ejecutar_accion_auditoria_directa(
                accion, codigo, ev or e,
            ),
            on_cerrar=lambda ev=None: self._cerrar_dialogo_inicio(comp.dialogo, ev or e),
            paleta=self._paleta_dialogo_inicio(),
        )
        self._abrir_dialogo_inicio(comp.dialogo, e)

    def _accionar_por_teclado(self, accion: str, e=None) -> bool:
        """Lo que invocan las teclas de función sobre esta lista.

        El mapeo de `teclado_nav.ATAJOS_ITEM` es FIJO y común a todas las
        listas (F1 info, F2 cobrar, F3 carrito, F4 historial, F5 editar, F6
        borrar), así que aquí quedan vivas F1, F4 y F5, y F2, F3 y F6 quedan
        INERTES porque esta lista no tiene esos íconos. Una tecla sin ícono
        equivalente no hace nada, que es muy distinto de hacer otra cosa: si
        F3 añadiera al carrito desde la lista de reposición, la misma tecla
        significaría cosas distintas en dos pantallas del mismo programa.

        La guarda de sección no es decorativa: el Dashboard aloja a las demás
        vistas, y una tecla pulsada mientras el usuario mira Ventas no puede
        accionar una lista del Inicio que ya no está en pantalla."""
        if self.current_section != "Inicio":
            return False
        if accion not in self.ACCIONES_AUDITORIA:
            return False
        return self.ejecutar_accion_auditoria_sobre_seleccionado(accion, e)

    # ── Contactar proveedor ─────────────────────────────────────────────────
    def _mostrar_contactos_proveedores(self, codigos, e=None):
        """Contactos de reposición de los ítems `codigos`, UNO POR PROVEEDOR.

        Criterio (es la única de las cuatro acciones que SÍ tiene sentido en
        lote): reponer no se hace producto por producto sino llamada por
        llamada, así que con varios ítems marcados lo útil es la lista de
        proveedores a los que hay que llamar, cada uno con los productos que le
        corresponden y su existencia actual. Un mismo proveedor no aparece dos
        veces aunque se le compren cuatro de los productos marcados; la
        agrupación la hace el servicio por `proveedores.id`."""
        contactos = obtener_contactos_proveedores(codigos)
        texto = self.get_text_color()
        subtext = self.get_subtext_color()
        accent = self.get_accent_color()

        if not contactos:
            self.show_alert_info(
                "No se encontraron los ítems seleccionados para buscar su proveedor.", e,
            )
            return

        bloques = []
        for contacto in contactos:
            sin_datos = not (contacto["telefono"] or contacto["correo"])
            datos = " · ".join(
                d for d in (contacto["contacto"], contacto["telefono"], contacto["correo"]) if d
            )
            bloques.append(
                ft.Container(
                    content=ft.Column([
                        ft.Text(
                            contacto["empresa"], size=14, weight=ft.FontWeight.BOLD,
                            color=texto, no_wrap=False,
                        ),
                        ft.Text(
                            datos or "Sin datos de contacto cargados",
                            size=12, color=ft.Colors.AMBER_400 if sin_datos else subtext,
                            no_wrap=False, selectable=True,
                        ),
                        ft.Text("A reponer:", size=11, color=subtext),
                        ft.Column([
                            ft.Text(
                                f"· {p['nombre_corto']} ({p['codigo']}) — quedan {p['existencia']:.0f}",
                                size=12, color=texto, no_wrap=False,
                            )
                            for p in contacto["productos"]
                        ], spacing=2, tight=True),
                    ], spacing=4, tight=True),
                    padding=10,
                    border_radius=12,
                    border=ft.Border.all(1, self.get_border_color()),
                )
            )

        dialogo = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.Icons.PHONE_IN_TALK_ROUNDED, color=accent),
                ft.Text(
                    f"Contactar proveedor ({len(contactos)})",
                    color=texto, weight=ft.FontWeight.BOLD,
                ),
            ], spacing=10),
            content=ft.Container(
                # Un ÚNICO scroll vertical sobre un alto acotado: un lote de
                # quince proveedores no puede estirar el diálogo fuera de la
                # pantalla, y dos scrolls anidados competirían por el gesto.
                content=ft.Column(
                    controls=bloques, spacing=10, scroll=ft.ScrollMode.AUTO,
                ),
                width=520,
                height=min(420, 150 * max(1, len(bloques))),
            ),
            actions=[ft.TextButton(
                "Cerrar", on_click=lambda ev: self._cerrar_dialogo_inicio(dialogo, ev),
            )],
            bgcolor=self.get_card_bg(),
        )
        self._abrir_dialogo_inicio(dialogo, e)

    def _build_panel_auditoria(self, accent, text_color) -> ft.Control:
        """Tarjeta de la Auditoría Preventiva: el parámetro de stock mínimo, el
        selector de modo de vista, los clusters de flechas y la lista.

        La tarjeta se arma SIEMPRE con los mismos controles y es
        `_cargar_filas_auditoria` quien decide qué se dibuja dentro según el
        modo elegido. Separarlo así permite cambiar de formato sin reconstruir
        el Inicio entero (y sin volver a consultar las métricas, la tasa BCV y
        las ventas del día, que no tienen nada que ver con el cambio)."""
        subtext = self.get_subtext_color()
        stock_minimo_actual = obtener_stock_minimo()

        def handle_guardar_stock_minimo(e):
            try:
                nuevo_val = float((inp_stock_minimo.value or "0").replace(",", "."))
                actualizar_stock_minimo(nuevo_val)
                self.show_alert_success(e, f"Stock mínimo actualizado a {nuevo_val:.0f}.")
                self.rebuild_ui()
            except ValueError as ex:
                self.show_alert_error(e, str(ex))

        # Enlazado al registro de foco: mientras el cursor esté aquí, las
        # flechas editan el número en vez de desplazar la pantalla.
        inp_stock_minimo = self._teclado.foco.enlazar(ft.TextField(
            label="Stock mínimo",
            value=f"{stock_minimo_actual:.0f}",
            width=110,
            keyboard_type=ft.KeyboardType.NUMBER,
            border_radius=12,
            content_padding=8,
            on_submit=handle_guardar_stock_minimo,
        ), "stock_minimo")
        btn_guardar_stock_minimo = ft.IconButton(
            icon=ft.Icons.SAVE_OUTLINED, icon_color=accent,
            tooltip="Guardar nuevo stock mínimo parametrizado (ERS 3.6)",
            on_click=handle_guardar_stock_minimo,
        )

        self._dt_auditoria = ft.DataTable(
            columns=[self._build_columna_auditoria(k, accent, text_color)
                     for k in self._columnas_orden_visible_auditoria()],
            rows=[],
            # Explícito aunque sea el valor por omisión: todas las filas llevan
            # `on_select_change` (clic en cualquier parte de la fila), y con la
            # columna de casillas propia de la tabla activada se dibujaría una
            # SEGUNDA casilla junto a nuestro marcador.
            show_checkbox_column=False,
        )
        # ── Separación de ejes ──────────────────────────────────────────────
        # Esta Row es la ÚNICA dueña del eje horizontal de la lista, y el
        # cuerpo del Inicio (`_scroll_inicio_v`) del vertical. La Column
        # intermedia NO desplaza: existe solo para darle al cluster flotante un
        # destino cuando el panel se construye suelto (lo hacen las pruebas,
        # que llaman a `build_data_sections()` sin pasar por `get_body()`).
        self._tabla_auditoria_row = ft.Row(
            controls=[self._dt_auditoria], scroll=ft.ScrollMode.AUTO, expand=True,
        )
        self._tabla_auditoria_col = ft.Column(
            controls=[self._tabla_auditoria_row], tight=True,
        )
        # Las flechas ←/→ del teclado desplazan ESTA lista: es la que el
        # usuario recorre, marca y acciona. Se asigna sin condición y después
        # de que Ventas Diarias haya puesto su respaldo, así que gana siempre
        # que la Auditoría esté en pantalla (ver `_tabla_a_ancho_completo`).
        self._scroll_inicio_h = self._tabla_auditoria_row

        # Los clusters de botones apuntan a los MISMOS controles que las
        # flechas del teclado: tienen que hacer exactamente lo mismo.
        self._nav_h_auditoria = build_inline_h_nav(self._tabla_auditoria_row, accent)
        self._nav_v_auditoria = build_floating_v_nav(
            self._scroll_inicio_v or self._tabla_auditoria_col, accent,
        )
        # Sin esta holgura el cluster vertical flotante se dibuja encima del
        # texto de la última fila.
        self._tabla_auditoria_con_holgura = ft.Container(
            content=self._tabla_auditoria_col,
            padding=ft.Padding.only(bottom=self._HOLGURA_NAV_FLOTANTE),
        )
        self._vista_auditoria = ft.Container()

        self._btn_modo_vista_auditoria = ft.SegmentedButton(
            selected=[self._modo_vista_auditoria],
            segments=[
                ft.Segment(
                    value="separado",
                    label=ft.Text("Separado", size=11, weight=ft.FontWeight.W_600),
                    icon=ft.Icon(ft.Icons.VIEW_COLUMN_ROUNDED, size=16),
                ),
                ft.Segment(
                    value="agrupado",
                    label=ft.Text("Agrupado", size=11, weight=ft.FontWeight.W_600),
                    icon=ft.Icon(ft.Icons.VIEW_LIST_ROUNDED, size=16),
                ),
                ft.Segment(
                    value="tarjetas",
                    label=ft.Text("Tarjetas", size=11, weight=ft.FontWeight.W_600),
                    icon=ft.Icon(ft.Icons.GRID_VIEW_ROUNDED, size=16),
                ),
            ],
            on_change=self._handle_cambio_modo_vista_auditoria,
        )

        # Se construye ANTES de cargar las filas para que el estado de la
        # selección ya tenga dónde mostrarse en el primer pintado.
        self._build_barra_seleccion_auditoria(accent, subtext)
        self._actualizar_barra_seleccion_auditoria()

        self._cargar_filas_auditoria(text_color, accent)

        return self.create_card(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Row([
                                ft.Icon(ft.Icons.REPORT_PROBLEM_ROUNDED, color=accent),
                                ft.Text(
                                    f"Auditoría Preventiva (Stock Crítico < {stock_minimo_actual:.0f})",
                                    size=15, weight=ft.FontWeight.BOLD, color=text_color,
                                ),
                            ], spacing=10),
                            ft.Row([
                                self._barra_seleccion_auditoria,
                                self._nav_h_auditoria,
                                self._btn_modo_vista_auditoria,
                                self._build_selector_columnas_auditoria(accent, text_color),
                                ft.IconButton(
                                    icon=ft.Icons.PRINT_ROUNDED,
                                    icon_color=accent,
                                    tooltip="Imprimir Reporte de Stock Crítico en Térmica (80mm)",
                                    on_click=self._handle_imprimir_auditoria,
                                ),
                                inp_stock_minimo,
                                btn_guardar_stock_minimo,
                                # Seis grupos de controles en una sola barra:
                                # `wrap` es lo que evita que en una ventana
                                # angosta los últimos queden fuera de pantalla
                                # en vez de bajar a una segunda línea.
                            ], spacing=8, wrap=True),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        wrap=True,
                    ),
                    ft.Divider(height=10, color=self.get_border_color()),
                    self._vista_auditoria,
                ],
                spacing=10,
            ),
            padding=15,
            border_radius=18,
            col={"sm": 12, "lg": 12},
        )

    # ── Columnas de la lista separada ───────────────────────────────────────
    def _columnas_orden_visible_auditoria(self) -> list[str]:
        """Orden fijo de columnas, filtrando las que el usuario desactivó.

        El "marcador" ABRE siempre la lista y "acciones" la CIERRA, y ninguna
        de las dos se puede ocultar. La razón de ser del marcador es que, al
        desplazarse a la derecha, el usuario deje de confundir las filas entre
        sí: tiene que ser la primera columna. Y una lista de reposición sin sus
        íconos vuelve a ser la tabla pasiva que el usuario pidió cambiar."""
        return (
            ["marcador"]
            + [
                k for k in self._columnas_ocultables_auditoria
                if self._columnas_visibles_auditoria.get(k, True)
            ]
            + ["acciones"]
        )

    def _build_columna_auditoria(self, key: str, accent, text_color) -> ft.DataColumn:
        color = accent if key in ("acciones", "marcador") else text_color
        return ft.DataColumn(ft.Text(
            self._columnas_labels_auditoria[key], color=color, weight=ft.FontWeight.BOLD,
        ))

    def _build_selector_columnas_auditoria(self, accent, text_color) -> ft.PopupMenuButton:
        """Mostrar/ocultar columnas, igual que en el catálogo. Solo tiene
        sentido en el modo separado (es el único con una columna por campo), y
        `_cargar_filas_auditoria` lo esconde en los otros dos."""
        self._col_menu_items_auditoria: dict[str, ft.PopupMenuItem] = {}
        items = []
        for key in self._columnas_ocultables_auditoria:
            item = ft.PopupMenuItem(
                content=self._columnas_labels_auditoria[key],
                checked=self._columnas_visibles_auditoria[key],
                on_click=lambda e, k=key: self._toggle_columna_auditoria(k, e),
            )
            self._col_menu_items_auditoria[key] = item
            items.append(item)

        self._btn_columnas_auditoria = ft.PopupMenuButton(
            icon=ft.Icons.VIEW_COLUMN_ROUNDED,
            icon_color=accent,
            tooltip="Mostrar/ocultar columnas de la auditoría",
            items=items,
        )
        return self._btn_columnas_auditoria

    def _toggle_columna_auditoria(self, key: str, e=None):
        """Oculta o muestra una columna, impidiendo quedarse sin ninguna: una
        tabla de cero columnas no es una vista, es una pantalla en blanco."""
        # Se cuentan solo las ocultables: "acciones" es estructural y no
        # alcanza para que la tabla siga diciendo algo.
        visibles = [
            k for k in self._columnas_ocultables_auditoria
            if self._columnas_visibles_auditoria.get(k, True)
        ]
        if self._columnas_visibles_auditoria[key] and len(visibles) <= 1:
            self.show_alert_info("Debe quedar al menos una columna visible.", e)
            return
        self._columnas_visibles_auditoria[key] = not self._columnas_visibles_auditoria[key]
        self._col_menu_items_auditoria[key].checked = self._columnas_visibles_auditoria[key]
        self._cargar_filas_auditoria()
        self.safe_update(e)

    def _handle_cambio_modo_vista_auditoria(self, e):
        """Cambio de formato de la lista. Solo se recargan las filas: el resto
        del Inicio (tasa BCV, métricas, ventas del día) no tiene nada que ver
        con el formato y volver a consultarlo sería trabajo tirado."""
        if e.control.selected:
            self._modo_vista_auditoria = list(e.control.selected)[0]
            self._cargar_filas_auditoria()
            self.safe_update(e)

    # ── Carga de las filas en los tres formatos ─────────────────────────────
    def _cargar_filas_auditoria(self, text_color=None, accent=None):
        """Rellena la lista de Auditoría en el modo vigente.

        Es el equivalente de `InventarioView._cargar_filas`: una sola función
        con una rama por formato, para que los tres compartan el origen de
        datos y el índice de lo que hay en pantalla. Si cada modo tuviera su
        propio cargador, el día que cambie la consulta habría que acordarse de
        los tres."""
        if not hasattr(self, "_vista_auditoria"):
            return  # panel aún sin construir
        if text_color is None:
            text_color = self.get_text_color()
        if accent is None:
            accent = self.get_accent_color()
        subtext = self.get_subtext_color()
        card_bg = self.get_card_bg()
        border = self.get_border_color()

        alertas = obtener_alertas_stock(minimo=obtener_stock_minimo())
        # Índice por código de lo que hay en pantalla: una acción invocada por
        # nombre (un atajo de teclado no tiene ninguna fila de la cual sacar el
        # ítem) resuelve el producto por aquí.
        self._alertas_en_pantalla = {a["codigo"]: a for a in alertas}
        self._descartar_marcados_fantasma()

        # El selector de columnas solo tiene sentido en el modo separado.
        if hasattr(self, "_btn_columnas_auditoria"):
            self._btn_columnas_auditoria.visible = (self._modo_vista_auditoria == "separado")

        if not alertas:
            # Sin nada que reponer no hay lista: ni tabla vacía ni flechas que
            # no desplacen nada.
            self._nav_h_auditoria.visible = False
            self._nav_v_auditoria.visible = False
            self._dt_auditoria.rows = []
            self._vista_auditoria.content = ft.Container(
                content=ft.Column([
                    ft.Icon(ft.Icons.CHECK_CIRCLE_OUTLINED, color=ft.Colors.GREEN_500, size=32),
                    ft.Text(
                        "Todo el inventario se encuentra sobre el stock mínimo de reposición.",
                        color=subtext, size=13,
                    ),
                ], alignment=ft.MainAxisAlignment.CENTER,
                   horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                padding=30,
            )
            return

        # Se vacían las filas antes de rearmar las columnas: al alternar de
        # modo, el diff de Flet encontraría filas con más celdas que columnas
        # y se descalzaría (mismo cuidado que en el catálogo).
        self._dt_auditoria.rows = []

        if self._modo_vista_auditoria == "separado":
            self._cargar_separado_auditoria(alertas, accent, text_color, subtext, card_bg)
        elif self._modo_vista_auditoria == "tarjetas":
            self._cargar_tarjetas_auditoria(alertas, accent, text_color, subtext, card_bg, border)
        else:
            self._cargar_agrupado_auditoria(alertas, accent, text_color, subtext, card_bg)

    def _envolver_tabla_auditoria(self):
        """Pone la tabla en pantalla con el cluster vertical flotando encima.

        Sin altura fija: el `Stack` se ajusta a la tabla y el desplazamiento
        vertical lo sigue aportando el cuerpo del Inicio."""
        self._nav_h_auditoria.visible = True
        self._nav_v_auditoria.visible = True
        self._vista_auditoria.content = ft.Stack(
            controls=[self._tabla_auditoria_con_holgura, self._nav_v_auditoria],
        )

    # ── Íconos de acción de la fila ─────────────────────────────────────────
    def _color_accion_auditoria(self, accion: str, accent) -> str:
        """Color del ícono. El Historial conserva el violeta que ya tiene en el
        catálogo y "Contactar proveedor" usa el verde del teléfono: que el
        mismo ícono tenga el mismo color en las dos pantallas es parte de
        poder reconocerlo sin leer el tooltip."""
        return {
            "info": accent,
            "historial": ft.Colors.PURPLE_300,
            "editar": accent,
            "proveedor": ft.Colors.GREEN_400,
        }[accion]

    def _boton_accion_auditoria(self, accion: str, codigo: str, accent, card_bg,
                                subtext, size=None) -> ft.Control:
        """Un ícono de la fila, cableado a `ejecutar_accion_auditoria` y con la
        tecla que lo acciona dibujada encima.

        La etiqueta del atajo va SUPERPUESTA en la esquina inferior derecha del
        cuadrado del ícono, dentro de un `Stack` del tamaño del botón: así la
        fila no crece y las dos vistas con tabla siguen entrando sin tocar sus
        altos de fila. Las acciones sin tecla ("Contactar proveedor") devuelven
        el botón pelado, sin insignia que prometa un atajo inexistente.

        `disabled` es la mitad VISIBLE de la regla del marcador: con otro ítem
        marcado, el ícono se ve apagado en vez de aceptar el clic y no hacer
        nada, porque un botón que ignora en silencio se lee como un cuelgue de
        la aplicación. El tooltip dice además por qué."""
        color = self._color_accion_auditoria(accion, accent)
        habilitado = self._seleccion_auditoria.puede_accionar(codigo)
        # El tooltip también lleva el atajo ("Editar (F5)"): sirve para
        # confirmarlo, no para descubrirlo — el PDF pide que la tecla esté a la
        # vista "para siempre ser consciente de ella".
        descripcion = tooltip_con_atajo(self.ETIQUETAS_ACCION_AUDITORIA[accion], accion)
        boton = ft.IconButton(
            self.ICONOS_ACCION_AUDITORIA[accion],
            icon_color=color,
            icon_size=size or self._TAM_ICONO_ACCION,
            tooltip=(
                descripcion if habilitado
                else f"{descripcion} (hay otro ítem marcado)"
            ),
            disabled=not habilitado,
            width=self._LADO_BOTON_ACCION,
            height=self._LADO_BOTON_ACCION,
            style=ft.ButtonStyle(padding=0),
            on_click=lambda ev, a=accion, c=codigo: self.ejecutar_accion_auditoria(a, c, ev),
        )
        etiqueta = etiqueta_atajo(accion)
        if not etiqueta:
            return boton

        color_etiqueta = color if habilitado else subtext
        insignia = ft.Container(
            content=ft.Text(
                etiqueta,
                size=self._TAM_ETIQUETA_ATAJO,
                weight=ft.FontWeight.BOLD,
                color=color_etiqueta,
                no_wrap=True,
            ),
            # Fondo OPACO (el de la tarjeta) más borde y texto del color del
            # ícono: así la tecla se lee sobre el dibujo del ícono y en los dos
            # temas, sin tener que elegir un color de texto por tema. Un fondo
            # translúcido dejaba el ícono asomando por detrás de la etiqueta.
            bgcolor=card_bg,
            border=ft.Border.all(1, color_etiqueta),
            border_radius=4,
            padding=ft.Padding.symmetric(horizontal=2),
            right=0,
            bottom=0,
        )
        return ft.Stack(
            controls=[boton, insignia],
            width=self._LADO_BOTON_ACCION,
            height=self._LADO_BOTON_ACCION,
        )

    def _botones_accion_auditoria(self, item: dict, accent, card_bg, subtext,
                                  size=None) -> list[ft.Control]:
        """Los íconos del ítem, en el orden de los atajos (F1 info, F4
        historial, F5 editar) y con "Contactar proveedor" al final, que es el
        que no tiene tecla."""
        codigo = item["codigo"]
        return [
            self._boton_accion_auditoria(accion, codigo, accent, card_bg, subtext, size)
            for accion in self.ACCIONES_AUDITORIA
            # El Historial Clínico no se dibuja para quien no puede abrirlo:
            # un ícono que rechaza el clic se lee como un cuelgue.
            if not (accion in ACCIONES_SOLO_ADMIN and not self.es_admin)
        ]

    def _celda_acciones_auditoria(self, item: dict, accent, card_bg, subtext) -> ft.Control:
        return ft.Row(self._botones_accion_auditoria(item, accent, card_bg, subtext), spacing=0)

    # ── Casilla marcadora y sombreado de la fila ────────────────────────────
    def _celda_marcador_auditoria(self, item: dict, accent, subtext) -> ft.Control:
        """La casilla izquierda. El ícono dice en qué modo está la selección
        (redondo para el marcador único, cuadrado para el lote) para que el
        usuario no tenga que mirar el conmutador."""
        marcado = self._seleccion_auditoria.esta_seleccionado(item["codigo"])
        if self._seleccion_auditoria.es_multiple:
            icono = ft.Icons.CHECK_BOX_ROUNDED if marcado else ft.Icons.CHECK_BOX_OUTLINE_BLANK_ROUNDED
        else:
            icono = ft.Icons.RADIO_BUTTON_CHECKED if marcado else ft.Icons.RADIO_BUTTON_UNCHECKED
        return ft.Container(
            content=ft.Icon(icono, color=accent if marcado else subtext, size=20),
            width=34,
            alignment=ft.Alignment.CENTER,
            tooltip=(
                "Clic para quitar la marca de este ítem"
                if marcado else "Clic para marcar este ítem"
            ),
        )

    def _celda_marcador_dc_auditoria(self, item: dict, accent, subtext) -> ft.DataCell:
        """La casilla atiende su propio toque: es la única celda de la fila que
        DESMARCA (`alternar`), mientras el resto de la fila solo marca."""
        return ft.DataCell(
            self._celda_marcador_auditoria(item, accent, subtext),
            on_tap=lambda ev, cod=item["codigo"]: self.alternar_item_auditoria(cod, ev),
        )

    def _construir_fila_auditoria(self, item: dict, celdas: list[ft.DataCell], accent) -> ft.DataRow:
        """Fila con su sombreado derivado del MODELO y no de una bandera local:
        así sobrevive al desplazamiento horizontal y a los repintados."""
        marcado = self._seleccion_auditoria.esta_seleccionado(item["codigo"])
        return ft.DataRow(
            cells=celdas,
            selected=marcado,
            color=ft.Colors.with_opacity(0.22, accent) if marcado else None,
            # Hace la fila COMPLETA sensible al clic ("no importa si es fuera
            # de la casilla"); la celda del marcador tiene su propio `on_tap` y
            # por eso no cae aquí.
            on_select_change=lambda ev, cod=item["codigo"]: self.seleccionar_item_auditoria(cod, ev),
            data=item["codigo"],
        )

    def _chip_auditoria(self, texto: str, color: str) -> ft.Container:
        """Etiqueta compacta sobre fondo tenue del mismo color (código,
        referencia, nombre corto). Funciona en los dos temas porque el fondo se
        deriva del color del texto, no de un gris fijo."""
        return ft.Container(
            content=ft.Text(texto, size=11, weight=ft.FontWeight.W_600, color=color),
            bgcolor=ft.Colors.with_opacity(0.12, color),
            padding=ft.Padding.symmetric(horizontal=6, vertical=2),
            border_radius=6,
        )

    @staticmethod
    def _etiqueta_origen_minimo(item: dict) -> str:
        """`origen` dice qué umbral disparó la alerta: sin ese dato, un mínimo
        distinto al de la caja de texto parece un error de cálculo."""
        return "umbral propio" if item.get("origen") == "producto" else "umbral global"

    # ── Modo "separado": una columna por campo ──────────────────────────────
    def _cargar_separado_auditoria(self, alertas, accent, text_color, subtext, card_bg):
        """Una columna por campo, con el selector de columnas para esconder lo
        que no interese. Es el formato para revisar dato por dato."""
        self._dt_auditoria.data_row_min_height = 48
        self._dt_auditoria.data_row_max_height = 48
        self._dt_auditoria.columns = [
            self._build_columna_auditoria(k, accent, text_color)
            for k in self._columnas_orden_visible_auditoria()
        ]

        def texto(valor, color=None, peso=ft.FontWeight.NORMAL):
            return ft.Text(
                valor, color=color or text_color, size=12, weight=peso,
                max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
            )

        constructores = {
            "codigo": lambda a: texto(a["codigo"], accent, ft.FontWeight.W_600),
            "referencia": lambda a: texto(a.get("referencia") or "-"),
            "descripcion": lambda a: ft.Container(
                content=texto(a.get("descripcion_general") or "-"), width=300,
            ),
            "nombre_corto": lambda a: texto(a["nombre_corto"]),
            "departamento": lambda a: texto(a.get("departamento") or "-"),
            "marca": lambda a: texto(a.get("marca") or "-"),
            "existencia": lambda a: texto(
                f"{a['existencia']:.0f}", ft.Colors.RED_500, ft.FontWeight.BOLD,
            ),
            "minimo": lambda a: texto(f"{a['minimo']:.0f}", peso=ft.FontWeight.W_600),
            "proveedor": lambda a: texto(a["proveedor_nombre"]),
            "contacto": lambda a: texto(
                f"{a['proveedor_contacto']} · {a['proveedor_telefono']}", subtext,
            ),
            "acciones": lambda a: self._celda_acciones_auditoria(a, accent, card_bg, subtext),
        }

        columnas = self._columnas_orden_visible_auditoria()
        self._dt_auditoria.rows = [
            self._construir_fila_auditoria(a, [
                self._celda_marcador_dc_auditoria(a, accent, subtext) if k == "marcador"
                else ft.DataCell(constructores[k](a))
                for k in columnas
            ], accent)
            for a in alertas
        ]
        self._envolver_tabla_auditoria()

    # ── Modo "agrupado": varios datos por celda, en dos líneas ──────────────
    def _cargar_agrupado_auditoria(self, alertas, accent, text_color, subtext, card_bg):
        """Varios datos por celda y en dos líneas, SIN deslizable horizontal:
        los anchos suman ~1120 px, el ancho útil de una pantalla normal. Es el
        formato con el que esta ventana ya se mostraba, y el que deja leer la
        descripción general completa de un vistazo."""
        self._dt_auditoria.data_row_min_height = 72
        self._dt_auditoria.data_row_max_height = 95
        self._dt_auditoria.columns = [
            # El marcador también abre la lista agrupada: la confusión de filas
            # al moverse a la derecha es la misma en los tres formatos.
            self._build_columna_auditoria("marcador", accent, text_color),
            ft.DataColumn(ft.Text("Producto (Descripción / Cód / Ref)", color=text_color, weight=ft.FontWeight.BOLD)),
            ft.DataColumn(ft.Text("Depto / Marca", color=text_color, weight=ft.FontWeight.BOLD)),
            ft.DataColumn(ft.Text("Stock Actual", color=text_color, weight=ft.FontWeight.BOLD)),
            ft.DataColumn(ft.Text("Mínimo", color=text_color, weight=ft.FontWeight.BOLD)),
            ft.DataColumn(ft.Text("Proveedor / Contacto (ERS 3.6)", color=text_color, weight=ft.FontWeight.BOLD)),
            ft.DataColumn(ft.Text("Acciones", color=accent, weight=ft.FontWeight.BOLD)),
        ]

        filas = []
        for item in alertas:
            celda_producto = ft.Container(
                content=ft.Column([
                    ft.Text(
                        item.get("descripcion_general") or item["nombre_corto"],
                        size=13, weight=ft.FontWeight.BOLD, color=text_color,
                        # El par `max_lines=2` + elipsis es lo que permite la
                        # segunda línea cuando la descripción es larga: sin el
                        # overflow explícito el texto se recortaría en seco.
                        max_lines=2, overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                    ft.Row([
                        self._chip_auditoria(f"Cód: {item['codigo']}", accent),
                        self._chip_auditoria(f"Ref: {item.get('referencia') or '-'}", subtext),
                        self._chip_auditoria(f"Corto: {item['nombre_corto']}", subtext),
                    ], spacing=6, wrap=True),
                ], spacing=4, tight=True),
                width=380,
                padding=ft.Padding.symmetric(vertical=6),
            )

            celda_clasificacion = ft.Container(
                content=ft.Column([
                    ft.Text(item.get("departamento") or "-", size=12, weight=ft.FontWeight.W_600, color=text_color),
                    ft.Text(item.get("marca") or "-", size=11, color=subtext),
                ], spacing=2, tight=True),
                width=150,
                padding=ft.Padding.symmetric(vertical=6),
            )

            celda_stock = ft.Container(
                content=ft.Text(f"{item['existencia']:.0f}", size=16, color=ft.Colors.RED_500, weight=ft.FontWeight.BOLD),
                width=90,
                alignment=ft.Alignment.CENTER_LEFT,
            )

            celda_minimo = ft.Container(
                content=ft.Column([
                    ft.Text(f"{item['minimo']:.0f}", size=13, color=text_color, weight=ft.FontWeight.W_600),
                    ft.Text(self._etiqueta_origen_minimo(item), size=10, color=subtext),
                ], spacing=2, tight=True),
                width=90,
                padding=ft.Padding.symmetric(vertical=6),
            )

            celda_proveedor = ft.Container(
                content=ft.Column([
                    ft.Text(
                        item["proveedor_nombre"], size=12, weight=ft.FontWeight.W_600, color=text_color,
                        max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                    ft.Text(
                        f"{item['proveedor_contacto']} · {item['proveedor_telefono']}",
                        size=11, color=subtext, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                ], spacing=2, tight=True),
                width=220,
                padding=ft.Padding.symmetric(vertical=6),
            )

            celda_acciones = ft.Container(
                content=self._celda_acciones_auditoria(item, accent, card_bg, subtext),
                width=150,
                padding=ft.Padding.symmetric(vertical=6),
            )

            filas.append(self._construir_fila_auditoria(item, [
                self._celda_marcador_dc_auditoria(item, accent, subtext),
                ft.DataCell(celda_producto),
                ft.DataCell(celda_clasificacion),
                ft.DataCell(celda_stock),
                ft.DataCell(celda_minimo),
                ft.DataCell(celda_proveedor),
                ft.DataCell(celda_acciones),
            ], accent))

        self._dt_auditoria.rows = filas
        self._envolver_tabla_auditoria()

    # ── Modo "tarjetas" ────────────────────────────────────────────────────
    def _cargar_tarjetas_auditoria(self, alertas, accent, text_color, subtext, card_bg, border):
        """Una tarjeta por producto a reponer. No hay tabla, así que tampoco
        hay eje horizontal ni clusters de flechas: las tarjetas envuelven y el
        eje vertical sigue siendo del cuerpo del Inicio."""
        self._nav_h_auditoria.visible = False
        self._nav_v_auditoria.visible = False
        self._dt_auditoria.rows = []

        tarjetas = [
            self._tarjeta_auditoria(item, accent, text_color, subtext, card_bg, border)
            for item in alertas
        ]
        self._vista_auditoria.content = ft.Column(
            controls=[ft.Row(controls=tarjetas, wrap=True, spacing=10)],
            tight=True,
        )

    def _tarjeta_auditoria(self, item, accent, text_color, subtext, card_bg, border) -> ft.Control:
        """Tarjeta de un producto a reponer.

        El marcador también funciona aquí, y con la misma mecánica que en las
        tablas: un clic en cualquier parte de la tarjeta marca, un clic en la
        casilla alterna. Sin eso, cambiar a tarjetas sería perder la selección
        y las acciones sobre lo marcado, y el usuario leería el modo de vista
        como tres pantallas distintas en vez de tres formatos de la misma."""
        marcado = self._seleccion_auditoria.esta_seleccionado(item["codigo"])
        casilla = self._celda_marcador_auditoria(item, accent, subtext)
        # La casilla se queda con su propio clic: es lo único de la tarjeta que
        # DESMARCA (el resto solo marca, igual que en las filas).
        casilla.on_click = lambda ev, cod=item["codigo"]: self.alternar_item_auditoria(cod, ev)
        return ft.Container(
            on_click=lambda ev, cod=item["codigo"]: self.seleccionar_item_auditoria(cod, ev),
            content=ft.Column([
                ft.Row([
                    casilla,
                    ft.Text(f"Código: {item['codigo']}", size=12, weight=ft.FontWeight.BOLD, color=accent),
                    ft.Container(
                        content=ft.Text(
                            f"Stock: {item['existencia']:.0f}", size=11,
                            weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE,
                        ),
                        bgcolor=ft.Colors.RED_700,
                        padding=ft.Padding.symmetric(horizontal=8, vertical=2),
                        border_radius=10,
                    ),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Divider(height=4),
                ft.Text(
                    item.get("descripcion_general") or item["nombre_corto"],
                    size=14, weight=ft.FontWeight.BOLD, color=text_color,
                    max_lines=2, overflow=ft.TextOverflow.ELLIPSIS,
                ),
                ft.Row([
                    ft.Text(f"Ref: {item.get('referencia') or '-'}", size=11, color=subtext),
                    ft.Text(
                        f"{item.get('departamento') or '-'} / {item.get('marca') or '-'}",
                        size=11, color=subtext,
                    ),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Divider(height=4),
                ft.Row([
                    ft.Column([
                        ft.Text("Mínimo", size=10, color=subtext),
                        ft.Text(
                            f"{item['minimo']:.0f}", size=13,
                            weight=ft.FontWeight.BOLD, color=text_color,
                        ),
                        ft.Text(self._etiqueta_origen_minimo(item), size=9, color=subtext),
                    ], spacing=1),
                    ft.Column([
                        ft.Text("Proveedor", size=10, color=subtext),
                        ft.Text(
                            item["proveedor_nombre"], size=12,
                            weight=ft.FontWeight.W_600, color=text_color,
                            max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                        ),
                        ft.Text(
                            f"{item['proveedor_contacto']} · {item['proveedor_telefono']}",
                            size=10, color=subtext,
                            max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                        ),
                    ], spacing=1, expand=True),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Divider(height=4),
                self._celda_acciones_auditoria(item, accent, card_bg, subtext),
            ], spacing=6),
            padding=12, border_radius=14, width=320,
            # Sombreado derivado del modelo, igual que en las filas: una
            # tarjeta marcada se tiñe y se le marca el borde, porque en una
            # cuadrícula el borde se distingue mejor que un fondo apenas más
            # claro.
            bgcolor=ft.Colors.with_opacity(0.22, accent) if marcado else card_bg,
            border=ft.Border.all(2 if marcado else 1, accent if marcado else border),
        )
