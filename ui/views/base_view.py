import flet as ft

class BaseView(ft.View):
    """Clase base que define la estructura visual común y gestión centralizada de temas."""
    
    # Estado estático global para persistencia entre vistas
    current_seed_color = "#2196F3"
    current_theme_mode = ft.ThemeMode.DARK
    
    def __init__(self, route: str, title: str):
        super().__init__(
            route=route,
            padding=ft.Padding.all(20),
            spacing=15,
        )
        self.view_title = title
        self.bgcolor = self.get_bg_color()
        self.setup_layout()

    @property
    def is_dark(self) -> bool:
        """Indica si la aplicación se encuentra en modo oscuro."""
        try:
            if self.page and self.page.theme_mode is not None:
                return self.page.theme_mode == ft.ThemeMode.DARK
        except (RuntimeError, AttributeError):
            pass
        return BaseView.current_theme_mode == ft.ThemeMode.DARK

    def get_accent_color(self) -> str:
        """Obtiene el color de acento actual."""
        return BaseView.current_seed_color

    def get_bg_color(self) -> str:
        """Fondo neutro de la aplicación (evita tintes no deseados)."""
        return "#0F172A" if self.is_dark else "#F1F5F9"

    def get_sidebar_bg(self) -> str:
        """Fondo de la barra lateral (blanco impecable en modo claro)."""
        return "#1E293B" if self.is_dark else ft.Colors.WHITE

    def get_card_bg(self) -> str:
        """Fondo para tarjetas, tablas y contenedores."""
        return "#1E293B" if self.is_dark else ft.Colors.WHITE

    def get_text_color(self) -> str:
        """Color de texto principal (alto contraste)."""
        return ft.Colors.WHITE if self.is_dark else "#0F172A"

    def get_subtext_color(self) -> str:
        """Color de texto secundario y etiquetas."""
        return ft.Colors.GREY_400 if self.is_dark else "#475569"

    def get_border_color(self) -> str:
        """Color de bordes y divisores."""
        return ft.Colors.GREY_800 if self.is_dark else "#CBD5E1"

    def setup_layout(self):
        """Estructura por defecto para las vistas que heredan."""
        header = ft.Text(
            self.view_title,
            size=26,
            weight=ft.FontWeight.BOLD,
            color=self.get_accent_color(),
        )
        
        self.bgcolor = self.get_bg_color()
        self.controls = [
            header,
            ft.Divider(height=10, color=self.get_border_color()),
            self.get_body()
        ]

    def get_body(self) -> ft.Control:
        """Método plantilla a implementar por cada pantalla."""
        raise NotImplementedError("Las subclases deben implementar get_body()")

    def toggle_theme(self, e=None):
        """Alterna dinámicamente entre el modo claro y oscuro."""
        if not self.page:
            return
            
        if self.page.theme_mode == ft.ThemeMode.DARK:
            self.page.theme_mode = ft.ThemeMode.LIGHT
        else:
            self.page.theme_mode = ft.ThemeMode.DARK
            
        BaseView.current_theme_mode = self.page.theme_mode
        self.rebuild_ui()

    def change_seed_color(self, color_hex: str):
        """Actualiza el color de acento global y refresca la interfaz."""
        if not self.page:
            return
            
        BaseView.current_seed_color = color_hex
        self.page.theme = ft.Theme(color_scheme_seed=color_hex)
        self.rebuild_ui()

    def rebuild_ui(self):
        """Reconstruye los controles de la vista con las nuevas propiedades visuales."""
        self.bgcolor = self.get_bg_color()
        self.setup_layout()
        if self.page:
            self.page.update()
