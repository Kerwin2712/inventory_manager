import asyncio
import os
import signal
import sys
import flet as ft
from core.database import init_db, get_setting
from ui.views.base_view import BaseView
from ui.views.login_view import LoginView
from ui.views.admin_users_view import AdminUsersView
from ui.views.dashboard_view import DashboardView
from services.cart_manager import limpiar_sesion

def _parchear_salida_limpia_windows():
    """Aplica parches para Windows que previenen bloqueos de terminal y ventanas colgadas:
    1. Silencia el error WinError 10054 al desconectar el socket proactor.
    2. Corrige el bug en flet_desktop.close_flet_view que intenta usar signal.SIGKILL (inexistente en Windows).
    3. Asegura que al cerrar la conexión socket del servidor Flet, Python termine de inmediato sin colgarse."""
    if sys.platform != "win32":
        return

    # 1. Silenciar WinError 10054 en Proactor
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

    # 2. Corregir señal de terminación de proceso en flet_desktop
    try:
        import flet_desktop
        def _patched_close_flet_view(pid_file):
            if pid_file is not None and os.path.exists(pid_file):
                try:
                    with open(pid_file, encoding="utf-8") as f:
                        fvp_pid = int(f.read())
                    sig = getattr(signal, "SIGKILL", signal.SIGTERM)
                    os.kill(fvp_pid, sig)
                except Exception:
                    pass
                finally:
                    if os.path.exists(pid_file):
                        os.remove(pid_file)

        flet_desktop.close_flet_view = _patched_close_flet_view
    except Exception:
        pass

    # 3. Terminar el proceso Python inmediatamente al cerrarse la sesión y socket de Flet
    try:
        from flet.messaging.flet_socket_server import FletSocketServer
        _orig_socket_close = FletSocketServer.close

        async def _safe_socket_close(self):
            try:
                if getattr(self, "session", None) and hasattr(self.session, "id"):
                    limpiar_sesion(self.session.id)
            except Exception:
                pass
            try:
                await asyncio.wait_for(_orig_socket_close(self), timeout=1.0)
            except Exception:
                pass
            finally:
                os._exit(0)

        FletSocketServer.close = _safe_socket_close
    except Exception:
        pass

_parchear_salida_limpia_windows()

def main(page: ft.Page):
    # Inicializar la base de datos SQLite, tablas y datos por defecto
    init_db()

    # Callback de limpieza de sesión por si Flet lo invoca
    def _al_cerrar_sesion(e=None):
        try:
            limpiar_sesion(page.session.id)
        except Exception:
            pass

    try:
        page.on_close = _al_cerrar_sesion
        page.on_disconnect = _al_cerrar_sesion
    except (RuntimeError, AttributeError):
        pass

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
