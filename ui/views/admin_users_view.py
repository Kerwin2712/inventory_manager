import flet as ft
from ui.views.base_view import BaseView
from services.user_service import create_user, get_all_users, update_user

class AdminUsersView(BaseView):
    """Vista exclusiva para que el usuario 'admin' inicial cree y gestione otros usuarios."""

    def __init__(self, on_logout_callback=None):
        self.on_logout_callback = on_logout_callback
        self.editing_user_id = None
        super().__init__(route="/admin_users", title="Gestión Exclusiva de Usuarios (Superadmin)")

    def get_body(self) -> ft.Control:
        # Controles del formulario
        self.username_input = ft.TextField(
            label="Nombre de Usuario",
            width=250,
            border_color=ft.Colors.BLUE_400,
        )
        self.password_input = ft.TextField(
            label="Contraseña",
            password=True,
            can_reveal_password=True,
            width=280,
            border_color=ft.Colors.BLUE_400,
            hint_text="Vacío = no cambiar al editar"
        )
        self.role_dropdown = ft.Dropdown(
            label="Rol",
            width=200,
            border_color=ft.Colors.BLUE_400,
            options=[
                ft.dropdown.Option(key="administrador", text="Administrador Real"),
                ft.dropdown.Option(key="vendedor", text="Vendedor"),
            ],
            value="administrador",
        )

        self.save_btn = ft.Button(
            content="Guardar Usuario",
            bgcolor=ft.Colors.BLUE_600,
            color=ft.Colors.WHITE,
            on_click=self.handle_save_user,
        )

        self.cancel_btn = ft.OutlinedButton(
            content="Cancelar Edición",
            visible=False,
            on_click=self.handle_cancel_edit,
        )

        logout_btn = ft.Button(
            content="Cerrar Sesión",
            bgcolor=ft.Colors.RED_600,
            color=ft.Colors.WHITE,
            on_click=self.handle_logout,
        )

        self.msg_text = ft.Text(value="", size=14, visible=False)

        # Controles de tema (Sol/Luna + Selector de Acento)
        theme_icon = ft.Icons.LIGHT_MODE_OUTLINED
        try:
            if self.page and self.page.theme_mode == ft.ThemeMode.LIGHT:
                theme_icon = ft.Icons.DARK_MODE_OUTLINED
        except RuntimeError:
            pass

        theme_toggle_btn = ft.IconButton(
            icon=theme_icon,
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
                            ft.Text(name),
                        ],
                        spacing=10,
                    ),
                    on_click=lambda e, h=hex_val: self.change_seed_color(h),
                )
            )

        color_picker_btn = ft.PopupMenuButton(
            icon=ft.Icons.PALETTE_OUTLINED,
            tooltip="Seleccionar Color de Acento",
            items=color_menu_items,
        )

        # Tabla para listar usuarios
        self.users_table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("ID")),
                ft.DataColumn(ft.Text("Usuario")),
                ft.DataColumn(ft.Text("Rol")),
                ft.DataColumn(ft.Text("Acciones")),
            ],
            rows=[],
        )

        self.refresh_table()

        # Contenedor del formulario
        form_card = ft.Container(
            content=ft.Column(
                controls=[
                    ft.Text("Registrar o Modificar Usuario del Sistema", size=18, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_200),
                    ft.Row(
                        controls=[
                            self.username_input,
                            self.password_input,
                            self.role_dropdown,
                        ],
                        wrap=True,
                        spacing=15,
                    ),
                    ft.Row(
                        controls=[
                            self.save_btn,
                            self.cancel_btn,
                            self.msg_text,
                        ],
                        spacing=15,
                    )
                ],
                spacing=15,
            ),
            padding=20,
            border_radius=10,
            bgcolor=ft.Colors.GREY_800,
        )

        top_header = ft.Row(
            controls=[
                ft.Text("Panel Exclusivo de Cuentas (Superadmin)", size=16, color=ft.Colors.GREY_400),
                ft.Row(
                    controls=[
                        theme_toggle_btn,
                        color_picker_btn,
                        logout_btn,
                    ],
                    spacing=10,
                )
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN
        )

        return ft.Column(
            controls=[
                top_header,
                form_card,
                ft.Divider(height=20, color=ft.Colors.GREY_700),
                ft.Text("Lista de Usuarios Registrados", size=18, weight=ft.FontWeight.BOLD),
                ft.Container(
                    content=self.users_table,
                    padding=10,
                )
            ],
            spacing=15,
            expand=True,
        )

    def refresh_table(self):
        """Carga los usuarios existentes en la tabla."""
        users = get_all_users()
        rows = []
        for u in users:
            edit_btn = ft.IconButton(
                icon=ft.Icons.EDIT,
                icon_color=ft.Colors.BLUE_400,
                tooltip="Editar Usuario",
                data=u,
                on_click=self.start_edit_user,
            )
            
            # Impedir modificar la cuenta admin inicial si es la cuenta del sistema
            action_cell = edit_btn if u["username"] != "admin" else ft.Text("Superadmin Principal", color=ft.Colors.GREY_500)
            
            rows.append(
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(str(u["id"]))),
                        ft.DataCell(ft.Text(u["username"])),
                        ft.DataCell(ft.Text(u["role"])),
                        ft.DataCell(action_cell),
                    ]
                )
            )
        self.users_table.rows = rows

    def handle_save_user(self, e):
        """Guarda o actualiza un usuario."""
        user = self.username_input.value.strip()
        pwd = self.password_input.value.strip()
        role = self.role_dropdown.value

        if not user:
            self.show_message("El nombre de usuario es obligatorio.", is_error=True)
            return

        if self.editing_user_id is None:
            if not pwd:
                self.show_message("La contraseña es requerida para un nuevo usuario.", is_error=True)
                return
            success, msg = create_user(user, pwd, role)
        else:
            success, msg = update_user(self.editing_user_id, user, pwd, role)

        if success:
            self.show_message(msg, is_error=False)
            self.handle_cancel_edit(None)
            self.refresh_table()
        else:
            self.show_message(msg, is_error=True)

        self.update()

    def start_edit_user(self, e):
        """Modo de edición para el usuario seleccionado."""
        user_data = e.control.data
        self.editing_user_id = user_data["id"]
        self.username_input.value = user_data["username"]
        self.password_input.value = ""
        self.role_dropdown.value = user_data["role"]
        self.save_btn.content = "Actualizar Usuario"
        self.cancel_btn.visible = True
        self.show_message(f"Editando usuario ID {user_data['id']}: {user_data['username']}", is_error=False)
        self.update()

    def handle_cancel_edit(self, e):
        """Cancela el modo de edición y limpia los campos."""
        self.editing_user_id = None
        self.username_input.value = ""
        self.password_input.value = ""
        self.role_dropdown.value = "administrador"
        self.save_btn.content = "Guardar Usuario"
        self.cancel_btn.visible = False
        self.update()

    def show_message(self, msg: str, is_error: bool):
        """Muestra un mensaje de retroalimentación."""
        self.msg_text.value = msg
        self.msg_text.color = ft.Colors.RED_400 if is_error else ft.Colors.GREEN_400
        self.msg_text.visible = True

    def handle_logout(self, e):
        """Maneja el cierre de sesión."""
        if self.on_logout_callback:
            self.on_logout_callback()
