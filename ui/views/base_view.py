import flet as ft

class BaseView(ft.View):
    """Clase base que define la estructura visual común."""
    
    def __init__(self, route: str, title: str):
        # Configuraciones visuales comunes
        super().__init__(
            route=route,
            padding=ft.Padding.all(40),
            spacing=20,
            bgcolor=ft.colors.GREY_900,
        )
        self.view_title = title
        self.setup_layout()

    def setup_layout(self):
        # Encabezado estándar para todas las vistas
        header = ft.Text(
            self.view_title,
            size=28,
            weight=ft.FontWeight.BOLD,
            color=ft.colors.BLUE_400,
        )
        
        # Añade el encabezado y el contenido específico
        self.controls = [
            header,
            ft.Divider(height=10, color=ft.colors.GREY_800),
            self.get_body()
        ]

    def get_body(self) -> ft.Control:
        # Método plantilla para ser implementado por vistas hijas
        raise NotImplementedError("Subclasses must implement get_body()")
