"""Borrado de inventario con clave del usuario y borrado masivo.

Decisión del usuario del proyecto (no está en el PDF): borrar inventario es
irreversible y la sesión suele quedar abierta en un mostrador, así que CADA
borrado exige la clave de la cuenta con la que está abierta la sesión,
verificada contra su `password_hash` almacenado. El borrado por lote la pide
UNA SOLA VEZ para todo el lote.

Lo que estas pruebas blindan: que el camino del botón "Eliminar" no borra nada
por sí mismo, que la clave correcta borra, que la incorrecta no borra y da un
error genérico, que la clave de OTRO usuario no sirve (la clave es la de la
sesión), que cancelar no borra, y que el lote se cobra con un solo diálogo.
"""
import flet as ft
import pytest

CLAVE = "clave-de-la-sesion-123"
CLAVE_AJENA = "clave-de-otro-usuario-456"
CODIGOS = ("DEL-001", "DEL-002", "DEL-003", "DEL-004")


class PageFalsa:
    """Pila de diálogos de Flet 0.86, igual que en `test_inventario_dialogos_pila`."""

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


@pytest.fixture
def pagina():
    return PageFalsa()


@pytest.fixture
def evento(pagina):
    return EventoFalso(pagina)


@pytest.fixture
def usuarios(db_temporal):
    """Cuenta de la sesión y una cuenta ajena, con claves distintas."""
    from services.user_service import create_user

    create_user("cajero", CLAVE, "administrador")
    create_user("otro", CLAVE_AJENA, "administrador")
    return "cajero"


@pytest.fixture
def productos(db_temporal):
    from services.inventario_service import crear_producto

    for i, codigo in enumerate(CODIGOS, start=1):
        crear_producto(
            codigo=codigo,
            referencia=f"REF-{i}",
            descripcion_general=f"Producto borrable {i}",
            departamento="Pruebas",
            precio_dolares=5.0 * i,
            existencia=2,
            costo_usd_efectivo=2.0 * i,
            rol_usuario="administrador",
        )
    return list(CODIGOS)


@pytest.fixture
def vista(usuarios, productos):
    from ui.views.inventario_view import InventarioView

    v = InventarioView(es_admin=True, username=usuarios, rol_usuario="administrador")
    v.get_body()
    return v


def _existe(codigo: str) -> bool:
    from services.inventario_service import obtener_producto

    return obtener_producto(codigo) is not None


def _componente_clave(vista):
    """El `DialogoClave` viaja en el `data` del diálogo apilado."""
    from ui.components.dialogo_clave import DialogoClave

    comp = vista._dialog.data
    assert isinstance(comp, DialogoClave), "el diálogo del tope debe ser el de clave"
    return comp


def _texto_del_dialogo(vista) -> str:
    return " ".join(
        c.value or "" for c in vista._dialog.content.controls if isinstance(c, ft.Text)
    )


def _marcar_lote(vista, codigos, evento):
    vista.alternar_modo_seleccion(evento)
    for codigo in codigos:
        vista.alternar_item(codigo, evento)


# ─────────────────────────────────────────────────────────────────────────────
# Borrado de un ítem
# ─────────────────────────────────────────────────────────────────────────────
def test_pedir_el_borrado_no_elimina_nada_hasta_dar_la_clave(vista, evento):
    vista._confirmar_eliminar("DEL-001", evento)

    assert _existe("DEL-001"), "sin clave correcta no se borra nada"
    comp = _componente_clave(vista)
    assert comp.campo.password is True and comp.campo.can_reveal_password is True


def test_el_dialogo_enuncia_el_codigo_que_se_va_a_borrar(vista, evento):
    vista._confirmar_eliminar("DEL-002", evento)

    assert "DEL-002" in _texto_del_dialogo(vista)


def test_la_clave_correcta_borra_el_item(vista, pagina, evento):
    vista._confirmar_eliminar("DEL-001", evento)
    comp = _componente_clave(vista)
    comp.campo.value = CLAVE

    comp.confirmar(evento)

    assert not _existe("DEL-001")
    assert vista._dialog_stack == []
    assert pagina.visible is None, "el diálogo debe quedar cerrado"


