"""Marcador, sombreado y regla de los botones en la Auditoría Preventiva.

El usuario del proyecto pidió el marcador "igual que Inventario", así que lo
que se blinda aquí es lo mismo que en `test_inventario_marcador_seleccion.py`,
sobre la otra lista:

  - Un clic en cualquier parte de la fila marca el ítem: se sombrea y la
    casilla izquierda queda marcada, en los TRES formatos de vista.
  - Solo hay DOS formas de deseleccionar: el clic dentro de la casilla marcada
    y la tecla [Esc].
  - Con un ítem marcado, los íconos de las demás filas quedan DESHABILITADOS
    (visiblemente, no ignorados en silencio).
  - Sin marcar nada, TODOS los íconos de todas las filas siguen activos: es la
    regla "Importante" del PDF y la más fácil de romper al cablear la lista.

El teclado lo atiende `ControlTeclado`, cuyo `manejar` es una corutina: por eso
las pulsaciones se ejercitan con `asyncio.run`.
"""
import asyncio

import flet as ft
import pytest

from services.inventario_service import actualizar_producto, crear_producto

CODIGOS = ("AUD-001", "AUD-002", "AUD-003")

ATRIBUTOS_HIJOS = (
    "controls", "content", "actions", "title", "rows", "columns", "cells", "label",
)


def _controles(control):
    if control is None or not hasattr(control, "_c"):
        return
    yield control
    for atributo in ATRIBUTOS_HIJOS:
        hijo = getattr(control, atributo, None)
        if isinstance(hijo, list):
            for h in hijo:
                yield from _controles(h)
        else:
            yield from _controles(hijo)


def _textos(control) -> list[str]:
    return [str(c.value) for c in _controles(control) if isinstance(c, ft.Text) and c.value]


class PaginaFalsa:
    def __init__(self):
        self.dialogos = []
        self.overlay = []
        self.updates = 0
        self.on_keyboard_event = None

    def show_dialog(self, dialog):
        dialog.open = True
        self.dialogos.append(dialog)

    def pop_dialog(self):
        dlg = next((d for d in reversed(self.dialogos) if d.open), None)
        if dlg is not None:
            dlg.open = False
        return dlg

    def update(self):
        self.updates += 1


class EventoFalso:
    def __init__(self, page):
        self.page = page


class TeclaFalsa:
    def __init__(self, page, key):
        self.page = page
        self.key = key


@pytest.fixture
def pagina():
    return PaginaFalsa()


@pytest.fixture
def evento(pagina):
    return EventoFalso(pagina)


@pytest.fixture
def productos(db_temporal):
    for i, codigo in enumerate(CODIGOS, start=1):
        crear_producto(
            codigo=codigo, referencia=f"REF-{i}",
            descripcion_general=f"Producto critico {i}",
            departamento="Ferretería", marca="ACME",
            precio_dolares=10.0 * i, existencia=0.0,
            nombre_referencia_corto=f"Corto {codigo}",
            costo_usd_efectivo=None, rol_usuario="administrador",
        )
    return list(CODIGOS)


@pytest.fixture
def vista(productos, pagina):
    from ui.views.dashboard_view import DashboardView

    DashboardView.ensure_settings_loaded()
    v = DashboardView(user_info={"username": "tester", "role": "administrador"})
    v.get_current_page = lambda e=None: pagina
    v.current_section = "Inicio"
    v.get_body()
    return v


# Los dos formatos con tabla comparten la mecánica de `DataRow`; las tarjetas
# tienen su propia estructura y se prueban aparte.
MODOS_CON_TABLA = ["separado", "agrupado"]


@pytest.fixture(params=MODOS_CON_TABLA)
def vista_modo(request, vista):
    vista._modo_vista_auditoria = request.param
    vista._cargar_filas_auditoria()
    return vista


# ── Helpers de lectura de la lista ──────────────────────────────────────────
def _fila(vista, codigo) -> ft.DataRow:
    return next(r for r in vista._dt_auditoria.rows if r.data == codigo)


def _casilla(fila: ft.DataRow) -> ft.DataCell:
    return fila.cells[0]


def _icono_casilla(fila: ft.DataRow) -> ft.Icon:
    return _casilla(fila).content.content


