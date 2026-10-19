"""Los diálogos heredados de Gestión de Datos, sobre la pila nativa de Flet.

El flujo de importación encadena modales (mapeo de columnas → proveedores
faltantes → error), y los tres seguían montándose con el patrón heredado de
`page.overlay` + alternar `open`, que en Flet 0.86 **no dibuja el cierre**: el
modal queda pegado en pantalla, o activo pero invisible recibiendo clics sobre
botones que el usuario ya no ve. En un encadenamiento de modales es
especialmente dañino, porque el diálogo que no se cerró se come los clics del
siguiente.

El doble de página emula la pila real (`show_dialog` / `pop_dialog`, cerrando
el más alto que siga abierto) en vez de verificar las banderas `open`, que
eran correctas también cuando el defecto estaba vivo.
"""
import types

import flet as ft
import pytest

from ui.views.gestion_datos_view import GestionDatosView


class PageFalsa:
    """Emula la pila de diálogos de `flet.BasePage` y su sesión."""

    def __init__(self):
        self.dialogos = []
        self.overlay = []
        self.updates = 0
        self.session = types.SimpleNamespace(id="sesion-test")

    def show_dialog(self, dialog):
        if dialog in self.dialogos:
            raise RuntimeError("Dialog is already opened")
        dialog.open = True
        self.dialogos.append(dialog)

    def pop_dialog(self):
        dlg = next((d for d in reversed(self.dialogos) if d.open), None)
        if dlg is not None:
            dlg.open = False
        return dlg

    def update(self):
        self.updates += 1

    @property
    def visible(self):
        """El diálogo que Flutter pintaría: el último abierto de la pila."""
        return next((d for d in reversed(self.dialogos) if d.open), None)


class EventoFalso:
    def __init__(self, page):
        self.page = page


@pytest.fixture
def vista(db_temporal):
    GestionDatosView.ensure_settings_loaded()
    pagina = PageFalsa()
    v = GestionDatosView(page=pagina, user_data={"username": "tester", "role": "administrador"})
    v.get_current_page = lambda e=None: pagina
    v._pagina = pagina
    return v


def _textos(control) -> list[str]:
    encontrados = []
    if isinstance(control, ft.Text) and control.value:
        encontrados.append(str(control.value))
    for atributo in ("controls", "content", "actions", "title"):
        hijo = getattr(control, atributo, None)
        if isinstance(hijo, list):
            for h in hijo:
                encontrados += _textos(h)
        elif hijo is not None and hasattr(hijo, "_c"):
            encontrados += _textos(hijo)
    return encontrados


def _etiqueta(accion) -> str:
    """Texto visible de un botón.

    Hay dos formas en el proyecto: `ft.TextButton("Cancelar")`, donde en Flet
    0.86 la cadena queda directamente en `content`, y
    `ft.Button(content=Row([Icon, Text(...)]))`, donde el texto vive dentro del
    árbol de controles. Se miran las dos.
    """
    contenido = getattr(accion, "content", None)
    partes = [contenido if isinstance(contenido, str) else ""] + _textos(accion)
    return " ".join(partes).lower()


def _boton(dlg, etiqueta: str):
    """Primer botón de las acciones del diálogo cuyo texto contenga `etiqueta`."""
    for accion in dlg.actions or []:
        if etiqueta.lower() in _etiqueta(accion):
            return accion
    raise AssertionError(
        f"no hay un botón '{etiqueta}' en {[_etiqueta(a) for a in dlg.actions or []]}"
    )


# ─── Diálogo de error ────────────────────────────────────────────────────────

def test_el_dialogo_de_error_se_monta_en_la_pila(vista):
    vista.mostrar_dialogo_error(EventoFalso(vista._pagina), "El archivo no tiene hoja de productos.")

    assert len(vista._pagina.dialogos) == 1
    assert vista._pagina.overlay == []
    assert "El archivo no tiene hoja de productos." in " ".join(_textos(vista._pagina.visible))


