"""Borrado de una deuda: confirmación de la cascada y DESPUÉS la clave.

Respuesta explícita del usuario del proyecto: borrar una deuda SÍ debe pedir la
clave del usuario, igual que el borrado de ítems del inventario. El criterio es
que borrar una deuda arrastra en cascada su historial de abonos, o sea destruye
el registro de cuánto se cobró y quién cobró, y eso merece la misma protección.

El ORDEN de los dos pasos también es una decisión: primero la confirmación que
enuncia la cascada y recién después la clave. Primero se entiende que se va a
destruir y entonces se firma; pedir la clave antes de explicar qué se pierde
invierte el orden natural de la decisión.

Lo que estas pruebas blindan:
  - que confirmar la cascada NO borra: solo abre el diálogo de clave;
  - que cancelar en cualquiera de los dos pasos no borra nada;
  - que una clave incorrecta no borra y deja un error GENÉRICO que no contiene
    la clave tecleada (ni en el diálogo, ni en un snackbar, ni en ningún texto
    de la vista);
  - que la clave de OTRO usuario no sirve: es la de la cuenta con la sesión
    abierta;
  - que con la clave correcta la deuda se borra, sale de la lista y su marca se
    descarta del modelo de selección.
"""
import flet as ft
import pytest

from ui.components.dialogo_clave import MENSAJE_ERROR_GENERICO, DialogoClave

CLAVE = "clave-de-la-sesion-123"
CLAVE_AJENA = "clave-de-otro-usuario-456"
CLAVE_EQUIVOCADA = "esta-no-es-la-clave-789"
USUARIO = "cajera2"

FUTURO = "31/12/2027"

ITEMS = [
    {"producto_codigo": "P-001", "descripcion_corta": "Filtro de aceite", "cantidad": 2, "subtotal_usd": 20.0},
]


class PageFalsa:
    """Pila de diálogos de Flet 0.86 más el gancho de teclado."""

    def __init__(self):
        self.dialogos = []
        self.overlay = []
        self.updates = 0
        self.on_keyboard_event = None

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
        return next((d for d in reversed(self.dialogos) if d.open), None)


class EventoFalso:
    def __init__(self, page):
        self.page = page


def _aplanar(control, vistos=None) -> list:
    if control is None or isinstance(control, (str, int, float, bool)):
        return []
    vistos = set() if vistos is None else vistos
    if id(control) in vistos:
        return []
    vistos.add(id(control))
    encontrados = [control]
    for atributo in ("controls", "content", "actions", "title", "label"):
        hijo = getattr(control, atributo, None)
        if isinstance(hijo, (list, tuple)):
            for h in hijo:
                encontrados += _aplanar(h, vistos)
        elif hijo is not None and not isinstance(hijo, (str, int, float, bool)):
            encontrados += _aplanar(hijo, vistos)
    return encontrados


def _textos(control) -> list[str]:
    return [str(c.value) for c in _aplanar(control) if isinstance(c, ft.Text) and c.value]


def _snacks(pagina) -> list[str]:
    mensajes = []
    for control in pagina.overlay:
        if isinstance(control, ft.SnackBar):
            mensajes += _textos(control.content)
    return mensajes


@pytest.fixture
def pagina():
    return PageFalsa()


@pytest.fixture
def evento(pagina):
    return EventoFalso(pagina)


@pytest.fixture
def usuarios(db_temporal):
    """La cuenta de la sesión y una ajena, con claves distintas."""
    from services.user_service import create_user

    create_user(USUARIO, CLAVE, "vendedor")
    create_user("otro", CLAVE_AJENA, "administrador")
    return USUARIO


@pytest.fixture
def deuda(usuarios):
    from services.cartera_service import crear_cliente
    from services.deudas_service import crear_deuda, registrar_abono

    crear_cliente(nombre="Fulano de Tal", cedula_rif="V-12345678", telefono="0414-1234567")
    d = crear_deuda("V-12345678", 100.0, FUTURO, items=ITEMS)
    registrar_abono(d["id"], 40.0, usuario_nombre=USUARIO)
    return d


@pytest.fixture
def vista(deuda):
    """Depende de `deuda` a propósito: `CarteraView.__init__` ya dispara
    `get_body()` y con él la primera carga de la tabla, así que la deuda tiene
    que existir ANTES de construir la vista."""
    from ui.views.cartera_view import CarteraView

    return CarteraView(user_data={"username": USUARIO, "role": "vendedor"})


def _existe(deuda_id) -> bool:
    from services.deudas_service import obtener_deuda

    return obtener_deuda(deuda_id) is not None


def _boton_borrar(v):
    for control in _aplanar(v.dt_deudas.rows[0].cells[-1].content):
        tooltip = getattr(control, "tooltip", None)
        if isinstance(tooltip, str) and "borrar" in tooltip.lower():
            return control
    raise AssertionError("No se encontró el botón de Borrar en el renglón")