def _icono_de(control) -> ft.IconButton:
    if isinstance(control, ft.Stack):
        return next(c for c in control.controls if isinstance(c, ft.IconButton))
    return control


def _botones(fila: ft.DataRow) -> list[ft.IconButton]:
    contenido = fila.cells[-1].content
    if isinstance(contenido, ft.Container):  # el modo agrupado envuelve la celda
        contenido = contenido.content
    return [
        _icono_de(c) for c in contenido.controls
        if isinstance(c, (ft.IconButton, ft.Stack))
    ]


def _clic_en_fila(vista, codigo, evento):
    _fila(vista, codigo).on_select_change(evento)


def _clic_en_casilla(vista, codigo, evento):
    _casilla(_fila(vista, codigo)).on_tap(evento)


def _pulsar(vista, pagina, tecla):
    return asyncio.run(vista._teclado.manejar(TeclaFalsa(pagina, tecla)))


def _tarjeta(vista, codigo) -> ft.Container:
    return next(
        t for t in vista._vista_auditoria.content.controls[0].controls
        if any(codigo in txt for txt in _textos(t))
    )


# ─────────────────────────────────────────────────────────────────────────────
# La casilla existe en los tres formatos
# ─────────────────────────────────────────────────────────────────────────────
def test_la_casilla_marcadora_abre_la_lista(vista_modo):
    for codigo in CODIGOS:
        fila = _fila(vista_modo, codigo)
        assert _casilla(fila).on_tap is not None, "la casilla atiende su propio clic"
        assert isinstance(_icono_casilla(fila), ft.Icon)


def test_la_fila_completa_es_sensible_al_clic(vista_modo):
    """"No importa si es fuera de la casilla": toda la fila marca."""
    for codigo in CODIGOS:
        assert _fila(vista_modo, codigo).on_select_change is not None


def test_la_tabla_no_dibuja_su_propia_columna_de_casillas(vista):
    """Con `on_select_change` en todas las filas, activar la columna de
    casillas de la tabla pondría una segunda casilla junto al marcador."""
    assert vista._dt_auditoria.show_checkbox_column is False


def test_la_columna_marcador_no_se_puede_ocultar(vista):
    assert "marcador" not in vista._columnas_ocultables_auditoria
    assert vista._columnas_orden_visible_auditoria()[0] == "marcador"


def test_en_tarjetas_tambien_se_puede_marcar(vista, evento):
    """Cambiar de formato no puede ser perder la selección: el usuario leería
    el selector como tres pantallas distintas y no como tres formatos."""
    vista._modo_vista_auditoria = "tarjetas"
    vista._cargar_filas_auditoria()

    _tarjeta(vista, "AUD-002").on_click(evento)

    assert vista._seleccion_auditoria.seleccionado == "AUD-002"


def test_la_tarjeta_marcada_se_sombrea_y_se_le_marca_el_borde(vista, evento):
    vista._modo_vista_auditoria = "tarjetas"
    vista._cargar_filas_auditoria()
    sin_marcar = _tarjeta(vista, "AUD-002").bgcolor

    _tarjeta(vista, "AUD-002").on_click(evento)

    marcada = _tarjeta(vista, "AUD-002")
    assert marcada.bgcolor != sin_marcar
    assert marcada.border.top.width == 2


# ─────────────────────────────────────────────────────────────────────────────
# Marcar y sombrear
# ─────────────────────────────────────────────────────────────────────────────
def test_un_clic_marca_y_sombrea_el_item(vista_modo, evento):
    _clic_en_fila(vista_modo, "AUD-002", evento)

    fila = _fila(vista_modo, "AUD-002")
    assert vista_modo._seleccion_auditoria.seleccionado == "AUD-002"
    assert fila.selected is True
    assert fila.color is not None, "el ítem marcado debe quedar sombreado"


def test_las_demas_filas_no_quedan_sombreadas(vista_modo, evento):
    _clic_en_fila(vista_modo, "AUD-002", evento)

    for codigo in ("AUD-001", "AUD-003"):
        fila = _fila(vista_modo, codigo)
        assert fila.selected is False
        assert fila.color is None


