import flet as ft
from ui.views.base_view import BaseView
from services.user_service import authenticate_user

class LoginView(BaseView):
    """Vista de inicio de sesión con adaptación dinámica de tema."""
    
    def __init__(self, on_login_success=None):
        self.on_login_success = on_login_success
        super().__init__(route="/login", title="Control de Acceso")

    def setup_layout(self):
        # Layout limpio para el login, sin cabeceras redundantes
        try:
            self.bgcolor = self.get_bg_color()
            self.controls = [
                self.get_body()
            ]
        except Exception as e:
            # Imprime el traceback en la consola
            import traceback
            import sys
            traceback.print_exc(file=sys.stderr)
            
            error_details = f"Error: {str(e)}\n\n{traceback.format_exc()}"
            
            def handle_copy(e_click):
                p = self.get_current_page(e_click)
                if p:
                    p.set_clipboard(error_details)
                    self.show_alert_info("Detalles del error copiados al portapapeles.", e_click)

            self.controls = [
                ft.Container(
                    content=ft.Column([
                        ft.Text("Error en Login", size=20, color=ft.Colors.RED_500, weight=ft.FontWeight.BOLD),
                        ft.Text(str(e), color=self.get_text_color(), text_align=ft.TextAlign.CENTER),
                        ft.Container(height=5),
                        ft.ElevatedButton(
                            content=ft.Row([
                                ft.Icon(ft.Icons.COPY_ALL_ROUNDED, size=18),
                                ft.Text("Copiar detalles del error", weight=ft.FontWeight.BOLD)
                            ], tight=True),
                            on_click=handle_copy
                        )
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10),
                    alignment=ft.Alignment.CENTER,
                    expand=True
                )
            ]

    def get_body(self) -> ft.Control:
        accent = self.get_accent_color()
        text_color = self.get_text_color()

        # Insignia de seguridad circular superior
        avatar_icon = ft.Container(
            content=ft.Icon(ft.Icons.LOCK_PERSON_OUTLINED, size=32, color=accent),
            bgcolor=ft.Colors.with_opacity(0.1, accent),
            width=64,
            height=64,
            border_radius=32,
            alignment=ft.Alignment.CENTER,
        )

        # Textos estilizados de cabecera
        title_text = ft.Text(
            "Bienvenido al Sistema",
            size=22,
            weight=ft.FontWeight.BOLD,
            color=text_color,
            text_align=ft.TextAlign.CENTER,
        )
        subtitle_text = ft.Text(
            "Ingrese sus credenciales de seguridad",
            size=13,
            color=self.get_subtext_color(),
            text_align=ft.TextAlign.CENTER,
        )

        # Campos de entrada de datos con prefijo y borde dinámico
        self.username_input = ft.TextField(
            label="Usuario",
            width=320,
            border_radius=12,
            border_color=self.get_border_color(),
            focused_border_color=accent,
            label_style=ft.TextStyle(color=self.get_subtext_color()),
            color=text_color,
            prefix_icon=ft.Icons.PERSON_ROUNDED,
            on_submit=self.handle_login,
        )
        self.password_input = ft.TextField(
            label="Contraseña",
            password=True,
            can_reveal_password=True,
            width=320,
            border_radius=12,
            border_color=self.get_border_color(),
            focused_border_color=accent,
            label_style=ft.TextStyle(color=self.get_subtext_color()),
            color=text_color,
            prefix_icon=ft.Icons.LOCK_ROUNDED,
            on_submit=self.handle_login,
        )
        
        # Botón de autenticación elevado con ícono
        login_btn = ft.ElevatedButton(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.LOGIN_ROUNDED, size=18, color=ft.Colors.WHITE),
                    ft.Text("Iniciar Sesión", weight=ft.FontWeight.BOLD, size=15),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                tight=True,
            ),
            width=320,
            height=46,
            style=ft.ButtonStyle(
                bgcolor=accent,
                color=ft.Colors.WHITE,
                shape=ft.RoundedRectangleBorder(radius=12),
            ),
            on_click=self.handle_login,
        )
        
        # Etiqueta para mensajes de error
        self.error_text = ft.Text(
            value="",
            color=ft.Colors.RED_500,
            size=13,
            visible=False,
            text_align=ft.TextAlign.CENTER,
        )
        
        # Sombra premium de elevación
        shadow = [
            ft.BoxShadow(
                spread_radius=1,
                blur_radius=25,
                color=ft.Colors.with_opacity(0.4, "#020617") if self.is_dark else ft.Colors.with_opacity(0.12, "#475569"),
                offset=ft.Offset(0, 10),
            )
        ]

        # Construcción de tarjeta con bordes e interacciones premium
        login_card = ft.Container(
            content=ft.Column(
                controls=[
                    avatar_icon,
                    ft.Column([
                        title_text,
                        subtitle_text,
                    ], spacing=4, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                    ft.Container(height=4), # Espaciador
                    self.username_input,
                    self.password_input,
                    self.error_text,
                    ft.Container(height=4), # Espaciador
                    login_btn,
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=15,
            ),
            bgcolor=self.get_card_bg(),
            border=ft.Border.all(1.5, ft.Colors.with_opacity(0.15, accent) if self.is_dark else self.get_border_color()),
            shadow=shadow,
            padding=ft.Padding(30, 30, 30, 30),
            border_radius=24,
            width=380,
        )
        
        # Contenedor principal con gradiente de profundidad de fondo
        return ft.Container(
            content=login_card,
            alignment=ft.Alignment.CENTER,
            expand=True,
            gradient=ft.LinearGradient(
                begin=ft.alignment.top_left,
                end=ft.alignment.bottom_right,
                colors=["#0F172A", "#1E1B4B"] if self.is_dark else ["#F8FAFC", "#E2E8F0"],
            )
        )

    def handle_login(self, e):
        # Validación básica de entradas
        user = self.username_input.value.strip()
        pwd = self.password_input.value.strip()
        
        if not user or not pwd:
            self.error_text.value = "Todos los campos son obligatorios."
            self.error_text.visible = True
            self.update()
            return

        # Autenticación contra SQLite
        auth_user = authenticate_user(user, pwd)
        
        if auth_user:
            self.error_text.visible = False
            self.username_input.value = ""
            self.password_input.value = ""
            self.update()
            
            if self.on_login_success:
                self.on_login_success(auth_user)
        else:
            self.error_text.value = "Usuario o contraseña incorrectos."
            self.error_text.visible = True
            self.update()
