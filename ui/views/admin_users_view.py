import flet as ft
from ui.views.base_view import BaseView
from services.user_service import create_user, get_all_users, update_user

class AdminUsersView(BaseView):
    """Vista exclusiva para que el usuario 'admin' inicial cree y gestione otros usuarios."""

    def __init__(self, on_logout_callback=None):
        self.on_logout_callback = on_logout_callback
        self.editing_user_id = None
        super().__init__(route="/admin_users", title="Gestión de Usuarios | SuperAdmin")

    def get_body(self) -> ft.Control:
        accent = self.get_accent_color()
        text_color = self.get_text_color()

        # Controles del formulario
        self.username_input = ft.TextField(
            label="Nombre de Usuario",
            width=250,
            border_color=self.get_border_color(),
            label_style=ft.TextStyle(color=self.get_subtext_color()),
            color=text_color,
            border_radius=12,
        )
        self.password_input = ft.TextField(
            label="Contraseña",
            password=True,
            can_reveal_password=True,
            width=280,
            border_color=self.get_border_color(),
            label_style=ft.TextStyle(color=self.get_subtext_color()),
            color=text_color,
            hint_text="Vacío = no cambiar al editar",
            border_radius=12,
        )
        self.role_dropdown = ft.Dropdown(
            label="Rol",
            width=200,
            border_color=self.get_border_color(),
            label_style=ft.TextStyle(color=self.get_subtext_color()),
            color=text_color,
            options=[
                ft.dropdown.Option(key="administrador", text="Administrador Real"),
                ft.dropdown.Option(key="vendedor", text="Vendedor"),
            ],
            value="administrador",
            border_radius=12,
        )

        self.save_btn = ft.Button(
            content=ft.Text("Guardar Usuario", weight=ft.FontWeight.BOLD),
            style=ft.ButtonStyle(
                bgcolor=accent,
                color=ft.Colors.WHITE,
                shape=ft.RoundedRectangleBorder(radius=12),
            ),
            on_click=self.handle_save_user,
        )

        self.cancel_btn = ft.OutlinedButton(
            content="Cancelar Edición",
            visible=False,
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=12),
            ),
            on_click=self.handle_cancel_edit,
        )

        logout_btn = ft.Button(
            content=ft.Text("Cerrar Sesión", weight=ft.FontWeight.BOLD),
            style=ft.ButtonStyle(
                bgcolor=ft.Colors.RED_600,
                color=ft.Colors.WHITE,
                shape=ft.RoundedRectangleBorder(radius=12),
            ),
            on_click=self.handle_logout,
        )

        self.msg_text = ft.Text(value="", size=14, visible=False)

        # Controles de tema
        theme_toggle_btn = ft.IconButton(
            icon=ft.Icons.LIGHT_MODE_OUTLINED if self.is_dark else ft.Icons.DARK_MODE_OUTLINED,
            icon_color=text_color,
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
                            ft.Text(name, color=text_color),
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

        # Tabla para listar usuarios
        self.users_table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("ID", color=text_color)),
                ft.DataColumn(ft.Text("Usuario", color=text_color)),
                ft.DataColumn(ft.Text("Rol", color=text_color)),
                ft.DataColumn(ft.Text("Acciones", color=text_color)),
            ],
            rows=[],
        )

        self.refresh_table()

        # Contenedor del formulario
        form_card = self.create_card(
            content=ft.Column(
                controls=[
                    ft.Text("Registrar o Modificar Usuario del Sistema", size=18, weight=ft.FontWeight.BOLD, color=accent),
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
            border_radius=16,
        )

        from services.printer_service import (
            detectar_impresora_termica,
            listar_impresoras_sistema,
            guardar_impresora_termica_configurada,
            obtener_impresora_termica_configurada,
            imprimir_ticket_prueba,
        )
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
                        color=text_color,
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

        user_icon = ft.Icon(ft.Icons.ADMIN_PANEL_SETTINGS, color=accent, size=22)

        top_header = ft.Row(
            controls=[
                ft.Row(
                    controls=[
                        user_icon,
                        ft.Text("Panel de Cuentas | SuperAdmin", size=16, color=text_color, weight=ft.FontWeight.BOLD),
                    ],
                    spacing=8,
                ),
                ft.Row(
                    controls=[
                        printer_btn,
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
                ft.Divider(height=20, color=self.get_border_color()),
                ft.Text("Lista de Usuarios Registrados", size=18, weight=ft.FontWeight.BOLD, color=text_color),
                self.create_card(
                    content=self.users_table,
                    padding=10,
                    border_radius=18
                )
            ],
            spacing=15,
            expand=True,
        )

    def refresh_table(self):
        """Carga los usuarios existentes en la tabla adaptando los colores."""
        users = get_all_users()
        rows = []
        text_color = self.get_text_color()
        accent = self.get_accent_color()

        for u in users:
            edit_btn = ft.IconButton(
                icon=ft.Icons.EDIT,
                icon_color=accent,
                tooltip="Editar Usuario",
                data=u,
                on_click=self.start_edit_user,
            )
            
            action_cell = edit_btn if u["username"] != "admin" else ft.Text("Superadmin Principal", color=self.get_subtext_color())
            
            rows.append(
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(str(u["id"]), color=text_color)),
                        ft.DataCell(ft.Text(u["username"], color=text_color)),
                        ft.DataCell(ft.Text(u["role"], color=text_color)),
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
        self.msg_text.color = ft.Colors.RED_500 if is_error else ft.Colors.GREEN_500
        self.msg_text.visible = True

    def handle_logout(self, e):
        """Maneja el cierre de sesión."""
        if self.on_logout_callback:
            self.on_logout_callback()

    def abrir_dialogo_configuracion_impresora(self, e=None):
        """Diálogo para configurar la impresora térmica preferida y probar impresión."""
        from services.printer_service import (
            listar_impresoras_sistema,
            guardar_impresora_termica_configurada,
            obtener_impresora_termica_configurada,
            imprimir_ticket_prueba,
        )

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

        def guardar_config(ev):
            seleccion = dd_impresoras.value or ""
            guardar_impresora_termica_configurada(seleccion)
            self.cerrar_dialogo(dlg_conf, ev)
            self.show_alert_success(f"Configuración guardada: {seleccion or 'Detección automática'}", ev)
            self.rebuild_ui()

        def probar_impresion(ev):
            sel = dd_impresoras.value or None
            ok, msg = imprimir_ticket_prueba(nombre_impresora=sel)
            if ok:
                self.show_alert_success("¡Ticket de prueba enviado con éxito a la impresora!", ev)
            else:
                self.show_alert_error(f"Error al enviar prueba: {msg}", ev)

        dlg_conf = ft.AlertDialog(
            title=ft.Row([ft.Icon(ft.Icons.PRINT_ROUNDED, color=ft.Colors.BLUE_400), ft.Text("Configurar Impresora Térmica")]),
            content=ft.Column([
                ft.Text("Seleccione la impresora para emitir los tickets de venta (80mm)."),
                dd_impresoras,
                ft.Text("Compatible con MP80-12, MPT-II, POS-80 (USB / Bluetooth).", size=11, color=self.get_subtext_color()),
            ], tight=True, spacing=12),
            actions=[
                ft.TextButton("Cerrar", on_click=lambda ev: self.cerrar_dialogo(dlg_conf, ev)),
                ft.OutlinedButton("Imprimir Ticket de Prueba", icon=ft.Icons.RECEIPT, on_click=probar_impresion),
                ft.Button("Guardar", icon=ft.Icons.CHECK, on_click=guardar_config,
                          style=ft.ButtonStyle(bgcolor=ft.Colors.GREEN_700, color=ft.Colors.WHITE)),
            ],
            actions_alignment=ft.MainAxisAlignment.END
        )
        self.abrir_dialogo(dlg_conf, e)