def test_el_marcado_se_mantiene_al_repintar_la_lista(vista_modo, evento):
    """Es estado del modelo, así que sobrevive a los repintados y por lo tanto
    a desplazarse hacia la derecha de la lista."""
    _clic_en_fila(vista_modo, "AUD-001", evento)

    vista_modo._cargar_filas_auditoria()

    assert _fila(vista_modo, "AUD-001").selected is True


def test_marcar_otro_item_mueve_el_marcador(vista_modo, evento):
    _clic_en_fila(vista_modo, "AUD-001", evento)
    _clic_en_fila(vista_modo, "AUD-003", evento)

    assert _fila(vista_modo, "AUD-001").selected is False
    assert _fila(vista_modo, "AUD-003").selected is True


def test_el_icono_de_la_casilla_cambia_al_marcar(vista_modo, evento):
    antes = _icono_casilla(_fila(vista_modo, "AUD-001")).icon

    _clic_en_fila(vista_modo, "AUD-001", evento)

    assert _icono_casilla(_fila(vista_modo, "AUD-001")).icon != antes


# ─────────────────────────────────────────────────────────────────────────────
# Las dos únicas formas de deseleccionar
# ─────────────────────────────────────────────────────────────────────────────
def test_el_clic_dentro_de_la_casilla_marcada_deselecciona(vista_modo, evento):
    _clic_en_fila(vista_modo, "AUD-002", evento)

    _clic_en_casilla(vista_modo, "AUD-002", evento)

    assert vista_modo._seleccion_auditoria.hay_seleccion is False
    assert _fila(vista_modo, "AUD-002").selected is False


def test_la_tecla_escape_deselecciona(vista_modo, pagina, evento):
    _clic_en_fila(vista_modo, "AUD-002", evento)

    _pulsar(vista_modo, pagina, "Escape")

    assert vista_modo._seleccion_auditoria.hay_seleccion is False


def test_otra_tecla_no_deselecciona(vista_modo, pagina, evento):
    _clic_en_fila(vista_modo, "AUD-002", evento)

    _pulsar(vista_modo, pagina, "Enter")

    assert vista_modo._seleccion_auditoria.seleccionado == "AUD-002"


def test_un_clic_en_la_fila_nunca_deselecciona(vista_modo, evento):
    _clic_en_fila(vista_modo, "AUD-002", evento)
    _clic_en_fila(vista_modo, "AUD-002", evento)

    assert vista_modo._seleccion_auditoria.seleccionado == "AUD-002"


def test_en_tarjetas_la_casilla_tambien_deselecciona(vista, evento):
    vista._modo_vista_auditoria = "tarjetas"
    vista._cargar_filas_auditoria()
    _tarjeta(vista, "AUD-002").on_click(evento)

    casilla = next(
        c for c in _controles(_tarjeta(vista, "AUD-002"))
        if isinstance(c, ft.Container) and c.width == 34
    )
    casilla.on_click(evento)

    assert vista._seleccion_auditoria.hay_seleccion is False


def test_al_marcar_se_engancha_el_teclado_sin_pisar_el_handler_previo(vista, pagina, evento):
    """El Dashboard comparte la página con las vistas que aloja: el handler que
    hubiera puesto debe seguir recibiendo las teclas."""
    recibidas = []
    pagina.on_keyboard_event = lambda ev: recibidas.append(getattr(ev, "key", None))

    _clic_en_fila(vista, "AUD-001", evento)

    assert pagina.on_keyboard_event is vista._teclado.handler
    asyncio.run(pagina.on_keyboard_event(TeclaFalsa(pagina, "Escape")))
    assert recibidas == ["Escape"], "el handler previo debe seguir invocándose"
    assert vista._seleccion_auditoria.hay_seleccion is False


# ─────────────────────────────────────────────────────────────────────────────
# La regla "Importante", en los dos sentidos
# ─────────────────────────────────────────────────────────────────────────────
def test_sin_marcar_nada_todos_los_iconos_estan_activos(vista_modo):
    """La mitad de la regla que es más fácil de romper: mientras no haya nada
    marcado, el sistema trabaja igual que la versión anterior."""
    for codigo in CODIGOS:
        botones = _botones(_fila(vista_modo, codigo))
        assert len(botones) == 4, "info, historial, editar y contactar proveedor"
        assert all(b.disabled is False for b in botones)


