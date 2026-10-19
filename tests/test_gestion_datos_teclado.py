"""Navegación con flechas en Gestión de Datos.

El usuario del proyecto pidió que las flechas naveguen en TODAS las vistas:
arriba, abajo, izquierda o derecha según los scrolls que haya, y con Ctrl hasta
el final del eje. En Gestión de Datos no hay ítems con iconos, así que acá va
solo la navegación: ninguna tecla de función hace nada, y eso también se
verifica — `ControlTeclado` recibe la vista SIN modelo de selección justamente
para que no pueda disparar acciones de ítem.

La mecánica de las teclas ya está probada en `tests/test_control_teclado.py`.
Lo que se prueba acá es el CABLEADO de esta vista, que es donde están las
decisiones propias: qué control desplaza cada eje en cada momento (el cuerpo, o
el scroll del modal que esté arriba) y que todos los campos de texto avisen del
foco. Un campo que no avise deja las flechas moviendo la pantalla mientras el
usuario escribe dentro de él, y eso no lo delata ningún otro test.

El handler es `async` porque `scroll_to` es una corutina, así que se ejercita
con `asyncio.run`, igual que en `test_control_teclado.py`.
"""
import asyncio
import types

import flet as ft
import pytest

from services import pedidos_service
from ui.components.teclado_nav import PASO_HORIZONTAL, PASO_VERTICAL

PROVEEDOR = "Distribuidora Andina"


class PaginaFalsa:
    """Doble de página con teclado y con la pila de diálogos de Flet 0.86."""

    def __init__(self):
        self.on_keyboard_event = None
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


class EventoFalso:
    def __init__(self, page=None, key=None, **modificadores):
        self.page = page
        self.key = key
        for nombre, valor in modificadores.items():
            setattr(self, nombre, valor)


class Grabador:
    """Reemplaza el `scroll_to` de un control real y anota cada llamada."""

    def __init__(self, control):
        self.llamadas = []
        control.scroll_to = self._scroll_to

    async def _scroll_to(self, **kwargs):
        self.llamadas.append(kwargs)


def _correr(corutina):
    return asyncio.run(corutina)


def _pulsar(vista, tecla, **modificadores):
    _correr(vista._teclado.manejar(EventoFalso(key=tecla, **modificadores)))


def _controles(control):
    yield control
    for atributo in ("controls", "content", "actions", "title"):
        hijo = getattr(control, atributo, None)
        if isinstance(hijo, list):
            for h in hijo:
                yield from _controles(h)
        elif hijo is not None and hasattr(hijo, "_c"):
            yield from _controles(hijo)


def _textfields(raiz) -> list:
    return [c for c in _controles(raiz) if isinstance(c, ft.TextField)]


def _campo(raiz, etiqueta: str):
    for c in _controles(raiz):
        if etiqueta.lower() in str(getattr(c, "label", "") or "").lower():
            return c
    raise AssertionError(f"No se encontró el campo '{etiqueta}'")


def _boton(raiz, etiqueta: str):
    for c in _controles(raiz):
        if getattr(c, "on_click", None) is None:
            continue
        textos = " ".join(
            str(x.value) for x in _controles(c) if isinstance(x, ft.Text) and x.value
        )
        contenido = getattr(c, "content", None)
        if isinstance(contenido, str):
            textos += " " + contenido
        if etiqueta.lower() in textos.lower():
            return c
    raise AssertionError(f"No se encontró un botón '{etiqueta}'")


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def borradores_limpios():
    yield
    pedidos_service._sesiones.clear()


@pytest.fixture
def banco_de_datos(db_temporal):
    from services.cartera_service import crear_proveedor
    from services.inventario_service import crear_producto

    crear_proveedor(empresa=PROVEEDOR, telefono="0412-5550000", rif="J-123456789")
    crear_producto(
        codigo="TUB-001",
        referencia="REF-TUB-001",
        descripcion_general="Tubo de escape universal",
        departamento="Repuestos",
        marca="Bosch",
        precio_dolares=30.0,
        existencia=4.0,
        nombre_referencia_corto="Tubo escape",
        costo_usd_efectivo=20.0,
        rol_usuario="administrador",
    )
    return "TUB-001"


@pytest.fixture
def entorno(banco_de_datos):
    """Vista montada sobre una página con teclado, con los atajos instalados.

    Reproduce el orden real: el Dashboard instancia la vista (todavía sin
    página), le asigna la página y recién entonces le pide el cuerpo. De ahí que
    la instalación tenga que ser perezosa.
    """
    from ui.views.gestion_datos_view import GestionDatosView

    pagina = PaginaFalsa()
    vista = GestionDatosView(user_data={"role": "administrador"})
    vista.get_current_page = lambda e=None: pagina
    cuerpo = vista.get_body()
    return {
        "vista": vista,
        "pagina": pagina,
        "cuerpo": cuerpo,
        "evento": EventoFalso(pagina),
        "grabador": Grabador(vista._cuerpo_scroll),
    }


# ─── Las flechas desplazan el cuerpo de la vista ─────────────────────────────

