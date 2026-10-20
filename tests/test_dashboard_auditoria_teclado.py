"""Teclas de función sobre la lista de Auditoría Preventiva.

El mapeo de `teclado_nav.ATAJOS_ITEM` es FIJO y común a las cuatro listas de la
aplicación (F1 info, F2 cobrar, F3 carrito, F4 historial, F5 editar, F6
borrar). La Auditoría solo tiene las acciones de reposición, así que aquí
quedan vivas **F1, F4 y F5**, y **F2, F3 y F6 quedan inertes**: una tecla sin
ícono equivalente no hace nada, que es muy distinto de hacer otra cosa. Si F3
añadiera al carrito desde la lista de reposición, la misma tecla significaría
cosas distintas en dos pantallas del mismo programa.

"Contactar proveedor" no tiene tecla a propósito: no existe en el mapeo
canónico y no se le inventó una.

`ControlTeclado.manejar` es una corutina (dentro espera a `scroll_to`), así que
las pulsaciones se ejercitan con `asyncio.run`, igual que en
`test_control_teclado.py`.
"""
import asyncio

import flet as ft
import pytest

from services.inventario_service import crear_producto
from ui.components.teclado_nav import PASO_HORIZONTAL, PASO_VERTICAL

CODIGOS = ("AUD-001", "AUD-002")


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


class TeclaFalsa:
    def __init__(self, page, key, **modificadores):
        self.page = page
        self.key = key
        for nombre, valor in modificadores.items():
            setattr(self, nombre, valor)


class EspiaScroll:
    """Reemplaza un destino real para contar los `scroll_to` recibidos."""

    def __init__(self):
        self.llamadas = []

    async def scroll_to(self, **kwargs):
        self.llamadas.append(kwargs)


@pytest.fixture
def pagina():
    return PaginaFalsa()


