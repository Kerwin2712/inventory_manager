import flet as ft
from ui.views.base_view import BaseView
from ui.views.cartera_view import CarteraView
from ui.views.inventario_view import InventarioView
from ui.views.ventas_view import VentasView
from ui.views.gestion_datos_view import GestionDatosView
from services.reportes_service import (
    obtener_metricas_dashboard,
    obtener_top_ventas,
    obtener_alertas_stock
)

class DashboardView(BaseView):
    """Vista principal de Dashboard adaptada al tema dinámico con navegación interna por módulos."""

    def __init__(self, user_info: dict = None, on_logout_callback=None):
        self.user_info = user_info or {"username": "usuario", "role": "administrador"}
        self.on_logout_callback = on_logout_callback
        self.current_section = "Inicio"
        self.rango_top_ventas = "Hoy"
        self.limite_top_ventas = 10
        super().__init__(route="/dashboard", title="Dashboard General")

    def handle_nav_change(self, section_name: str):
        """Cambia la sección activa de la vista principal."""
        self.current_section = section_name
        self.rebuild_ui()

    def get_body(self) -> ft.Control:
        # Selección del contenido principal según la sección activa
        if self.current_section == "Ventas":
            ventas_view = VentasView(page=self.page, user_data=self.user_info)
            try:
                if self.page:
                    ventas_view.page = self.page
            except (RuntimeError, AttributeError):
                pass
            main_content = ventas_view.get_body()

        elif self.current_section == "Cartera":
            cartera_view = CarteraView()
            try:
                if self.page:
                    cartera_view.page = self.page
            except (RuntimeError, AttributeError):
                pass
            main_content = cartera_view.get_body()

        elif self.current_section == "Inventario":
            inv_view = InventarioView()
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
            main_content = ft.Column(
                controls=[
                    self.build_metrics_cards(),
                    ft.Container(height=10),
                    self.build_data_sections(),
                ],
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
                ft.VerticalDivider(width=1, color=self.get_border_color()),
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
        """Construye el Sidebar con fondo blanco en Modo Claro y acento en la opción activa."""
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

            btn = ft.Container(
                content=ft.Row(
                    controls=[
                        ft.Icon(icon, color=fg, size=20),
                        ft.Text(label, color=fg, weight=ft.FontWeight.W_600 if is_active else ft.FontWeight.NORMAL),
                    ],
                    spacing=12,
                ),
                padding=ft.Padding.symmetric(horizontal=15, vertical=12),
                border_radius=8,
                bgcolor=bg,
                on_click=lambda e, l=label: self.handle_nav_change(l),
            )
            item_controls.append(btn)

        return ft.Container(
            width=230,
            padding=15,
            bgcolor=self.get_sidebar_bg(),
            border=ft.Border.only(right=ft.BorderSide(1, self.get_border_color())),
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Icon(ft.Icons.STOREFRONT_ROUNDED, color=accent, size=28),
                            ft.Text("InventoryApp", size=18, weight=ft.FontWeight.BOLD, color=self.get_text_color()),
                        ],
                        spacing=10,
                    ),
                    ft.Divider(height=20, color=self.get_border_color()),
                    ft.Column(controls=item_controls, spacing=5, expand=True),
                ],
                spacing=10,
            )
        )

    def build_header(self) -> ft.Control:
        """Encabezado superior con acento focalizado en el título e icono de usuario."""
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

        logout_btn = ft.Button(
            content="Salir",
            bgcolor=ft.Colors.RED_600,
            color=ft.Colors.WHITE,
            on_click=lambda e: self.on_logout_callback() if self.on_logout_callback else None,
        )

        header_title = f"Dashboard - {self.current_section}" if self.current_section != "Inicio" else "Dashboard Principal"

        return ft.Row(
            controls=[
                ft.Text(header_title, size=22, weight=ft.FontWeight.BOLD, color=accent),
                ft.Row(
                    controls=[
                        user_badge,
                        notifications_icon,
                        theme_toggle_btn,
                        color_picker_btn,
                        logout_btn,
                    ],
                    spacing=10,
                )
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
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
            ("Ventas del Día", ventas_val, variacion_str, ft.Icons.ATTACH_MONEY_ROUNDED, ft.Colors.GREEN_500),
            ("Productos en Stock", stock_val, stock_sub, ft.Icons.INVENTORY_ROUNDED, self.get_accent_color()),
            ("Alertas de Stock Bajo", criticos_val, criticos_sub, ft.Icons.WARNING_AMBER_ROUNDED, ft.Colors.AMBER_500 if metricas['total_criticos'] > 0 else ft.Colors.GREEN_500),
        ]

        card_widgets = []
        for title, value, subtitle, icon, color in cards_data:
            c = ft.Card(
                content=ft.Container(
                    content=ft.Column(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Text(title, size=13, color=self.get_subtext_color(), weight=ft.FontWeight.W_500),
                                    ft.Icon(icon, color=color, size=24),
                                ],
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            ),
                            ft.Text(value, size=20, weight=ft.FontWeight.BOLD, color=self.get_text_color()),
                            ft.Text(subtitle, size=12, color=color),
                        ],
                        spacing=8,
                    ),
                    padding=20,
                    width=260,
                    bgcolor=self.get_card_bg(),
                    border_radius=10,
                ),
                elevation=1,
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
            content_padding=5
        )
        dd_rango.on_change = handle_cambio_rango

        dd_limite = ft.Dropdown(
            value=str(self.limite_top_ventas),
            options=[
                ft.dropdown.Option("10", "Top 10"),
                ft.dropdown.Option("100", "Top 100"),
            ],
            width=100,
            content_padding=5
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

        left_section = ft.Container(
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
            border_radius=10,
            bgcolor=self.get_card_bg(),
            border=ft.Border.all(1, self.get_border_color()),
            col={"sm": 12, "lg": 6},
        )

        # ── 2. Auditoría Preventiva (Stock Crítico + Contacto Proveedor - ERS 3.6) ──
        alertas_stock = obtener_alertas_stock(minimo=5.0)

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

        right_section = ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Icon(ft.Icons.REPORT_PROBLEM_ROUNDED, color=ft.Colors.AMBER_500),
                            ft.Text("Auditoría Preventiva (Stock Crítico < 5)", size=15, weight=ft.FontWeight.BOLD, color=text_color),
                        ],
                        spacing=10,
                    ),
                    ft.Divider(height=10, color=self.get_border_color()),
                    stock_content,
                ],
                spacing=10,
            ),
            padding=15,
            border_radius=10,
            bgcolor=self.get_card_bg(),
            border=ft.Border.all(1, self.get_border_color()),
            col={"sm": 12, "lg": 6},
        )

        return ft.ResponsiveRow(
            controls=[
                left_section,
                right_section,
            ],
            spacing=20,
        )