def test_al_pedir_el_cuerpo_los_atajos_quedan_instalados(entorno):
    assert entorno["pagina"].on_keyboard_event is entorno["vista"]._teclado.handler
    assert entorno["vista"]._teclado.instalado is True


def test_la_flecha_abajo_desplaza_el_cuerpo_de_la_vista(entorno):
    _pulsar(entorno["vista"], "Arrow Down")

    assert entorno["grabador"].llamadas == [{"delta": PASO_VERTICAL, "duration": 200}]


def test_la_flecha_arriba_desplaza_el_cuerpo_hacia_atras(entorno):
    _pulsar(entorno["vista"], "Arrow Up")

    assert entorno["grabador"].llamadas == [{"delta": -PASO_VERTICAL, "duration": 200}]


def test_control_flecha_abajo_va_al_final_del_eje(entorno):
    _pulsar(entorno["vista"], "Arrow Down", ctrl=True)

    assert entorno["grabador"].llamadas[0]["delta"] > 10000


def test_control_flecha_arriba_va_al_principio_del_eje(entorno):
    _pulsar(entorno["vista"], "Arrow Up", ctrl=True)

    assert entorno["grabador"].llamadas == [{"offset": 0.0, "duration": 200}]


def test_el_cuerpo_no_tiene_scroll_horizontal(entorno):
    """Las tarjetas se reacomodan con `ResponsiveRow` en vez de desbordarse, así
    que izquierda/derecha no tienen a qué aplicarse sobre el cuerpo."""
    _pulsar(entorno["vista"], "Arrow Right")

    assert entorno["vista"]._destino_horizontal() is None
    assert entorno["grabador"].llamadas == []


# ─── La regla del foco ───────────────────────────────────────────────────────

def test_con_un_campo_enfocado_las_flechas_no_desplazan(entorno):
    entorno["vista"]._teclado.foco.tomar("un_campo")

    _pulsar(entorno["vista"], "Arrow Down")

    assert entorno["grabador"].llamadas == []


def test_al_soltar_el_campo_las_flechas_vuelven_a_desplazar(entorno):
    foco = entorno["vista"]._teclado.foco
    foco.tomar("un_campo")
    _pulsar(entorno["vista"], "Arrow Down")

    foco.soltar("un_campo")
    _pulsar(entorno["vista"], "Arrow Down")

    assert len(entorno["grabador"].llamadas) == 1


def test_todos_los_campos_del_pedido_avisan_del_foco(entorno):
    """Los del asistente del pedido, las casillas del renglón y el cierre."""
    vista, evento = entorno["vista"], entorno["evento"]
    vista.mostrar_generador_pedido(evento)
    campos = _textfields(vista._dialog)
    _campo(vista._dialog, "Buscar item registrado").value = "TUB-001"
    _boton(vista._dialog, "Buscar").on_click(evento)
    _boton(vista._pedido_resultados_col, "Agregar al pedido").on_click(evento)
    campos += _textfields(vista._dialog)

    assert campos, "no se encontró ningún campo de texto"
    for campo in campos:
        assert campo.on_focus is not None, f"'{campo.label}' no avisa al tomar el foco"
        assert campo.on_blur is not None, f"'{campo.label}' no avisa al soltar el foco"


def test_escribir_en_un_campo_del_pedido_frena_las_flechas(entorno):
    """La prueba de punta a punta de la regla: se simula el foco por el propio
    `on_focus` del campo, como lo entregaría Flet."""
    vista, evento = entorno["vista"], entorno["evento"]
    vista.mostrar_generador_pedido(evento)
    busqueda = _campo(vista._dialog, "Buscar item registrado")
    grabador = Grabador(vista._destino_vertical())

    busqueda.on_focus(evento)
    _pulsar(vista, "Arrow Down")
    assert grabador.llamadas == []

    busqueda.on_blur(evento)
    _pulsar(vista, "Arrow Down")
    assert len(grabador.llamadas) == 1


def test_los_campos_del_alta_de_proveedores_avisan_del_foco(entorno, tmp_path):
    vista, evento = entorno["vista"], entorno["evento"]
    ruta = tmp_path / "x.xlsx"
    ruta.write_bytes(b"")

    vista.mostrar_asistente_proveedores_faltantes(evento, str(ruta), [PROVEEDOR])

    campos = _textfields(vista._dialog)
    assert len(campos) == 6
    for campo in campos:
        assert campo.on_focus is not None, f"'{campo.label}' no avisa al tomar el foco"
        assert campo.on_blur is not None, f"'{campo.label}' no avisa al soltar el foco"


# ─── Ninguna tecla de función hace nada ──────────────────────────────────────

@pytest.mark.parametrize("tecla", ["F1", "F2", "F3", "F4", "F5", "F6"])
def test_ninguna_tecla_de_funcion_dispara_nada(entorno, tecla):
    """Acá no hay ítems con iconos: `ControlTeclado` se cablea sin modelo de
    selección precisamente para que las teclas de función no puedan accionar."""
    vista = entorno["vista"]

    _pulsar(vista, tecla)

    assert vista._teclado.hay_seleccion is False
    assert entorno["grabador"].llamadas == []
    assert vista._dialog is None, "ninguna tecla de función debe abrir un diálogo"