@pytest.fixture
def productos(db_temporal):
    for i, codigo in enumerate(CODIGOS, start=1):
        crear_producto(
            codigo=codigo, referencia=f"REF-{i}",
            descripcion_general=f"Producto critico {i}",
            departamento="Ferretería", precio_dolares=10.0 * i, existencia=0.0,
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


def _pulsar(vista, pagina, tecla, **modificadores):
    return asyncio.run(vista._teclado.manejar(TeclaFalsa(pagina, tecla, **modificadores)))


def _marcar(vista, codigo, pagina):
    fila = next(r for r in vista._dt_auditoria.rows if r.data == codigo)
    fila.on_select_change(TeclaFalsa(pagina, ""))


# ─────────────────────────────────────────────────────────────────────────────
# Las tres teclas con ícono equivalente
# ─────────────────────────────────────────────────────────────────────────────
def test_f1_abre_el_detalle_del_item_marcado(vista, pagina):
    _marcar(vista, "AUD-002", pagina)

    _pulsar(vista, pagina, "F1")

    assert pagina.dialogos, "F1 no abrió ningún modal"


def test_f4_abre_el_historial_del_item_marcado(vista, pagina):
    _marcar(vista, "AUD-002", pagina)

    _pulsar(vista, pagina, "F4")

    textos = [
        str(c.value) for c in _recorrer(pagina.dialogos[-1])
        if isinstance(c, ft.Text) and c.value
    ]
    assert any("Historial Clínico" in t for t in textos)


def test_f5_abre_el_formulario_del_item_marcado(vista, pagina):
    _marcar(vista, "AUD-001", pagina)

    _pulsar(vista, pagina, "F5")

    assert vista._vista_inventario_auxiliar._editing_codigo == "AUD-001"


def test_las_teclas_recorren_el_mismo_camino_que_los_iconos(vista, pagina):
    """Dos caminos distintos para la misma acción son dos comportamientos que
    se separan con el tiempo."""
    ejecutadas = []
    vista.ejecutar_accion_auditoria = lambda a, c, e=None: ejecutadas.append((a, c)) or True
    _marcar(vista, "AUD-002", pagina)

    for tecla in ("F1", "F4", "F5"):
        _pulsar(vista, pagina, tecla)

    assert ejecutadas == [
        ("info", "AUD-002"), ("historial", "AUD-002"), ("editar", "AUD-002"),
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Las tres teclas sin ícono equivalente quedan inertes
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("tecla", ["F2", "F3", "F6"])
def test_las_teclas_sin_icono_equivalente_no_hacen_nada(vista, pagina, tecla):
    """F2 cobrar, F3 carrito y F6 borrar no existen en esta lista: no se les
    reasignó otra acción ni se les inventó un significado propio."""
    _marcar(vista, "AUD-002", pagina)

    _pulsar(vista, pagina, tecla)

    assert pagina.dialogos == []
    assert vista._vista_inventario_auxiliar is None


@pytest.mark.parametrize("accion", ["cobrar", "carrito", "borrar"])
def test_el_ejecutor_de_teclado_rechaza_las_acciones_que_no_son_de_esta_lista(vista, accion):
    """Entra por el nombre de la acción, no por la tecla: se rechaza antes de
    llegar al punto de entrada, que para esas acciones lanzaría."""
    vista._seleccion_auditoria.seleccionar("AUD-001")

    assert vista._accionar_por_teclado(accion) is False


# ─────────────────────────────────────────────────────────────────────────────
# Guardas: sin ítem marcado y fuera del Inicio
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("tecla", ["F1", "F4", "F5"])
def test_sin_item_marcado_ninguna_tecla_acciona(vista, pagina, tecla):
    _pulsar(vista, pagina, tecla)

    assert pagina.dialogos == []


def test_sin_item_marcado_el_punto_de_entrada_devuelve_falso(vista):
    assert vista.ejecutar_accion_auditoria_sobre_seleccionado("info") is False


def test_fuera_del_inicio_las_teclas_no_accionan_la_auditoria(vista, pagina):
    """El Dashboard aloja a las demás vistas: una tecla pulsada mientras el
    usuario mira Ventas no puede accionar una lista que ya no está montada."""
    vista._seleccion_auditoria.seleccionar("AUD-001")
    vista.current_section = "Ventas"

    assert vista._accionar_por_teclado("info") is False


# ─────────────────────────────────────────────────────────────────────────────
# Convivencia con la navegación
# ─────────────────────────────────────────────────────────────────────────────
def test_las_flechas_siguen_desplazando_con_un_item_marcado(vista, pagina):
    espia_v, espia_h = EspiaScroll(), EspiaScroll()
    vista._scroll_inicio_v = espia_v
    vista._scroll_inicio_h = espia_h
    _marcar(vista, "AUD-001", pagina)

    _pulsar(vista, pagina, "Arrow Down")
    _pulsar(vista, pagina, "Arrow Right")

    assert espia_v.llamadas == [{"delta": PASO_VERTICAL, "duration": 200}]
    assert espia_h.llamadas == [{"delta": PASO_HORIZONTAL, "duration": 200}]


def test_control_flecha_va_al_extremo(vista, pagina):
    espia = EspiaScroll()
    vista._scroll_inicio_v = espia

    _pulsar(vista, pagina, "Arrow Up", ctrl=True)
    _pulsar(vista, pagina, "Arrow Down", ctrl=True)

    assert espia.llamadas[0] == {"offset": 0.0, "duration": 200}
    assert espia.llamadas[1]["delta"] > 10000


def test_con_un_campo_enfocado_las_flechas_no_desplazan(vista, pagina):
    """Mientras el cursor está en el campo de stock mínimo, las flechas mueven
    el cursor: nadie espera que al corregir un número se le mueva la pantalla."""
    espia = EspiaScroll()
    vista._scroll_inicio_v = espia
    vista._teclado.foco.tomar("stock_minimo")

    _pulsar(vista, pagina, "Arrow Down")

    assert espia.llamadas == []


def test_con_un_campo_enfocado_las_teclas_de_funcion_si_actuan(vista, pagina):
    """Una tecla de función no edita texto, así que el foco no la bloquea; lo
    que no puede faltar es el ítem marcado."""
    _marcar(vista, "AUD-001", pagina)
    vista._teclado.foco.tomar("stock_minimo")

    _pulsar(vista, pagina, "F5")

    assert vista._vista_inventario_auxiliar._editing_codigo == "AUD-001"


def test_todos_los_campos_de_texto_del_inicio_estan_enlazados_al_foco(vista):
    """Sin el enlace, al usuario se le mueve la pantalla mientras escribe. La
    comprobación es sobre TODOS los campos del área y no sobre el de stock
    mínimo por su nombre: el día que se agregue un buscador o un filtro, este
    test tiene que fallar si nadie lo enlazó."""
    campos = [c for c in _recorrer(vista.build_data_sections()) if isinstance(c, ft.TextField)]

    assert campos, "no se encontró ningún campo de texto en el área de Inicio"
    for campo in campos:
        assert campo.on_focus is not None, f"campo '{campo.label}' sin enlazar"
        assert campo.on_blur is not None, f"campo '{campo.label}' sin enlazar"

    # Y el enlace surte efecto: el registro pasa a decir que hay foco.
    campos[0].on_focus(None)
    assert vista._teclado.foco.hay_campo_con_foco is True
    campos[0].on_blur(None)
    assert vista._teclado.foco.hay_campo_con_foco is False


def _recorrer(control, _vistos=None):
    if _vistos is None:
        _vistos = set()
    if control is None or not hasattr(control, "_c") or id(control) in _vistos:
        return
    _vistos.add(id(control))
    yield control
    for atributo in ("controls", "content", "actions", "title", "rows", "columns", "cells", "label"):
        hijo = getattr(control, atributo, None)
        if isinstance(hijo, list):
            for h in hijo:
                yield from _recorrer(h, _vistos)
        else:
            yield from _recorrer(hijo, _vistos)