def _accion(dialogo, etiqueta: str):
    for a in dialogo.actions:
        texto = getattr(a, "text", None) or getattr(a, "content", None)
        if isinstance(texto, str) and etiqueta.lower() in texto.lower():
            return a
    raise AssertionError(f"No se encontró la acción '{etiqueta}'")


def _componente_clave(v) -> DialogoClave:
    """El `DialogoClave` viaja en el `data` del `AlertDialog` apilado."""
    comp = v._dialog.data
    assert isinstance(comp, DialogoClave), "el diálogo del tope debe ser el de clave"
    return comp


def _hasta_el_dialogo_de_clave(v, evento):
    """Recorre el camino completo del usuario: botón Borrar, confirmación de la
    cascada y confirmar, que deja arriba el diálogo de clave."""
    _boton_borrar(v).on_click(evento)
    confirmacion = v._dialog
    _accion(confirmacion, "Sí, Borrar").on_click(evento)
    return confirmacion, _componente_clave(v)


# ─── El orden de los dos pasos ───────────────────────────────────────────────

def test_el_primer_paso_es_la_confirmacion_que_enuncia_la_cascada(vista, deuda, evento):
    """Primero se entiende qué se destruye; la clave viene después."""
    _boton_borrar(vista).on_click(evento)

    textos = " ".join(_textos(vista._dialog))
    assert "cascada" in textos
    assert "historial de abonos" in textos
    assert "$40.00" in textos, "debe nombrar lo ya abonado, que es lo que se pierde"
    assert not isinstance(vista._dialog.data, DialogoClave), (
        "la clave no puede pedirse antes de explicar qué se pierde"
    )
    assert _existe(deuda["id"])


def test_la_confirmacion_avisa_de_que_vendra_la_clave(vista, deuda, evento):
    _boton_borrar(vista).on_click(evento)

    textos = " ".join(_textos(vista._dialog))
    assert "clave de su usuario" in textos


def test_confirmar_la_cascada_abre_la_clave_y_todavia_no_borra(vista, deuda, pagina, evento):
    confirmacion, comp = _hasta_el_dialogo_de_clave(vista, evento)

    assert confirmacion.open is False, "la confirmación cede su lugar"
    assert pagina.visible is comp.dialogo
    assert _existe(deuda["id"]), "confirmar la cascada no borra por sí mismo"


def test_el_dialogo_de_clave_nombra_la_deuda_que_va_a_borrar(vista, deuda, evento):
    """Nadie debe entregar su clave a ciegas: el mensaje dice qué autoriza."""
    _, comp = _hasta_el_dialogo_de_clave(vista, evento)

    textos = " ".join(_textos(comp.dialogo))
    assert "Fulano de Tal" in textos
    assert "V-12345678" in textos
    assert "historial de abonos" in textos


def test_el_campo_de_clave_viene_enmascarado(vista, deuda, evento):
    _, comp = _hasta_el_dialogo_de_clave(vista, evento)

    assert comp.campo.password is True


# ─── La clave correcta borra ─────────────────────────────────────────────────

def test_la_clave_correcta_borra_la_deuda_y_la_saca_de_la_lista(vista, deuda, pagina, evento):
    _, comp = _hasta_el_dialogo_de_clave(vista, evento)

    comp.campo.value = CLAVE
    assert comp.confirmar(evento) is True

    assert not _existe(deuda["id"])
    assert comp.dialogo.open is False
    assert pagina.visible is None
    assert vista._dialog_stack == []
    assert vista.dt_deudas.rows == []
    assert any("eliminada" in m.lower() for m in _snacks(pagina))


def test_el_borrado_autorizado_descarta_la_marca_del_renglon(vista, deuda, evento):
    """Si el id borrado quedara marcado, esa selección fantasma dejaría inertes
    los botones de todos los renglones vivos."""
    vista.dt_deudas.rows[0].on_select_change(evento)
    assert vista._seleccion_deudas.hay_seleccion is True

    _, comp = _hasta_el_dialogo_de_clave(vista, evento)
    comp.campo.value = CLAVE
    comp.confirmar(evento)

    assert vista._seleccion_deudas.hay_seleccion is False


def test_el_atajo_f6_recorre_los_mismos_dos_pasos(vista, deuda, evento):
    """La tecla y el ratón comparten el punto de entrada, así que F6 también
    pasa por la cascada y por la clave."""
    import asyncio

    class TeclaFalsa:
        def __init__(self, key):
            self.key = key

    vista.dt_deudas.rows[0].on_select_change(evento)
    vista._asegurar_teclado(evento)
    asyncio.run(vista._teclado.manejar(TeclaFalsa("F6")))

    assert "cascada" in " ".join(_textos(vista._dialog))
    _accion(vista._dialog, "Sí, Borrar").on_click(evento)
    comp = _componente_clave(vista)
    assert _existe(deuda["id"])

    comp.campo.value = CLAVE
    comp.confirmar(evento)
    assert not _existe(deuda["id"])


