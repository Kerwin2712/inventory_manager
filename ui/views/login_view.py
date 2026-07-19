import flet as ft
from ui.views.base_view import BaseView

class LoginView(BaseView):
    """Vista de inicio de sesión."""
    
    def __init__(self):
        super().__init__(route="/login", title="Control de Acceso")

    def get_body(self) -> ft.Control:
        # Campos de entrada de datos
        self.username_input = ft.TextField(
            label="Usuario",
            width=320,
            border_color=ft.colors.BLUE_400,
            focused_border_color=ft.colors.BLUE_200,
        )
        self.password_input = ft.TextField(
            label="Contraseña",
            password=True,
            can_reveal_password=True,
            width=320,
            border_color=ft.colors.BLUE_400,
            focused_border_color=ft.colors.BLUE_200,
        )
        
        # Botón de autenticación
        login_btn = ft.ElevatedButton(
            text="Iniciar Sesión",
            width=320,
            bgcolor=ft.colors.BLUE_600,
            color=ft.colors.WHITE,
            on_click=self.handle_login,
        )
        
        # Etiqueta para mensajes de error
        self.error_text = ft.Text(
            value="",
            color=ft.colors.RED_400,
            size=14,
            visible=False,
        )
        
        # Retorna el contenedor principal centrado
        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Icon(name=ft.icons.LOCK_PERSON_OUTLINED, size=50, color=ft.colors.BLUE_400),
                    self.username_input,
                    self.password_input,
                    self.error_text,
                    ft.Container(height=10),
                    login_btn,
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=15,
            ),
            alignment=ft.alignment.center,
            padding=ft.padding.only(top=40),
        )

    def handle_login(self, e):
        # Validación básica de entradas
        user = self.username_input.value.strip()
        pwd = self.password_input.value.strip()
        
        if not user or not pwd:
            self.error_text.value = "Todos los campos son obligatorios."
            self.error_text.visible = True
        else:
            self.error_text.visible = False
            # Lógica futura de autenticación con base de datos
            print(f"Intento de login: {user}")
            
        self.update()