def test_con_un_item_marcado_solo_el_marcado_conserva_sus_iconos(vista_modo, evento):
    _clic_en_fila(vista_modo, "AUD-002", evento)

    assert all(b.disabled is False for b in _botones(_fila(vista_modo, "AUD-002")))
    for codigo in ("AUD-001", "AUD-003"):
        botones = _botones(_fila(vista_modo, codigo))
        assert all(b.disabled is True for b in botones), (
            f"los íconos de {codigo} deben quedar deshabilitados, no inertes en silencio"
        )


def test_el_icono_deshabilitado_explica_por_que(vista_modo, evento):
    """Un botón apagado sin explicación se lee como un cuelgue."""
    _clic_en_fila(vista_modo, "AUD-002", evento)

    for boton in _botones(_fila(vista_modo, "AUD-001")):
        assert "hay otro ítem marcado" in boton.tooltip


def test_al_deseleccionar_vuelven_a_habilitarse_todos(vista_modo, evento):
    _clic_en_fila(vista_modo, "AUD-002", evento)
    _clic_en_casilla(vista_modo, "AUD-002", evento)

    for codigo in CODIGOS:
        assert all(b.disabled is False for b in _botones(_fila(vista_modo, codigo)))


def test_una_accion_sobre_un_item_no_marcado_se_rechaza(vista, evento, pagina):
    """Defensa en profundidad: la regla vale también para quien invoque la
    acción por código o por teclado, no solo para quien hace clic."""
    vista._seleccion_auditoria.seleccionar("AUD-002")

    assert vista.ejecutar_accion_auditoria("editar", "AUD-001", evento) is False
    assert vista._vista_inventario_auxiliar is None, (
        "no debe abrirse el formulario del ítem ajeno"
    )


def test_la_accion_sobre_el_item_marcado_se_ejecuta(vista, evento):
    vista._seleccion_auditoria.seleccionar("AUD-002")

    assert vista.ejecutar_accion_auditoria("editar", "AUD-002", evento) is True
    assert vista._vista_inventario_auxiliar._editing_codigo == "AUD-002"


def test_sin_seleccion_cualquier_accion_se_ejecuta(vista, evento):
    assert vista.ejecutar_accion_auditoria("editar", "AUD-003", evento) is True
    assert vista._vista_inventario_auxiliar._editing_codigo == "AUD-003"


# ─────────────────────────────────────────────────────────────────────────────
# La selección no sobrevive a un cambio de sección
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("seccion", ["Ventas", "Inventario", "Cartera", "Gestión de Datos"])
def test_al_salir_del_inicio_la_seleccion_se_olvida(vista, evento, seccion):
    """Si sobreviviera, una tecla de función abriría un modal sobre una lista
    que el usuario no tiene delante."""
    _clic_en_fila(vista, "AUD-001", evento)
    assert vista._seleccion_auditoria.hay_seleccion is True

    vista.current_section = seccion
    vista.get_body()

    assert vista._seleccion_auditoria.hay_seleccion is False
    assert vista._alertas_en_pantalla == {}
    assert vista._scroll_inicio_v is None
    assert vista._scroll_inicio_h is None


def test_repintar_el_inicio_conserva_el_marcado(vista, evento):
    """Lo contrario del test anterior: dentro del Inicio, el marcado es
    justamente lo que hay que conservar (un repintado ocurre al guardar el
    stock mínimo o al cambiar de formato)."""
    _clic_en_fila(vista, "AUD-001", evento)

    vista.get_body()

    assert vista._seleccion_auditoria.seleccionado == "AUD-001"


def test_un_item_que_sale_de_la_lista_deja_de_estar_marcado(vista, evento):
    """Una selección fantasma bloquearía los íconos de todas las filas vivas
    por un ítem que no se ve en ninguna parte."""
    _clic_en_fila(vista, "AUD-001", evento)

    actualizar_producto(
        codigo="AUD-001", referencia="REF-1",
        descripcion_general="Producto critico 1",
        departamento="Ferretería", existencia=500.0, precio_dolares=10.0,
        costo_usd_efectivo=1.0, rol_usuario="administrador",
    )
    vista._cargar_filas_auditoria()

    assert vista._seleccion_auditoria.hay_seleccion is False
    for codigo in ("AUD-002", "AUD-003"):
        assert all(b.disabled is False for b in _botones(_fila(vista, codigo)))