# ─── La clave incorrecta no borra ────────────────────────────────────────────

def test_una_clave_incorrecta_no_borra_y_deja_el_dialogo_abierto(vista, deuda, pagina, evento):
    _, comp = _hasta_el_dialogo_de_clave(vista, evento)

    comp.campo.value = CLAVE_EQUIVOCADA
    assert comp.confirmar(evento) is False

    assert _existe(deuda["id"])
    assert comp.dialogo.open is True, "debe quedar abierto para reintentar"
    assert pagina.visible is comp.dialogo


def test_el_error_de_clave_es_generico_y_no_contiene_la_clave_tecleada(
    vista, deuda, pagina, evento
):
    """La clave nunca va a un log, a un snackbar ni al texto de un error, y el
    mensaje no distingue casos: cada distinción le dice algo a quien está
    probando claves ajenas."""
    _, comp = _hasta_el_dialogo_de_clave(vista, evento)

    comp.campo.value = CLAVE_EQUIVOCADA
    comp.confirmar(evento)

    assert comp.error.value == MENSAJE_ERROR_GENERICO
    assert CLAVE_EQUIVOCADA not in comp.error.value
    assert comp.campo.value == "", "el valor tecleado se descarta en cuanto se usa"
    textos_visibles = " ".join(_textos(comp.dialogo) + _snacks(pagina))
    assert CLAVE_EQUIVOCADA not in textos_visibles
    assert CLAVE not in textos_visibles


def test_una_clave_vacia_da_el_mismo_error_generico(vista, deuda, evento):
    """No se distingue "clave vacía" de "clave equivocada"."""
    _, comp = _hasta_el_dialogo_de_clave(vista, evento)

    comp.campo.value = ""
    assert comp.confirmar(evento) is False
    assert comp.error.value == MENSAJE_ERROR_GENERICO
    assert _existe(deuda["id"])


def test_la_clave_de_otro_usuario_no_autoriza_el_borrado(vista, deuda, evento):
    """La clave es la de la cuenta con la que está abierta la sesión, no la de
    cualquier cuenta del sistema."""
    _, comp = _hasta_el_dialogo_de_clave(vista, evento)

    comp.campo.value = CLAVE_AJENA
    assert comp.confirmar(evento) is False
    assert _existe(deuda["id"])


def test_sin_usuario_en_sesion_no_se_puede_borrar(db_temporal, deuda, evento):
    """Fail-closed: es preferible no poder borrar a borrar sin autorización
    comprobable."""
    from ui.views.cartera_view import CarteraView

    v = CarteraView(user_data={})
    assert v.usuario_nombre is None

    _, comp = _hasta_el_dialogo_de_clave(v, evento)
    comp.campo.value = CLAVE
    assert comp.confirmar(evento) is False
    assert _existe(deuda["id"])


def test_un_reintento_con_la_clave_correcta_si_borra(vista, deuda, evento):
    _, comp = _hasta_el_dialogo_de_clave(vista, evento)

    comp.campo.value = CLAVE_EQUIVOCADA
    comp.confirmar(evento)
    comp.campo.value = CLAVE
    assert comp.confirmar(evento) is True

    assert not _existe(deuda["id"])


# ─── Cancelar en cualquiera de los dos pasos ─────────────────────────────────

def test_cancelar_la_confirmacion_de_la_cascada_no_borra_nada(vista, deuda, pagina, evento):
    _boton_borrar(vista).on_click(evento)
    _accion(vista._dialog, "Cancelar").on_click(evento)

    assert _existe(deuda["id"])
    assert pagina.visible is None
    assert vista._dialog_stack == []
    assert len(vista.dt_deudas.rows) == 1


def test_cancelar_el_dialogo_de_clave_no_borra_nada(vista, deuda, pagina, evento):
    _, comp = _hasta_el_dialogo_de_clave(vista, evento)

    comp.campo.value = CLAVE  # la clave correcta ya escrita, pero se cancela
    comp.cancelar(evento)

    assert _existe(deuda["id"])
    assert comp.dialogo.open is False
    assert pagina.visible is None
    assert vista._dialog_stack == []
    assert len(vista.dt_deudas.rows) == 1


def test_cancelar_la_clave_tampoco_la_deja_en_el_campo(vista, deuda, evento):
    _, comp = _hasta_el_dialogo_de_clave(vista, evento)

    comp.campo.value = CLAVE
    comp.cancelar(evento)

    assert comp.campo.value == ""
