import flet as ft
from ui.views.base_view import BaseView
from services.user_service import authenticate_user

class LoginView(BaseView):
    """Vista de inicio de sesión con adaptación dinámica de tema."""
    
    def __init__(self, on_login_success=None):
        self.on_login_success = on_login_success
        super().__init__(route="/login", title="Control de Acceso")

    def get_body(self) -> ft.Control:
        accent = self.get_accent_color()
        text_color = self.get_text_color()

        # Campos de entrada de datos
        self.username_input = ft.TextField(
            label="Usuario",
            width=320,
            border_color=accent,
            focused_border_color=accent,
            label_style=ft.TextStyle(color=self.get_subtext_color()),
            color=text_color,
            on_submit=self.handle_login,
        )
        self.password_input = ft.TextField(
            label="Contraseña",
            password=True,
            can_reveal_password=True,
            width=320,
            border_color=accent,
            focused_border_color=accent,
            label_style=ft.TextStyle(color=self.get_subtext_color()),
            color=text_color,
            on_submit=self.handle_login,
        )
        
        # Botón de autenticación
        login_btn = ft.Button(
            content="Iniciar Sesión",
            width=320,
            bgcolor=accent,
            color=ft.Colors.WHITE,
            on_click=self.handle_login,
        )
        
        # Etiqueta para mensajes de error
        self.error_text = ft.Text(
            value="",
            color=ft.Colors.RED_500,
            size=14,
            visible=False,
        )
        
        # Retorna el contenedor principal centrado
        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Icon(icon=ft.Icons.LOCK_PERSON_OUTLINED, size=50, color=accent),
                    self.username_input,
                    self.password_input,
                    self.error_text,
                    ft.Container(height=10),
                    login_btn,
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=15,
            ),
            alignment=ft.Alignment.CENTER,
            padding=ft.Padding.only(top=40),
            expand=True,
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
