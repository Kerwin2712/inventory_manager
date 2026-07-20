import flet as ft

class BaseView(ft.View):
    """Clase base que define la estructura visual común y gestión centralizada de temas."""
    
    def __init__(self, route: str, title: str):
        super().__init__(
            route=route,
            padding=ft.Padding.all(20),
            spacing=15,
        )
        self.view_title = title
        self.setup_layout()

    def setup_layout(self):
        """Estructura por defecto para las vistas que heredan."""
        header = ft.Text(
            self.view_title,
            size=26,
            weight=ft.FontWeight.BOLD,
            color=ft.Colors.BLUE_400,
        )
        
        self.controls = [
            header,
            ft.Divider(height=10, color=ft.Colors.GREY_800),
            self.get_body()
        ]

    def get_body(self) -> ft.Control:
        """Método plantilla a implementar por cada pantalla."""
        raise NotImplementedError("Las subclases deben implementar get_body()")

    def toggle_theme(self, e=None):
        """Alterna dinámicamente entre el modo claro y oscuro en la aplicación."""
        if not self.page:
            return
            
        # PERSISTENCIA FUTURA DE TEMAS:
        # Aquí se leerá/actualizará el parámetro 'theme_mode' de la sesión del usuario en SQLite:
        # user_service.update_user_theme_preference(user_id, new_mode)
        
        if self.page.theme_mode == ft.ThemeMode.DARK:
            self.page.theme_mode = ft.ThemeMode.LIGHT
        else:
            self.page.theme_mode = ft.ThemeMode.DARK
            
        self.page.update()

    def change_seed_color(self, color_hex: str):
        """Actualiza el color de acento global (color_scheme_seed) de la aplicación."""
        if not self.page:
            return
            
        # PERSISTENCIA FUTURA DE TEMAS:
        # Aquí se persistirá la preferencia 'color_scheme_seed' en la base de datos para la cuenta activa:
        # user_service.update_user_seed_color_preference(user_id, color_hex)
        
        self.page.theme = ft.Theme(color_scheme_seed=color_hex)
        self.page.update()
