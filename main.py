import os
import sys
import threading
import time
import flet as ft
from core.database import init_db, get_setting
from ui.views.base_view import BaseView
from ui.views.login_view import LoginView
from ui.views.admin_users_view import AdminUsersView
from ui.views.dashboard_view import DashboardView
from services.cart_manager import limpiar_sesion

def _silenciar_desconexion_windows():
    """Silencia el error WinError 10054 en Windows al cerrar la ventana de la aplicación Flet."""
    if sys.platform != "win32":
        return
    try:
        from asyncio.proactor_events import _ProactorBasePipeTransport
        _orig_call_connection_lost = _ProactorBasePipeTransport._call_connection_lost

        def _silent_call_connection_lost(self, exc):
            try:
                _orig_call_connection_lost(self, exc)
            except (ConnectionResetError, OSError):
                pass

        _ProactorBasePipeTransport._call_connection_lost = _silent_call_connection_lost
    except Exception:
        pass

_silenciar_desconexion_windows()

def _iniciar_vigilante_cierre(page: ft.Page):
    """Monitorea el ciclo de vida de la ventana y la conexión socket cliente para garantizar
    que el proceso Python termine de inmediato si la ventana se cierra por cualquier motivo."""
    def _vigilante():
        time.sleep(2.0)  # Esperar a que la ventana y el cliente Flutter se inicien completamente
        session = getattr(page, "session", None)
        conn = getattr(session, "connection", None) if session else None
        while True:
            time.sleep(0.5)
            # 1. Si la sesión fue marcada como cerrada internamente
            if session and getattr(session, "_Session__closed", False):
                os._exit(0)
            # 2. Si la tarea de recepción de socket terminó (el cliente cerró el socket)
            if conn:
                task = getattr(conn, "_FletSocketServer__receive_loop_task", None)
                if task and task.done():
                    os._exit(0)
                if hasattr(conn, "_FletSocketServer__connected") and conn._FletSocketServer__connected is False:
                    os._exit(0)

    t = threading.Thread(target=_vigilante, daemon=True, name="WatchdogCierreVentana")
    t.start()

def main(page: ft.Page):
    # Inicializar la base de datos SQLite, tablas y datos por defecto
    init_db()

    def _terminar_aplicacion(e=None):
        """Limpia la sesión activa y termina el proceso Python de forma inmediata al cerrar."""
        try:
            limpiar_sesion(page.session.id)
        except Exception:
            pass
        os._exit(0)

    def _al_evento_ventana(e):
        """Intercepta el evento nativo de cierre de la ventana de escritorio."""
        tipo = getattr(e, "type", None)
        if tipo in (ft.WindowEventType.CLOSE, "close"):
            _terminar_aplicacion(e)

    # Configurar interceptor nativo de cierre de ventana
    try:
        page.window.prevent_close = True
        page.window.on_event = _al_evento_ventana
    except (RuntimeError, AttributeError):
        pass

    # Fallbacks para eventos de cierre y desconexión
    try:
        page.on_close = _terminar_aplicacion
        page.on_disconnect = _terminar_aplicacion
    except (RuntimeError, AttributeError):
        pass

    # Iniciar vigilante en segundo plano para garantizar salida si el cliente Flutter finaliza
    _iniciar_vigilante_cierre(page)

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


    
    try:
        page.window.maximized = True
    except AttributeError:
        try:
            page.window_state = ft.WindowState.MAXIMIZED
        except AttributeError:
            pass

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
    # Modo escritorio (ventana nativa Flutter) — build de producción y del
    # instalador (PyInstaller + Inno Setup, ver installer/README.md). Para
    # probar en un entorno sin soporte de ventana nativa, usar en su lugar:
    # ft.run(main, view=ft.AppView.WEB_BROWSER, port=8550)
    try:
        ft.run(main)
    finally:
        import os
        os._exit(0)
