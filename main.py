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

    # Instanciar e integrar la vista de login en la pila de vistas de la aplicación
    login_view = LoginView()
    page.views.append(login_view)
    page.update()

if __name__ == "__main__":
    ft.run(main)
