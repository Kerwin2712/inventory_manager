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
            border_radius=12,
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
            border_radius=12,
            border_color=accent,
            focused_border_color=accent,
            label_style=ft.TextStyle(color=self.get_subtext_color()),
            color=text_color,
            on_submit=self.handle_login,
        )
        
        # Botón de autenticación
        login_btn = ft.Button(
            content=ft.Text("Iniciar Sesión", weight=ft.FontWeight.BOLD),
            width=320,
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
            size=14,
            visible=False,
        )
        
        # Retorna el contenedor principal centrado
        login_card = self.create_card(
            content=ft.Column(
                controls=[
                    ft.Icon(name=ft.Icons.LOCK_PERSON_OUTLINED, size=50, color=accent),
                    ft.Text("Control de Acceso", size=20, weight=ft.FontWeight.BOLD, color=text_color),
                    ft.Container(height=5),
                    self.username_input,
                    self.password_input,
                    self.error_text,
                    ft.Container(height=10),
                    login_btn,
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=15,
            ),
            padding=30,
            border_radius=20,
        )
        login_card.width = 380
        
        return ft.Container(
            content=login_card,
            alignment=ft.Alignment.CENTER,
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