def test_cerrar_el_dialogo_de_error_lo_quita_de_la_pantalla(vista):
    """Con el patrón heredado este cierre no se dibujaba y el modal quedaba
    pegado: el usuario no podía volver a la vista."""
    evento = EventoFalso(vista._pagina)
    vista.mostrar_dialogo_error(evento, "Error de prueba")
    dlg = vista._pagina.visible

    _boton(dlg, "entendido").on_click(evento)

    assert dlg.open is False
    assert vista._pagina.visible is None


def test_el_dialogo_de_error_entra_en_la_pila_de_la_vista(vista):
    vista.mostrar_dialogo_error(EventoFalso(vista._pagina), "Error de prueba")
    assert vista._dialog is vista._pagina.visible


# ─── Asistente de proveedores faltantes ─────────────────────────────────────

def test_el_asistente_de_proveedores_se_monta_en_la_pila(vista, tmp_path):
    ruta = tmp_path / "pedido.xlsx"
    ruta.write_bytes(b"")

    vista.mostrar_asistente_proveedores_faltantes(
        EventoFalso(vista._pagina), str(ruta), ["Distribuidora Andina"]
    )

    assert len(vista._pagina.dialogos) == 1
    assert vista._pagina.overlay == []
    assert any("Andina" in t for t in _textos(vista._pagina.visible))


def test_cancelar_el_asistente_de_proveedores_cierra_el_modal(vista, tmp_path):
    ruta = tmp_path / "pedido.xlsx"
    ruta.write_bytes(b"")
    evento = EventoFalso(vista._pagina)

    vista.mostrar_asistente_proveedores_faltantes(evento, str(ruta), ["Distribuidora Andina"])
    dlg = vista._pagina.visible
    _boton(dlg, "cancelar importaci").on_click(evento)

    assert dlg.open is False
    assert vista._pagina.visible is None


def test_registrar_el_proveedor_cierra_el_modal_y_avanza(vista, tmp_path):
    """El encadenamiento es lo que importa: si este modal no se cierra de
    verdad, se queda encima y se come los clics del siguiente paso."""
    ruta = tmp_path / "pedido.xlsx"
    ruta.write_bytes(b"")
    evento = EventoFalso(vista._pagina)
    completados = []

    vista.ejecutar_importacion_final = lambda *a, **k: None
    vista.mostrar_asistente_proveedores_faltantes(
        evento, str(ruta), ["Distribuidora Andina"],
        on_completado=lambda ev: completados.append(True),
    )
    dlg = vista._pagina.visible

    for campo in (c for c in _controles_de(dlg) if isinstance(c, ft.TextField)):
        etiqueta = (campo.label or "").lower()
        if "rif" in etiqueta or "cédula" in etiqueta or "cedula" in etiqueta:
            campo.value = "J-123456789"
        elif "teléfono" in etiqueta or "telefono" in etiqueta:
            campo.value = "0212-1234567"

    _boton(dlg, "guardar y continuar").on_click(evento)

    assert dlg.open is False, "el modal del proveedor quedó abierto sobre el siguiente paso"
    assert vista._pagina.visible is None


def _controles_de(control):
    yield control
    for atributo in ("controls", "content", "actions", "title"):
        hijo = getattr(control, atributo, None)
        if isinstance(hijo, list):
            for h in hijo:
                yield from _controles_de(h)
        elif hijo is not None and hasattr(hijo, "_c"):
            yield from _controles_de(hijo)


# ─── Que no quede ningún rastro del patrón heredado ─────────────────────────

def test_ningun_dialogo_de_la_vista_usa_el_overlay(vista, tmp_path):
    """Guarda de regresión sobre el archivo: los tres modales heredados ya
    pasan por la pila, y es fácil reintroducir el patrón viejo al copiar un
    bloque existente."""
    import inspect

    import ui.views.gestion_datos_view as modulo

    fuente = inspect.getsource(modulo)
    # El respaldo de `_open_dialog`/`_close_dialog` para páginas sin la API de
    # pila es legítimo; lo que no debe repetirse es el montaje manual del
    # diálogo en el overlay fuera de esos dos helpers.
    assert "p.overlay.append(dlg)" not in fuente
    assert "dlg.open = True" not in fuente
