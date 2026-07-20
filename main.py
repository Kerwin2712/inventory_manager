import flet as ft
from core.database import init_db, get_setting
from ui.views.base_view import BaseView
from ui.views.login_view import LoginView
from ui.views.admin_users_view import AdminUsersView
from ui.views.dashboard_view import DashboardView

def main(page: ft.Page):
    # Inicializar la base de datos SQLite, tablas y datos por defecto
    init_db()

    # Cargar preferencias de tema guardadas desde SQLite
    saved_mode = get_setting("theme_mode", "dark")
    saved_color = get_setting("seed_color", "#2196F3")
    
    initial_theme_mode = ft.ThemeMode.LIGHT if saved_mode == "light" else ft.ThemeMode.DARK
    BaseView.current_theme_mode = initial_theme_mode
    BaseView.current_seed_color = saved_color

    # Configuración de propiedades de la ventana y tema
    page.title = "Sistema Integrado de Inventario y Ventas"
    page.theme_mode = initial_theme_mode
    page.theme = ft.Theme(color_scheme_seed=saved_color)
    
    # Manejo de tamaño mínimo compatible
    try:
        page.window.min_width = 1000
        page.window.min_height = 700
    except AttributeError:
        try:
            page.window_min_width = 1000
            page.window_min_height = 700
        except AttributeError:
            pass

    def show_login():
        """Muestra la vista de inicio de sesión."""
        page.views.clear()
        login_view = LoginView(on_login_success=on_login_success)
        page.views.append(login_view)
        page.update()

    def show_dashboard(user: dict):
        """Muestra el Dashboard principal para los usuarios del sistema."""
        page.views.clear()
        dashboard_view = DashboardView(
            user_info=user,
            on_logout_callback=show_login,
        )
        page.views.append(dashboard_view)
        page.update()

    def show_admin_users():
        """Muestra la vista aislada para que el usuario 'admin' cree y modifique usuarios."""
        page.views.clear()
        admin_users_view = AdminUsersView(on_logout_callback=show_login)
        page.views.append(admin_users_view)
        page.update()

    def on_login_success(user: dict):
        """Redirige según el usuario autenticado: 'admin' va a su vista exclusiva de gestión de usuarios; los demás al Dashboard."""
        if user["username"] == "admin":
            show_admin_users()
        else:
            show_dashboard(user)

    # Arrancar mostrando la pantalla de inicio de sesión
    show_login()

if __name__ == "__main__":
    ft.run(main)
