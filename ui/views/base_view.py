import flet as ft
from core.database import get_setting, set_setting

class BaseView(ft.View):
    """Clase base con persistencia automática de temas en SQLite."""
    
    # Estado estático global sincronizado con SQLite
    current_seed_color = "#2196F3"
    current_theme_mode = ft.ThemeMode.DARK
    _settings_loaded = False
    
    def __init__(self, route: str, title: str):
        super().__init__(
            route=route,
            padding=ft.Padding.all(20),
            spacing=15,
        )
        self.view_title = title
        self.ensure_settings_loaded()
        self.bgcolor = self.get_bg_color()
        self.setup_layout()

    @classmethod
    def ensure_settings_loaded(cls):
        """Carga las preferencias desde SQLite la primera vez que se instancie una vista."""
        if not cls._settings_loaded:
            saved_mode = get_setting("theme_mode", "dark")
            saved_color = get_setting("seed_color", "#2196F3")
            cls.current_theme_mode = ft.ThemeMode.LIGHT if saved_mode == "light" else ft.ThemeMode.DARK
            cls.current_seed_color = saved_color if saved_color else "#2196F3"
            cls._settings_loaded = True

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
        """Fondo neutro de la aplicación con mayor contraste para destacar elementos."""
        return "#0F172A" if self.is_dark else "#CBD5E1"

    def get_sidebar_bg(self) -> str:
        """Fondo de la barra lateral (gris sofisticado en modo claro)."""
        return "#1E293B" if self.is_dark else "#E2E8F0"

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

    def get_card_shadow(self) -> list[ft.BoxShadow]:
        """Retorna una lista de sombras premium para contenedores."""
        if self.is_dark:
            return [
                ft.BoxShadow(
                    spread_radius=0,
                    blur_radius=12,
                    color=ft.Colors.with_opacity(0.35, "#020617"),
                    offset=ft.Offset(0, 4),
                )
            ]
        else:
            return [
                ft.BoxShadow(
                    spread_radius=0,
                    blur_radius=12,
                    color=ft.Colors.with_opacity(0.08, "#475569"),
                    offset=ft.Offset(0, 4),
                )
            ]

    def create_card(self, content: ft.Control, padding: int | ft.Padding = 15, border_radius: int = 16, **kwargs) -> ft.Container:
        """Crea un contenedor de tarjeta estilizado con bordes redondeados y sombras premium."""
        return ft.Container(
            content=content,
            padding=padding,
            border_radius=border_radius,
            bgcolor=self.get_card_bg(),
            border=ft.Border.all(1, self.get_border_color()),
            shadow=self.get_card_shadow(),
            **kwargs
        )

    def setup_layout(self):
        """Estructura por defecto para las vistas que heredan."""
        try:
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
        except Exception as e:
            # Renderizado seguro en caso de error
            self.bgcolor = self.get_bg_color()
            self.controls = [
                ft.Container(
                    content=ft.Column([
                        ft.Text("Error al Cargar Módulo", size=24, color=ft.Colors.RED_500, weight=ft.FontWeight.BOLD),
                        ft.Text(f"Detalle: {str(e)}", color=self.get_text_color(), size=16),
                        ft.Divider(height=20, color=self.get_border_color()),
                        ft.Text("Por favor, verifique el archivo de configuración o contacte al administrador.", color=self.get_subtext_color())
                    ], spacing=10),
                    padding=30,
                    alignment=ft.Alignment.CENTER,
                    expand=True
                )
            ]

    def get_body(self) -> ft.Control:
        """Método plantilla a implementar por cada pantalla."""
        raise NotImplementedError("Las subclases deben implementar get_body()")

    def toggle_theme(self, e=None):
        """Alterna dinámicamente entre modo claro/oscuro y guarda la preferencia en SQLite."""
        if not self.page:
            return
            
        if self.page.theme_mode == ft.ThemeMode.DARK:
            self.page.theme_mode = ft.ThemeMode.LIGHT
            new_mode_str = "light"
        else:
            self.page.theme_mode = ft.ThemeMode.DARK
            new_mode_str = "dark"
            
        BaseView.current_theme_mode = self.page.theme_mode
        set_setting("theme_mode", new_mode_str)
        self.rebuild_ui()

    def change_seed_color(self, color_hex: str):
        """Actualiza el color de acento global y guarda la preferencia en SQLite."""
        if not self.page:
            return
            
        BaseView.current_seed_color = color_hex
        self.page.theme = ft.Theme(color_scheme_seed=color_hex)
        set_setting("seed_color", color_hex)
        self.rebuild_ui()

    def rebuild_ui(self):
        """Reconstruye los controles de la vista con las nuevas propiedades visuales."""
        self.bgcolor = self.get_bg_color()
        self.setup_layout()
        try:
            if self.page:
                self.page.update()
        except (RuntimeError, AttributeError):
            pass

    def get_current_page(self, e=None):
        """Obtiene la instancia de page activa de forma segura."""
        if e and hasattr(e, "page") and e.page:
            return e.page
        if e and hasattr(e, "control") and hasattr(e.control, "page") and e.control.page:
            return e.control.page
        try:
            if self.page:
                return self.page
        except (RuntimeError, AttributeError):
            pass
        return None

    def safe_update(self, e=None):
        """Actualiza la interfaz evitando excepciones de renderizado."""
        p = self.get_current_page(e)
        if p:
            p.update()
        else:
            try:
                self.update()
            except (RuntimeError, AttributeError):
                pass

    def mostrar_modal_tasa_bcv(self, e=None, callback_al_guardar=None):
        """Despliega un modal global para actualizar la Tasa BCV desde cualquier vista."""
        p = self.get_current_page(e)
        if not p:
            return

        from services.bcv_service import obtener_estado_tasa, actualizar_tasa
        estado = obtener_estado_tasa()
        tasa_actual = estado.get("tasa", 0.0)
        desc_antiguedad = estado.get("descripcion", "")

        txt_tasa = ft.TextField(
            label="Tasa BCV (Bs. / $)",
            value=f"{tasa_actual:.2f}" if tasa_actual > 0 else "",
            prefix_icon=ft.Icons.ATTACH_MONEY,
            keyboard_type=ft.KeyboardType.NUMBER,
            autofocus=True,
            border_radius=12
        )
        lbl_err = ft.Text("", color=ft.Colors.RED_500, size=12, weight=ft.FontWeight.BOLD)

        def guardar_tasa(e_save):
            lbl_err.value = ""
            try:
                val = float(txt_tasa.value.strip().replace(",", "."))
                if val <= 0:
                    raise ValueError()
                actualizar_tasa(val)
                dialog.open = False
                p.update()
                
                # Notificación de éxito
                s = ft.SnackBar(
                    content=ft.Text(f"Tasa BCV actualizada a {val:,.2f} Bs/$", color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD),
                    bgcolor=ft.Colors.GREEN_700,
                    duration=3000
                )
                p.overlay.append(s)
                s.open = True
                p.update()

                if callback_al_guardar:
                    callback_al_guardar(val)
                elif hasattr(self, "rebuild_ui"):
                    self.rebuild_ui()
            except Exception:
                lbl_err.value = "Ingrese un número mayor a 0 (ej: 732.48)."
                p.update()

        def cerrar(e_close):
            dialog.open = False
            p.update()

        dialog = ft.AlertDialog(
            title=ft.Row([
                ft.Icon(ft.Icons.CURRENCY_EXCHANGE, color=self.get_accent_color()),
                ft.Text("Actualizar Tasa de Cambio BCV", weight=ft.FontWeight.BOLD)
            ], spacing=10),
            content=ft.Container(
                content=ft.Column([
                    ft.Text(f"Antigüedad: {desc_antiguedad}", size=13, color=self.get_subtext_color(), weight=ft.FontWeight.W_600),
                    ft.Divider(height=10),
                    txt_tasa,
                    lbl_err
                ], spacing=10, tight=True),
                width=380,
                padding=10
            ),
            actions=[
                ft.TextButton("Cancelar", on_click=cerrar),
                ft.Button(
                    content=ft.Row([ft.Icon(ft.Icons.SAVE), ft.Text("Guardar Tasa")], tight=True),
                    bgcolor=self.get_accent_color(),
                    color=ft.Colors.WHITE,
                    on_click=guardar_tasa
                )
            ],
            actions_alignment=ft.MainAxisAlignment.SPACE_BETWEEN
        )

        if dialog not in p.overlay:
            p.overlay.append(dialog)
        dialog.open = True
        p.update()

    def show_alert_success(self, msg_or_e, e_or_msg=None):
        """Muestra una notificación flotante de éxito."""
        if isinstance(msg_or_e, str):
            msg, e = msg_or_e, e_or_msg
        else:
            e, msg = msg_or_e, e_or_msg or ""
        p = self.get_current_page(e)
        if p:
            s = ft.SnackBar(
                content=ft.Text(msg, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD),
                bgcolor=ft.Colors.GREEN_700,
                duration=3500
            )
            p.overlay.append(s)
            s.open = True
            p.update()

    def show_alert_error(self, msg_or_e, e_or_msg=None):
        """Muestra una notificación flotante de error."""
        if isinstance(msg_or_e, str):
            msg, e = msg_or_e, e_or_msg
        else:
            e, msg = msg_or_e, e_or_msg or ""
        p = self.get_current_page(e)
        if p:
            s = ft.SnackBar(
                content=ft.Text(msg, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD),
                bgcolor=ft.Colors.RED_700,
                duration=4000
            )
            p.overlay.append(s)
            s.open = True
            p.update()

    def show_alert_info(self, msg_or_e, e_or_msg=None):
        """Muestra una notificación flotante informativa."""
        if isinstance(msg_or_e, str):
            msg, e = msg_or_e, e_or_msg
        else:
            e, msg = msg_or_e, e_or_msg or ""
        p = self.get_current_page(e)
        if p:
            s = ft.SnackBar(
                content=ft.Text(msg, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD),
                bgcolor=ft.Colors.BLUE_700,
                duration=3500
            )
            p.overlay.append(s)
            s.open = True
            p.update()

