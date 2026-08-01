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
                    try:
                        p.clipboard = error_details
                    except AttributeError:
                        try:
                            p.set_clipboard(error_details)
                        except AttributeError:
                            pass
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

        # Título en negrita y centrado
        title_text = ft.Text(
            "Iniciar sesión",
            size=24,
            weight=ft.FontWeight.BOLD,
            color=text_color,
            text_align=ft.TextAlign.CENTER,
        )

        # Campos de entrada de datos sin íconos y con fondos oscuros
        self.username_input = ft.TextField(
            label="Usuario",
            width=320,
            border_radius=8,
            border_color="#343644" if self.is_dark else "#94A3B8",
            focused_border_color="#90CAF9" if self.is_dark else accent,
            label_style=ft.TextStyle(color=self.get_subtext_color()),
            color=text_color,
            filled=True,
            bgcolor="#1D1E27" if self.is_dark else "#F8FAFC",
            on_submit=self.handle_login,
        )
        self.password_input = ft.TextField(
            label="Contraseña",
            password=True,
            can_reveal_password=True,
            width=320,
            border_radius=8,
            border_color="#343644" if self.is_dark else "#94A3B8",
            focused_border_color="#90CAF9" if self.is_dark else accent,
            label_style=ft.TextStyle(color=self.get_subtext_color()),
            color=text_color,
            filled=True,
            bgcolor="#1D1E27" if self.is_dark else "#F8FAFC",
            on_submit=self.handle_login,
        )
        
        # Botón de inicio de sesión estilo píldora oscuro
        login_btn = ft.Button(
            content=ft.Text("Iniciar sesión", weight=ft.FontWeight.BOLD, color="#90CAF9" if self.is_dark else accent, size=15),
            width=320,
            height=44,
            style=ft.ButtonStyle(
                bgcolor="#15161D" if self.is_dark else "#E2E8F0",
                shape=ft.RoundedRectangleBorder(radius=22),
            ),
            on_click=self.handle_login,
        )
        
        # Mensajes de error en rojo
        self.error_text = ft.Text(
            value="",
            color=ft.Colors.RED_500,
            size=13,
            visible=False,
            text_align=ft.TextAlign.CENTER,
        )
        
        # Sombra suave de elevación
        shadow = [
            ft.BoxShadow(
                spread_radius=0,
                blur_radius=15,
                color=ft.Colors.with_opacity(0.2, "#000000") if self.is_dark else ft.Colors.with_opacity(0.08, "#475569"),
                offset=ft.Offset(0, 6),
            )
        ]

        # Contenedor de la tarjeta del login ajustado al contenido con altura fija
        login_card = ft.Container(
            content=ft.Column(
                controls=[
                    title_text,
                    ft.Container(height=4), # Pequeña separación del título
                    self.username_input,
                    self.password_input,
                    self.error_text,
                    ft.Container(height=2), # Pequeña separación del botón
                    login_btn,
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=20,
                tight=True,
            ),
            bgcolor="#21222C" if self.is_dark else ft.Colors.WHITE,
            border=ft.Border.all(1, "#2C2D3A" if self.is_dark else "#E2E8F0"),
            shadow=shadow,
            padding=ft.Padding(30, 40, 30, 40),
            border_radius=16,
            width=380,
            height=370,
        )
        
        # Contenedor principal con fondo plano negro/gris oscuro
        return ft.Container(
            content=login_card,
            alignment=ft.Alignment.CENTER,
            expand=True,
            bgcolor="#0B0C10" if self.is_dark else "#F1F5F9",
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