def test_la_clave_incorrecta_no_borra_y_da_un_error_generico(vista, evento):
    vista._confirmar_eliminar("DEL-001", evento)
    comp = _componente_clave(vista)
    comp.campo.value = "no-es-la-clave"

    comp.confirmar(evento)

    assert _existe("DEL-001")
    assert comp.error.value == "Clave incorrecta"
    assert vista._dialog is comp.dialogo, "el diálogo sigue abierto para reintentar"


def test_la_clave_vacia_no_borra(vista, evento):
    vista._confirmar_eliminar("DEL-001", evento)
    comp = _componente_clave(vista)

    comp.confirmar(evento)

    assert _existe("DEL-001")
    assert comp.error.value == "Clave incorrecta"


def test_la_clave_de_otro_usuario_no_autoriza_el_borrado(vista, evento):
    """La clave exigida es la de la cuenta con la sesión abierta, no la de
    cualquier cuenta válida del sistema."""
    vista._confirmar_eliminar("DEL-001", evento)
    comp = _componente_clave(vista)
    comp.campo.value = CLAVE_AJENA

    comp.confirmar(evento)

    assert _existe("DEL-001")
    assert comp.error.value == "Clave incorrecta"


def test_cancelar_no_borra_nada(vista, pagina, evento):
    vista._confirmar_eliminar("DEL-001", evento)
    comp = _componente_clave(vista)
    comp.campo.value = CLAVE

    comp.cancelar(evento)

    assert _existe("DEL-001")
    assert vista._dialog_stack == []
    assert pagina.visible is None


def test_sin_usuario_en_sesion_no_se_autoriza_ningun_borrado(productos, evento):
    """Fail-closed: es preferible no poder borrar a borrar sin autorización
    comprobable."""
    from ui.views.inventario_view import InventarioView

    v = InventarioView(es_admin=True, username=None, rol_usuario="administrador")
    v.get_body()
    v._confirmar_eliminar("DEL-001", evento)
    comp = v._dialog.data
    comp.campo.value = CLAVE

    comp.confirmar(evento)

    assert _existe("DEL-001")
    assert comp.error.value == "Clave incorrecta"


def test_el_verificador_compara_contra_la_cuenta_de_la_sesion(vista):
    assert vista._verificar_clave_sesion(CLAVE) is True
    assert vista._verificar_clave_sesion(CLAVE_AJENA) is False
    assert vista._verificar_clave_sesion("") is False


def test_el_boton_borrar_de_la_fila_desemboca_en_el_dialogo_de_clave(vista, evento):
    """El camino real del usuario (clic en el icono de la papelera)."""
    vista.ejecutar_accion_item("borrar", "DEL-003", evento)

    assert _existe("DEL-003")
    assert _componente_clave(vista) is not None


# ─────────────────────────────────────────────────────────────────────────────
# Selección múltiple y borrado masivo
# ─────────────────────────────────────────────────────────────────────────────
def test_el_modo_multiple_permite_marcar_varios_items(vista, evento):
    _marcar_lote(vista, ["DEL-001", "DEL-002", "DEL-003"], evento)

    assert vista._seleccion.es_multiple is True
    assert vista._seleccion.cantidad == 3


def test_la_barra_muestra_cuantos_items_lleva_marcados(vista, evento):
    _marcar_lote(vista, ["DEL-001", "DEL-002"], evento)

    assert vista._lbl_seleccion.value == "2 ítems marcados"
    assert vista._btn_borrar_lote.visible is True
    assert "2" in vista._btn_borrar_lote.content.value


def test_la_barra_ofrece_entrar_y_salir_del_modo_multiple(vista, evento):
    assert vista._btn_modo_seleccion.on_click == vista.alternar_modo_seleccion
    assert vista._btn_borrar_lote.visible is False

    _marcar_lote(vista, ["DEL-001"], evento)
    vista.alternar_modo_seleccion(evento)

    assert vista._seleccion.es_multiple is False
    assert vista._seleccion.hay_seleccion is False, "salir del lote limpia la selección"
    assert vista._btn_borrar_lote.visible is False


