import flet as ft
from ui.views.base_view import BaseView

class DashboardView(BaseView):
    """Vista principal de Dashboard adaptada al tema dinámico."""

    def __init__(self, user_info: dict = None, on_logout_callback=None):
        self.user_info = user_info or {"username": "usuario", "role": "administrador"}
        self.on_logout_callback = on_logout_callback
        super().__init__(route="/dashboard", title="Dashboard General")

    def get_body(self) -> ft.Control:
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
                                content=ft.Column(
                                    controls=[
                                        self.build_metrics_cards(),
                                        ft.Container(height=10),
                                        self.build_data_sections(),
                                    ],
                                    scroll=ft.ScrollMode.AUTO,
                                    spacing=20,
                                ),
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
            ("Inicio", ft.Icons.DASHBOARD_ROUNDED, True),
            ("Ventas", ft.Icons.POINT_OF_SALE_ROUNDED, False),
            ("Inventario", ft.Icons.INVENTORY_2_ROUNDED, False),
            ("Cartera", ft.Icons.ACCOUNT_BALANCE_WALLET_ROUNDED, False),
            ("Gestión de Datos", ft.Icons.DATASET_ROUNDED, False),
        ]

        item_controls = []
        accent = self.get_accent_color()

        for label, icon, is_active in nav_items:
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
                on_click=lambda e, l=label: print(f"Navegar a {l}"),
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
                    ft.Text(f"{self.user_info.get('username')} ({role_label})", weight=ft.FontWeight.BOLD, color=self.get_text_color()),
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

        return ft.Row(
            controls=[
                ft.Text("Dashboard Principal", size=22, weight=ft.FontWeight.BOLD, color=accent),
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
        """Construye las tarjetas de métricas con el fondo adaptativo del tema."""
        cards_data = [
            ("Ventas del Día", "$1,450.80", "+12.5% vs ayer", ft.Icons.ATTACH_MONEY_ROUNDED, ft.Colors.GREEN_500),
            ("Productos en Stock", "1,840 Unidades", "52 Categorías", ft.Icons.INVENTORY_ROUNDED, self.get_accent_color()),
            ("Alertas de Stock Bajo", "8 Críticos", "Requieren reposición", ft.Icons.WARNING_AMBER_ROUNDED, ft.Colors.AMBER_500),
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
                            ft.Text(value, size=22, weight=ft.FontWeight.BOLD, color=self.get_text_color()),
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
        """Construye las tablas de métricas en contenedores adaptativos."""
        text_color = self.get_text_color()
        accent = self.get_accent_color()

        # 1. Inteligencia de Negocio
        top_products = [
            ("1", "Laptop Dell XPS 15", "Electrónica", "142 Uds"),
            ("2", "Monitor LG 27 UltraFine", "Periféricos", "98 Uds"),
            ("3", "Teclado Mecánico RGB", "Accesorios", "85 Uds"),
            ("4", "Mouse Inalámbrico Logi", "Accesorios", "74 Uds"),
            ("5", "Disco SSD 1TB NVMe", "Componentes", "62 Uds"),
        ]

        top_rows = []
        for pos, name, cat, qty in top_products:
            top_rows.append(
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(pos, weight=ft.FontWeight.BOLD, color=text_color)),
                        ft.DataCell(ft.Text(name, color=text_color)),
                        ft.DataCell(ft.Text(cat, color=self.get_subtext_color())),
                        ft.DataCell(ft.Text(qty, color=accent, weight=ft.FontWeight.BOLD)),
                    ]
                )
            )

        top_table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("#", color=text_color)),
                ft.DataColumn(ft.Text("Producto", color=text_color)),
                ft.DataColumn(ft.Text("Categoría", color=text_color)),
                ft.DataColumn(ft.Text("Ventas", color=text_color)),
            ],
            rows=top_rows,
        )

        left_section = ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Icon(ft.Icons.LEADERBOARD_ROUNDED, color=accent),
                            ft.Text("Inteligencia de Negocio (Top Más Vendidos)", size=15, weight=ft.FontWeight.BOLD, color=text_color),
                        ],
                        spacing=10,
                    ),
                    ft.Divider(height=10, color=self.get_border_color()),
                    top_table,
                ],
                spacing=10,
            ),
            padding=15,
            border_radius=10,
            bgcolor=self.get_card_bg(),
            border=ft.Border.all(1, self.get_border_color()),
            expand=True,
        )

        # 2. Auditoría Preventiva
        critical_stock = [
            ("Cable HDMI 2.1 2m", "2", "10", "TecnoImport C.A."),
            ("RAM 16GB DDR5 5600", "1", "5", "Global Distribution"),
            ("Impresora HP Smart", "0", "3", "OfiSuministros Vzla"),
            ("Adaptador Ethernet USB-C", "3", "12", "TecnoImport C.A."),
            ("Fuente de Poder 750W", "2", "8", "Global Distribution"),
        ]

        stock_rows = []
        for name, current, min_val, supplier in critical_stock:
            stock_rows.append(
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(name, color=text_color)),
                        ft.DataCell(ft.Text(current, color=ft.Colors.RED_500, weight=ft.FontWeight.BOLD)),
                        ft.DataCell(ft.Text(min_val, color=text_color)),
                        ft.DataCell(ft.Text(supplier, color=self.get_subtext_color())),
                    ]
                )
            )

        stock_table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("Producto", color=text_color)),
                ft.DataColumn(ft.Text("Stock Actual", color=text_color)),
                ft.DataColumn(ft.Text("Mínimo", color=text_color)),
                ft.DataColumn(ft.Text("Proveedor", color=text_color)),
            ],
            rows=stock_rows,
        )

        right_section = ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Icon(ft.Icons.REPORT_PROBLEM_ROUNDED, color=ft.Colors.AMBER_500),
                            ft.Text("Auditoría Preventiva (Stock Crítico)", size=15, weight=ft.FontWeight.BOLD, color=text_color),
                        ],
                        spacing=10,
                    ),
                    ft.Divider(height=10, color=self.get_border_color()),
                    stock_table,
                ],
                spacing=10,
            ),
            padding=15,
            border_radius=10,
            bgcolor=self.get_card_bg(),
            border=ft.Border.all(1, self.get_border_color()),
            expand=True,
        )

        return ft.Row(
            controls=[
                left_section,
                right_section,
            ],
            spacing=20,
            wrap=True,
        )
