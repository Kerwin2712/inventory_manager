"""Quién puede usar la Carga Masiva y la Copia de Seguridad.

Por qué existe este archivo: "Gestión de Datos" aparece en el menú para todos
los roles, y ahí viven dos operaciones que reescriben o se llevan la base
entera. La Carga Masiva actualiza el stock de todo el catálogo, de modo que un
vendedor podía reescribir el inventario **desde el mismo módulo que existe
para que no pudiera** — el Generador de Pedido se agregó justamente porque un
empleado no debe modificar el stock. Y la Copia de Seguridad exporta ahora los
costos, que son información reservada a la administración.

El Generador de Pedido sigue visible para todos: eso es el requisito, no un
descuido.
"""
import flet as ft
import pytest

from ui.views.gestion_datos_view import GestionDatosView


class PaginaFalsa:
    def __init__(self):
        self.on_keyboard_event = None
        self.overlay = []
        self.dialogos = []

    def show_dialog(self, dialog):
        self.dialogos.append(dialog)

    def pop_dialog(self):
        return self.dialogos.pop() if self.dialogos else None

    def update(self):
        pass


class EventoFalso:
    def __init__(self, page):
        self.page = page


def _vista(rol: str | None, **kwargs) -> GestionDatosView:
    GestionDatosView.ensure_settings_loaded()
    user_data = {"username": "tester", "role": rol} if rol is not None else None
    vista = GestionDatosView(user_data=user_data, **kwargs)
    pagina = PaginaFalsa()
    vista.get_current_page = lambda e=None: pagina
    vista._pagina = pagina
    return vista


def _titulos(control) -> list[str]:
    encontrados = []
    if isinstance(control, ft.Text) and control.value:
        encontrados.append(str(control.value))
    for atributo in ("controls", "content", "actions", "title"):
        hijo = getattr(control, atributo, None)
        if isinstance(hijo, list):
            for h in hijo:
                encontrados += _titulos(h)
        elif hijo is not None and hasattr(hijo, "_c"):
            encontrados += _titulos(hijo)
    return encontrados


# ─── Qué tarjetas se dibujan ─────────────────────────────────────────────────

@pytest.mark.parametrize("rol", ["administrador", "superadmin", "gerencia"])
def test_un_administrador_ve_las_tres_tarjetas(db_temporal, rol):
    textos = _titulos(_vista(rol).get_body())
    assert any("Carga Masiva de Datos" in t for t in textos)
    assert any("Copias de Seguridad" in t for t in textos)
    assert any("Generador de Archivo por Nueva Mercancía" in t for t in textos)


@pytest.mark.parametrize("rol", ["vendedor", "cajero", ""])
def test_un_vendedor_solo_ve_el_generador_de_pedido(db_temporal, rol):
    textos = _titulos(_vista(rol).get_body())
    assert not any("Carga Masiva de Datos" in t for t in textos)
    assert not any("Copias de Seguridad" in t for t in textos)
    assert any("Generador de Archivo por Nueva Mercancía" in t for t in textos)


def test_sin_usuario_se_esconden_las_dos_operaciones(db_temporal):
    """Fail-closed: una vista construida sin usuario —por error, o aislada en
    una prueba— no puede habilitar la Carga Masiva."""
    vista = _vista(None)
    assert vista.es_admin is False
    textos = _titulos(vista.get_body())
    assert not any("Carga Masiva de Datos" in t for t in textos)


def test_un_rol_desconocido_no_es_administrador(db_temporal):
    assert _vista("jefe de taller").es_admin is False


# ─── Los handlers también se cierran ─────────────────────────────────────────

def test_la_carga_masiva_rechaza_a_un_vendedor_que_la_invoque(db_temporal, monkeypatch):
    """Ocultar la tarjeta no es autorizar: el handler sigue siendo invocable
    por código, y es ahí donde la acción ocurre."""
    vista = _vista("vendedor")
    vista.get_body()

    abrio = []
    monkeypatch.setattr(vista, "abrir_dialogo_abrir", lambda: abrio.append(True) or "")
    errores = []
    monkeypatch.setattr(vista, "show_alert_error", lambda e, msg=None: errores.append(msg or e))

    vista.handle_importar_click(EventoFalso(vista._pagina))

    assert abrio == [], "se abrió el selector de archivo para un vendedor"
    assert errores, "no se avisó al usuario por qué no pasó nada"


def test_el_respaldo_rechaza_a_un_vendedor_que_lo_invoque(db_temporal, monkeypatch):
    vista = _vista("vendedor")
    vista.get_body()

    guardo = []
    monkeypatch.setattr(
        vista, "abrir_dialogo_guardado", lambda d, s: guardo.append(True) or ""
    )
    errores = []
    monkeypatch.setattr(vista, "show_alert_error", lambda e, msg=None: errores.append(msg or e))

    vista.handle_exportar_excel(EventoFalso(vista._pagina))

    assert guardo == [], "se abrió el diálogo de guardado para un vendedor"
    assert errores


def test_el_mensaje_de_rechazo_no_culpa_al_usuario(db_temporal, monkeypatch):
    vista = _vista("vendedor")
    mensajes = []
    monkeypatch.setattr(vista, "show_alert_error", lambda e, msg=None: mensajes.append(str(msg or e)))

    vista._exigir_admin(None)

    assert mensajes
    assert "administrador" in mensajes[0].lower()


def test_un_administrador_pasa_la_comprobacion(db_temporal):
    assert _vista("administrador")._exigir_admin(None) is True


# ─── El generador de pedido sigue abierto a todos ────────────────────────────

def test_un_vendedor_puede_abrir_el_generador_de_pedido(db_temporal):
    """Es el punto de la Nueva Función 6: el empleado registra la mercancía
    recibida sin poder tocar el inventario."""
    vista = _vista("vendedor")
    vista.get_body()

    vista.mostrar_generador_pedido(EventoFalso(vista._pagina))

    assert vista._pagina.dialogos, "el generador de pedido no se abrió"


# ─── El Dashboard pasa el usuario ────────────────────────────────────────────

def test_el_dashboard_le_pasa_el_usuario_a_la_vista(db_temporal, monkeypatch):
    """Sin esto la vista aplica su criterio fail-closed y le esconde la Carga
    Masiva incluso a un administrador."""
    from ui.views import dashboard_view as modulo

    capturadas = []

    class Espia(GestionDatosView):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            capturadas.append(self)

    monkeypatch.setattr(modulo, "GestionDatosView", Espia)
    modulo.DashboardView.ensure_settings_loaded()
    dashboard = modulo.DashboardView(user_info={"username": "admin", "role": "superadmin"})
    dashboard.current_section = "Gestión de Datos"
    dashboard.get_body()

    assert capturadas, "el Dashboard no construyó la vista"
    assert capturadas[-1].es_admin is True


def test_el_dashboard_no_promueve_a_un_vendedor(db_temporal, monkeypatch):
    from ui.views import dashboard_view as modulo

    capturadas = []

    class Espia(GestionDatosView):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            capturadas.append(self)

    monkeypatch.setattr(modulo, "GestionDatosView", Espia)
    modulo.DashboardView.ensure_settings_loaded()
    dashboard = modulo.DashboardView(user_info={"username": "pepe", "role": "vendedor"})
    dashboard.current_section = "Gestión de Datos"
    dashboard.get_body()

    assert capturadas[-1].es_admin is False
