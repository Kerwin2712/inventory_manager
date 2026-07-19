import flet as ft
from ui.views.login_view import LoginView

def main(page: ft.Page):
    # Configuración de propiedades básicas de la ventana
    page.title = "Sistema Integrado de Inventario y Ventas"
    page.theme_mode = ft.ThemeMode.DARK
    
    # Manejo de tamaño mínimo compatible con distintas versiones de Flet
    try:
        page.window.min_width = 800
        page.window.min_height = 600
    except AttributeError:
        try:
            page.window_min_width = 800
            page.window_min_height = 600
        except AttributeError:
            pass

    # Instanciar la vista de login
    login_view = LoginView()
    
    # Agregar la vista a la página
    page.add(login_view)

if __name__ == "__main__":
    ft.app(target=main)
