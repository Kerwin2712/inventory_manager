import flet as ft
from ui.views.base_view import BaseView
from ui.views.cartera_view import CarteraView
from ui.views.inventario_view import InventarioView
from ui.views.ventas_view import VentasView
from ui.views.gestion_datos_view import GestionDatosView
from services.reportes_service import (
    obtener_metricas_dashboard,
    obtener_top_ventas,
    obtener_alertas_stock,
    obtener_stock_minimo,
    actualizar_stock_minimo,
)

class DashboardView(BaseView):
    """Vista principal de Dashboard adaptada al tema dinámico con navegación interna por módulos."""

    # ERS 3.6: módulo exclusivo de uso administrativo/gerencial.
    ROLES_CON_ACCESO_AUDITORIA = ("administrador", "superadmin", "gerencia")

    # El título global ("General") viaja DENTRO de `build_header()`: una sola
    # franja horizontal con título + módulo + usuario + opciones + salir.
    mostrar_titulo_por_defecto = False

    def __init__(self, user_info: dict = None, on_logout_callback=None):
        self.user_info = user_info or {"username": "usuario", "role": "administrador"}
        self.on_logout_callback = on_logout_callback
        self.current_section = "Inicio"
        self.rango_top_ventas = "Hoy"
        self.limite_top_ventas = 10
        self.sidebar_collapsed = True
        super().__init__(route="/dashboard", title="General")

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
        self.rebuild_ui()

    def procesar_venta_desde_inventario(self, producto: dict, e=None):
        """Flujo Directo Inventario→Ventas (ERS 3.3): instancia una nueva nota
        de venta, carga el producto con cantidad=1 y navega a Ventas."""
        from services.cart_manager import crear_nuevo_carrito, agregar_o_actualizar_producto
        sid = self.get_session_id(e)
        crear_nuevo_carrito(sid)
        agregar_o_actualizar_producto(sid, producto, cantidad=1.0)
        self.current_section = "Ventas"
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
        self.rebuild_ui()

    def get_body(self) -> ft.Control:
        # Selección del contenido principal según la sección activa
        if self.current_section == "Ventas":
            ventas_view = VentasView(page=self.page, user_data=self.user_info, on_update_callback=self.rebuild_ui)
            try:
                if self.page:
                    ventas_view.page = self.page
            except (RuntimeError, AttributeError):
                pass
            main_content = ventas_view.get_body()

        elif self.current_section == "Cartera":
            cartera_view = CarteraView(on_iniciar_venta=self.iniciar_venta_desde_cartera)
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
            gd_view = GestionDatosView()
            try:
                if self.page:
                    gd_view.page = self.page
            except (RuntimeError, AttributeError):
                pass
            main_content = gd_view.get_body()

        elif self.current_section == "Inicio":
            # ERS 3.6: el panel de Inteligencia de Negocio y Auditoría de Stock
            # es exclusivo para roles administrativos/gerenciales.
            secciones_inicio = [self.build_metrics_cards(), ft.Container(height=10)]
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
            main_content = ft.Column(
                controls=secciones_inicio,
                scroll=ft.ScrollMode.AUTO,
                spacing=20,
            )
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

    def build_header(self) -> ft.Control:
        """Franja superior ÚNICA: título global · módulo actual · usuario ·
        opciones de interfaz · cerrar sesión.

        El título global ya no se pinta arriba en una línea aparte (ver
        `mostrar_titulo_por_defecto`): se absorbe aquí para recuperar ese alto
        para el contenido. El bloque de título toma el ancho sobrante y elide
        con puntos suspensivos, mientras la zona de acciones va `tight` para
        que en ventanas angostas los botones nunca salgan de pantalla."""
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
            on_click=lambda e: print("Notificaciones"),
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

        header_title = f"{self.current_section}" if self.current_section != "Inicio" else "Principal"

        # Título global + módulo actual en un solo bloque jerárquico
        # ("General · Inventario"): el global en acento y el módulo en el color
        # de texto, separados por un punto medio. El módulo lleva `expand` para
        # que sea él (y no los botones) el que ceda ancho y elida.
        bloque_titulo = ft.Container(
            content=ft.Row(
                controls=[
                    ft.Text(
                        self.view_title, size=20, weight=ft.FontWeight.BOLD, color=accent,
                        no_wrap=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                    ft.Text("·", size=20, weight=ft.FontWeight.BOLD, color=self.get_subtext_color()),
                    ft.Text(
                        header_title, size=18, weight=ft.FontWeight.W_600, color=self.get_text_color(),
                        no_wrap=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                        expand=True,
                    ),
                ],
                spacing=8,
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
                width=265,
                bgcolor=self.get_card_bg(),
                border_radius=18,
                border=ft.Border.all(1, self.get_border_color()),
                shadow=self.get_card_shadow(),
            )
            card_widgets.append(c)

        return ft.Row(controls=card_widgets, spacing=20, wrap=True)

    def build_data_sections(self) -> ft.Control:
        """Construye las tablas de métricas en contenedores adaptativos con datos reales."""
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

        left_section = self.create_card(
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
            col={"sm": 12, "lg": 6},
        )

        # ── 2. Auditoría Preventiva (Stock Crítico + Contacto Proveedor - ERS 3.6) ──
        stock_minimo_actual = obtener_stock_minimo()
        alertas_stock = obtener_alertas_stock(minimo=stock_minimo_actual)

        def handle_guardar_stock_minimo(e):
            try:
                nuevo_val = float((inp_stock_minimo.value or "0").replace(",", "."))
                actualizar_stock_minimo(nuevo_val)
                self.show_alert_success(e, f"Stock mínimo actualizado a {nuevo_val:.0f}.")
                self.rebuild_ui()
            except ValueError as ex:
                self.show_alert_error(e, str(ex))

        inp_stock_minimo = ft.TextField(
            label="Stock mínimo",
            value=f"{stock_minimo_actual:.0f}",
            width=110,
            keyboard_type=ft.KeyboardType.NUMBER,
            border_radius=12,
            content_padding=8,
            on_submit=handle_guardar_stock_minimo,
        )
        btn_guardar_stock_minimo = ft.IconButton(
            icon=ft.Icons.SAVE_OUTLINED, icon_color=accent,
            tooltip="Guardar nuevo stock mínimo parametrizado (ERS 3.6)",
            on_click=handle_guardar_stock_minimo,
        )

        if alertas_stock:
            stock_rows = []
            for item in alertas_stock:
                contacto_str = f"{item['proveedor_nombre']} ({item['proveedor_telefono']})"
                stock_rows.append(
                    ft.DataRow(
                        cells=[
                            ft.DataCell(ft.Text(item["nombre_corto"], color=text_color, weight=ft.FontWeight.BOLD)),
                            ft.DataCell(ft.Text(f"{item['existencia']:.0f}", color=ft.Colors.RED_500, weight=ft.FontWeight.BOLD)),
                            ft.DataCell(ft.Text(f"{item['minimo']:.0f}", color=text_color)),
                            ft.DataCell(ft.Text(contacto_str, color=self.get_subtext_color())),
                        ]
                    )
                )

            stock_content = ft.DataTable(
                columns=[
                    ft.DataColumn(ft.Text("Producto", color=text_color)),
                    ft.DataColumn(ft.Text("Stock Actual", color=text_color)),
                    ft.DataColumn(ft.Text("Mínimo", color=text_color)),
                    ft.DataColumn(ft.Text("Proveedor / Contacto (ERS 3.6)", color=text_color)),
                ],
                rows=stock_rows,
            )
        else:
            stock_content = ft.Container(
                content=ft.Column([
                    ft.Icon(ft.Icons.CHECK_CIRCLE_OUTLINED, color=ft.Colors.GREEN_500, size=32),
                    ft.Text("Todo el inventario se encuentra sobre el stock mínimo de reposición.", color=self.get_subtext_color(), size=13)
                ], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                padding=30
            )

        right_section = self.create_card(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Row([
                                ft.Icon(ft.Icons.REPORT_PROBLEM_ROUNDED, color=accent),
                                ft.Text(f"Auditoría Preventiva (Stock Crítico < {stock_minimo_actual:.0f})", size=15, weight=ft.FontWeight.BOLD, color=text_color),
                            ], spacing=10),
                            ft.Row([inp_stock_minimo, btn_guardar_stock_minimo], spacing=2),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        wrap=True,
                    ),
                    ft.Divider(height=10, color=self.get_border_color()),
                    stock_content,
                ],
                spacing=10,
            ),
            padding=15,
            border_radius=18,
            col={"sm": 12, "lg": 6},
        )

        return ft.ResponsiveRow(
            controls=[
                left_section,
                right_section,
            ],
            spacing=20,
        )
