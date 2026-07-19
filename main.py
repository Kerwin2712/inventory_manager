import flet as ft
from core.database import init_db
from ui.views.login_view import LoginView
from ui.views.admin_users_view import AdminUsersView

def main(page: ft.Page):
    # Inicializar la base de datos SQLite y sembrar la cuenta admin
    init_db()

    # Configuración de propiedades básicas de la ventana
    page.title = "Sistema Integrado de Inventario y Ventas"
    page.theme_mode = ft.ThemeMode.DARK
    
    # Manejo de tamaño mínimo compatible
    try:
        page.window.min_width = 850
        page.window.min_height = 650
    except AttributeError:
        try:
            page.window_min_width = 850
            page.window_min_height = 650
        except AttributeError:
            pass

    def show_login():
        """Muestra la vista de inicio de sesión."""
        page.views.clear()
        login_view = LoginView(on_login_success=on_login_success)
        page.views.append(login_view)
        page.update()

    def on_login_success(user: dict):
        """Maneja la navegación tras un inicio de sesión exitoso según el usuario/rol."""
        page.views.clear()
        
        if user["username"] == "admin":
            # Redirección exclusiva para el usuario admin inicial a la gestión de usuarios
            admin_view = AdminUsersView(on_logout_callback=show_login)
            page.views.append(admin_view)
        else:
            # Vista temporal para usuarios generales (administrador real o vendedores)
            welcome_text = ft.Text(
                f"¡Bienvenido/a, {user['username']}! (Rol: {user['role']})",
                size=22,
                weight=ft.FontWeight.BOLD,
                color=ft.Colors.BLUE_400
            )
            logout_btn = ft.ElevatedButton(
                content="Cerrar Sesión",
                bgcolor=ft.Colors.RED_600,
                color=ft.Colors.WHITE,
                on_click=lambda e: show_login()
            )
            welcome_view = ft.View(
                route="/dashboard",
                padding=ft.Padding.all(40),
                bgcolor=ft.Colors.GREY_900,
                controls=[
                    welcome_text,
                    ft.Text("Módulo principal en desarrollo...", size=16, color=ft.Colors.GREY_400),
                    ft.Container(height=20),
                    logout_btn
                ]
            )
            page.views.append(welcome_view)
            
        page.update()

    # Arrancar mostrando la pantalla de login
    show_login()

if __name__ == "__main__":
    ft.run(main)