def test_el_borrado_masivo_pide_la_clave_una_sola_vez_y_borra_todo_el_lote(
    vista, pagina, evento
):
    lote = ["DEL-001", "DEL-002", "DEL-003"]
    _marcar_lote(vista, lote, evento)

    vista._confirmar_eliminar_lote(evento)
    assert len(pagina.dialogos) == 1, "un solo diálogo de clave para todo el lote"
    comp = _componente_clave(vista)
    comp.campo.value = CLAVE
    comp.confirmar(evento)

    assert [c for c in lote if _existe(c)] == [], "el lote completo debe borrarse"
    assert _existe("DEL-004"), "lo que no estaba marcado no se toca"
    assert len(pagina.dialogos) == 1, "no se pidió la clave una segunda vez"


def test_el_dialogo_del_lote_enuncia_cuantos_items_se_borraran(vista, evento):
    _marcar_lote(vista, ["DEL-001", "DEL-002"], evento)

    vista._confirmar_eliminar_lote(evento)

    texto = _texto_del_dialogo(vista)
    assert "2" in texto and "DEL-001" in texto and "DEL-002" in texto


def test_la_clave_incorrecta_no_borra_el_lote(vista, evento):
    lote = ["DEL-001", "DEL-002"]
    _marcar_lote(vista, lote, evento)
    vista._confirmar_eliminar_lote(evento)
    comp = _componente_clave(vista)
    comp.campo.value = "no-es-la-clave"

    comp.confirmar(evento)

    assert all(_existe(c) for c in lote)
    assert comp.error.value == "Clave incorrecta"
    assert vista._seleccion.cantidad == 2, "el lote marcado se conserva para reintentar"


def test_cancelar_el_borrado_masivo_no_borra_nada(vista, evento):
    lote = ["DEL-001", "DEL-002"]
    _marcar_lote(vista, lote, evento)
    vista._confirmar_eliminar_lote(evento)

    _componente_clave(vista).cancelar(evento)

    assert all(_existe(c) for c in lote)
    assert vista._dialog_stack == []
    assert vista._seleccion.cantidad == 2


def test_tras_borrar_el_lote_no_queda_seleccion_fantasma(vista, evento):
    """Un código borrado que siguiera marcado dejaría inertes los botones de
    todas las filas vivas."""
    _marcar_lote(vista, ["DEL-001", "DEL-002"], evento)
    vista._confirmar_eliminar_lote(evento)
    comp = _componente_clave(vista)
    comp.campo.value = CLAVE
    comp.confirmar(evento)

    assert vista._seleccion.hay_seleccion is False
    assert vista._seleccion.es_multiple is False, "lote terminado: se sale del modo"
    assert vista._seleccion.puede_accionar("DEL-004") is True


def test_sin_items_marcados_el_borrado_masivo_no_abre_ningun_dialogo(vista, pagina, evento):
    vista.alternar_modo_seleccion(evento)

    assert vista._confirmar_eliminar_lote(evento) is None
    assert pagina.dialogos == []


def test_en_modo_multiple_los_items_no_marcados_quedan_deshabilitados(vista, evento):
    _marcar_lote(vista, ["DEL-001"], evento)

    fila_ajena = next(r for r in vista._dt.rows if r.data == "DEL-002")
    botones = [c for c in fila_ajena.cells[-1].content.controls if isinstance(c, ft.IconButton)]
    assert botones and all(b.disabled for b in botones)


def test_el_lote_puede_incluir_un_item_ya_borrado_sin_tumbar_el_flujo(vista, evento):
    """Si otro camino borró un código del lote, el resto debe borrarse igual."""
    from services.inventario_service import eliminar_producto

    _marcar_lote(vista, ["DEL-001", "DEL-002"], evento)
    eliminar_producto("DEL-001")

    vista._confirmar_eliminar_lote(evento)
    comp = _componente_clave(vista)
    comp.campo.value = CLAVE
    comp.confirmar(evento)

    assert not _existe("DEL-002")