def test_una_tecla_cualquiera_no_hace_nada(entorno):
    _pulsar(entorno["vista"], "K")

    assert entorno["grabador"].llamadas == []


# ─── La página se comparte con el Dashboard ──────────────────────────────────

def test_el_handler_previo_de_la_pagina_sigue_recibiendo_las_teclas(banco_de_datos):
    """La vista vive dentro del Dashboard, que puede tener su propio
    `on_keyboard_event`: instalar los atajos de Gestión de Datos no puede
    robarle el teclado al resto de la aplicación."""
    from ui.views.gestion_datos_view import GestionDatosView

    pagina = PaginaFalsa()
    recibidas = []
    pagina.on_keyboard_event = lambda e: recibidas.append(getattr(e, "key", None))

    vista = GestionDatosView(user_data={"role": "administrador"})
    vista.get_current_page = lambda e=None: pagina
    vista.get_body()
    Grabador(vista._cuerpo_scroll)

    _pulsar(vista, "Arrow Down")
    _pulsar(vista, "F5")
    _pulsar(vista, "Z")

    assert recibidas == ["Arrow Down", "F5", "Z"]


def test_instalar_dos_veces_no_duplica_el_desplazamiento(entorno):
    """La vista reinstala en cada handler porque al construirse todavía no hay
    página; sin la guarda de idempotencia, el control se encadenaría a sí mismo
    y una sola flecha se procesaría muchas veces."""
    vista = entorno["vista"]
    vista.get_body()
    vista._teclado.instalar(entorno["evento"])
    grabador = Grabador(vista._cuerpo_scroll)

    _pulsar(vista, "Arrow Down")

    assert len(grabador.llamadas) == 1


# ─── Con un modal arriba, las flechas desplazan el modal ─────────────────────

def test_con_el_pedido_abierto_las_flechas_desplazan_su_contenido(entorno):
    vista = entorno["vista"]
    vista.mostrar_generador_pedido(entorno["evento"])
    destino = vista._destino_vertical()
    assert destino is not None and destino is not vista._cuerpo_scroll
    grabador = Grabador(destino)

    _pulsar(vista, "Arrow Down")

    assert grabador.llamadas == [{"delta": PASO_VERTICAL, "duration": 200}]
    assert entorno["grabador"].llamadas == [], "no debe moverse la vista de atrás"


def test_al_cerrar_el_modal_las_flechas_vuelven_al_cuerpo(entorno):
    vista, evento = entorno["vista"], entorno["evento"]
    vista.mostrar_generador_pedido(evento)

    _boton(vista._pedido_dlg, "Cerrar sin exportar").on_click(evento)

    assert vista._destino_vertical() is vista._cuerpo_scroll
    _pulsar(vista, "Arrow Down")
    assert len(entorno["grabador"].llamadas) == 1


def test_un_modal_sin_scroll_propio_no_mueve_la_vista_de_atras(entorno):
    """Mover la pantalla que está detrás de un modal es desorientador y encima
    el modal tapa el resultado: mejor que las flechas no hagan nada."""
    vista = entorno["vista"]
    vista.mostrar_dialogo_error(entorno["evento"], "Falló la importación")

    _pulsar(vista, "Arrow Down")

    assert vista._destino_vertical() is None
    assert entorno["grabador"].llamadas == []


def test_el_asistente_de_mapeo_desplaza_la_vista_previa_con_las_flechas(entorno, tmp_path):
    """El caso que más lo necesita: la vista previa del archivo es una tabla
    ancha y hoy solo se recorre arrastrando una barra de scroll fina."""
    import pandas as pd

    vista = entorno["vista"]
    ruta = tmp_path / "catalogo.xlsx"
    with pd.ExcelWriter(str(ruta), engine="openpyxl") as writer:
        pd.DataFrame([{"Código": "TUB-001", "Existencia": 3, "Marca": "Bosch"}]).to_excel(
            writer, sheet_name="Productos", index=False
        )

    vista.mostrar_asistente_mapeo(entorno["evento"], str(ruta))

    vertical, horizontal = vista._destino_vertical(), vista._destino_horizontal()
    assert vertical is not None and horizontal is not None
    grabador_h = Grabador(horizontal)
    grabador_v = Grabador(vertical)

    _pulsar(vista, "Arrow Right")
    _pulsar(vista, "Arrow Down")

    assert grabador_h.llamadas == [{"delta": PASO_HORIZONTAL, "duration": 200}]
    assert grabador_v.llamadas == [{"delta": PASO_VERTICAL, "duration": 200}]


def test_un_destino_que_revienta_no_tumba_el_teclado(entorno):
    """Un control desmontado entre el repintado y la pulsación no puede dejar
    sin teclado a toda la aplicación."""
    vista = entorno["vista"]

    async def scroll_roto(**kwargs):
        raise RuntimeError("este control ya no está en pantalla")

    vista._cuerpo_scroll.scroll_to = scroll_roto

    _pulsar(vista, "Arrow Down")  # no debe propagar
