import flet as ft
from ui.views.base_view import BaseView
from ui.views.cartera_view import CarteraView
from ui.views.inventario_view import InventarioView
from ui.views.ventas_view import VentasView
from ui.views.gestion_datos_view import GestionDatosView
from ui.components.scroll_nav import build_floating_v_nav, build_inline_h_nav
from ui.components.teclado_nav import ControlTeclado
from services.bcv_service import obtener_estado_tasa
from services.reportes_service import (
    obtener_metricas_dashboard,
    obtener_top_ventas,
    obtener_ventas_del_dia,
    obtener_alertas_stock,
    obtener_stock_minimo,
    actualizar_stock_minimo,
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

        self._teclado = ControlTeclado(
            # Resolución tardía a propósito: pasar `self.get_current_page`
            # directamente congelaría el método que exista en este instante,
            # de modo que cualquier reemplazo posterior (una subclase, o un
            # doble de prueba que sustituye la página) quedaría ignorado y el
            # teclado buscaría la página por un camino viejo.
            obtener_pagina=lambda e=None: self.get_current_page(e),
            destino_vertical=lambda: self._scroll_inicio_v,
            destino_horizontal=lambda: self._scroll_inicio_h,
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

    def build_ventas_diarias(self) -> ft.Control:
        """Ventana "Ventas Diarias" del Inicio (nueva función 1 de la
        especificación 17/10/2026): todas las ventas del día de hoy en forma de
        lista, la más reciente arriba y la más vieja abajo.

        Va entre las cuatro tarjetas y la Auditoría Preventiva, y a ancho
        completo como ellas. Las columnas llevan ancho fijo (suman ~1120 px) y
        la descripción se parte en dos líneas al estilo "agrupado" del
        Inventario, porque el requisito explícito es que no haga falta un
        deslizable horizontal para leer toda la información de la fila."""
        text_color = self.get_text_color()
        subtext = self.get_subtext_color()
        accent = self.get_accent_color()

        ventas = obtener_ventas_del_dia()

        if ventas:
            filas = []
            for venta in ventas:
                cantidad = venta["cantidad_articulos"]
                # Las cantidades son REAL (hay productos que se venden por
                # fracción): solo se muestran decimales cuando existen.
                cantidad_txt = (
                    f"{cantidad:,.0f}" if float(cantidad).is_integer() else f"{cantidad:,.2f}"
                )
                simbolo = "Bs" if venta["moneda"] == "Bs" else "$"
                referencia = venta["referencia_pago"]

                filas.append(
                    ft.DataRow(cells=[
                        ft.DataCell(ft.Container(
                            content=ft.Text(venta["fecha_hora"], size=12, color=text_color, weight=ft.FontWeight.W_600),
                            width=150,
                        )),
                        ft.DataCell(ft.Container(
                            content=ft.Text(
                                venta["descripcion_corta"], size=13, color=text_color,
                                # Dos líneas: un carrito con varios artículos
                                # concatena todos sus nombres cortos y una sola
                                # línea los dejaría casi todos fuera.
                                max_lines=2, overflow=ft.TextOverflow.ELLIPSIS,
                            ),
                            width=380,
                            padding=ft.Padding.symmetric(vertical=6),
                        )),
                        ft.DataCell(ft.Container(
                            content=ft.Text(venta["metodo_pago"], size=12, color=text_color),
                            width=140,
                        )),
                        ft.DataCell(ft.Container(
                            # En Efectivo no hay comprobante que mostrar: el
                            # guion deja claro que la casilla no quedó vacía
                            # por un dato perdido.
                            content=ft.Text(
                                referencia or "-", size=12,
                                color=text_color if referencia else subtext,
                                max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                            ),
                            width=160,
                        )),
                        ft.DataCell(ft.Container(
                            content=ft.Text(cantidad_txt, size=12, color=text_color, weight=ft.FontWeight.W_600),
                            width=130,
                        )),
                        ft.DataCell(ft.Container(
                            content=ft.Text(
                                f"{simbolo} {venta['monto_total']:,.2f}",
                                size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_400,
                            ),
                            width=160,
                        )),
                    ])
                )

            contenido = ft.DataTable(
                columns=[
                    ft.DataColumn(ft.Text("Fecha y hora", color=text_color, weight=ft.FontWeight.BOLD)),
                    ft.DataColumn(ft.Text("Descripción Corta", color=text_color, weight=ft.FontWeight.BOLD)),
                    ft.DataColumn(ft.Text("Método de Pago", color=text_color, weight=ft.FontWeight.BOLD)),
                    ft.DataColumn(ft.Text("Referencia de Pago", color=text_color, weight=ft.FontWeight.BOLD)),
                    ft.DataColumn(ft.Text("Cantidad de Artículos", color=text_color, weight=ft.FontWeight.BOLD)),
                    ft.DataColumn(ft.Text("Monto Total Pagado", color=text_color, weight=ft.FontWeight.BOLD)),
                ],
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

        tarjeta = self.create_card(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Row([
                                ft.Icon(ft.Icons.RECEIPT_LONG_ROUNDED, color=accent),
                                ft.Text("Ventas Diarias", size=15, weight=ft.FontWeight.BOLD, color=text_color),
                            ], spacing=10),
                            ft.Text(
                                f"{len(ventas)} venta(s) hoy", size=12,
                                color=subtext, weight=ft.FontWeight.W_600,
                            ),
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

        # Igual que `build_data_sections`: el `ResponsiveRow` es lo que hace que
        # la tarjeta se estire de izquierda a derecha (un Container suelto en un
        # Column se encoge al ancho de su contenido).
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
                                self._nav_h_auditoria,
                                self._btn_modo_vista_auditoria,
                                self._build_selector_columnas_auditoria(accent, text_color),
                                inp_stock_minimo,
                                btn_guardar_stock_minimo,
                            ], spacing=8),
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
        """Orden fijo de columnas, filtrando las que el usuario desactivó."""
        return [
            k for k in self._columnas_ocultables_auditoria
            if self._columnas_visibles_auditoria.get(k, True)
        ]

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
        visibles = self._columnas_orden_visible_auditoria()
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
            self._cargar_separado_auditoria(alertas, accent, text_color, subtext)
        elif self._modo_vista_auditoria == "tarjetas":
            self._cargar_tarjetas_auditoria(alertas, accent, text_color, subtext, card_bg, border)
        else:
            self._cargar_agrupado_auditoria(alertas, accent, text_color, subtext)

    def _envolver_tabla_auditoria(self):
        """Pone la tabla en pantalla con el cluster vertical flotando encima.

        Sin altura fija: el `Stack` se ajusta a la tabla y el desplazamiento
        vertical lo sigue aportando el cuerpo del Inicio."""
        self._nav_h_auditoria.visible = True
        self._nav_v_auditoria.visible = True
        self._vista_auditoria.content = ft.Stack(
            controls=[self._tabla_auditoria_con_holgura, self._nav_v_auditoria],
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
    def _cargar_separado_auditoria(self, alertas, accent, text_color, subtext):
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
        }

        columnas = self._columnas_orden_visible_auditoria()
        self._dt_auditoria.rows = [
            ft.DataRow(cells=[ft.DataCell(constructores[k](a)) for k in columnas])
            for a in alertas
        ]
        self._envolver_tabla_auditoria()

    # ── Modo "agrupado": varios datos por celda, en dos líneas ──────────────
    def _cargar_agrupado_auditoria(self, alertas, accent, text_color, subtext):
        """Varios datos por celda y en dos líneas, SIN deslizable horizontal:
        los anchos suman ~1120 px, el ancho útil de una pantalla normal. Es el
        formato con el que esta ventana ya se mostraba, y el que deja leer la
        descripción general completa de un vistazo."""
        self._dt_auditoria.data_row_min_height = 72
        self._dt_auditoria.data_row_max_height = 95
        self._dt_auditoria.columns = [
            ft.DataColumn(ft.Text("Producto (Descripción / Cód / Ref)", color=text_color, weight=ft.FontWeight.BOLD)),
            ft.DataColumn(ft.Text("Depto / Marca", color=text_color, weight=ft.FontWeight.BOLD)),
            ft.DataColumn(ft.Text("Stock Actual", color=text_color, weight=ft.FontWeight.BOLD)),
            ft.DataColumn(ft.Text("Mínimo", color=text_color, weight=ft.FontWeight.BOLD)),
            ft.DataColumn(ft.Text("Proveedor / Contacto (ERS 3.6)", color=text_color, weight=ft.FontWeight.BOLD)),
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

            filas.append(ft.DataRow(cells=[
                ft.DataCell(celda_producto),
                ft.DataCell(celda_clasificacion),
                ft.DataCell(celda_stock),
                ft.DataCell(celda_minimo),
                ft.DataCell(celda_proveedor),
            ]))

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
        """Tarjeta de un producto a reponer."""
        return ft.Container(
            content=ft.Column([
                ft.Row([
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
            ], spacing=6),
            padding=12, border_radius=14, width=320,
            bgcolor=card_bg,
            border=ft.Border.all(1, border),
        )
