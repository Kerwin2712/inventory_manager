"""Diálogo de cobro del módulo de Ventas (`ui/views/ventas_view.py`).

"Preguntar siempre antes de procesar la compra": pulsar Procesar Venta abre
UN solo diálogo con la referencia del pago, el monto auto-rellenado y su
gemela "Descuento". Lo que se blinda aquí:

- El diálogo se monta y desmonta por la pila nativa de Flet 0.86
  (`show_dialog`/`pop_dialog`). Con el patrón heredado (`page.overlay` +
  bandera `open`) el cierre no se dibuja y el diálogo queda pegado, o activo
  pero invisible recibiendo clics (ver `tests/test_inventario_dialogos_pila.py`).
- La confirmación de omitir la referencia se apila ENCIMA del cobro y el [NO]
  devuelve al cobro intacto.
- El hint con la suma de costos solo lo ve quien puede ver costos; el piso se
  valida igual para todos en el servicio.
- Crédito solo se ofrece en Venta Formal.

La `PageFalsa` emula la API real de la página (misma que usa el test de la
pila de diálogos del Inventario) para ejercitar el mismo camino que la app.
"""
import pytest

from services.bcv_service import actualizar_tasa
from services.cart_manager import (
    establecer_metodo_pago,
    establecer_tipo_venta,
    limpiar_sesion,
    obtener_carrito_activo,
    vincular_cliente_a_carrito,
)
from services.cartera_service import crear_cliente
from services.inventario_service import crear_producto
from ui.views.ventas_view import VentasView


class PageFalsa:
    """Emula la pila de diálogos de `flet.BasePage`."""

    def __init__(self):
        self.dialogos = []
        self.overlay = []
        self.updates = 0

    def show_dialog(self, dialog):
        if dialog in self.dialogos:
            raise RuntimeError("Dialog is already opened")
        dialog.open = True
        self.dialogos.append(dialog)
        self.updates += 1

    def pop_dialog(self):
        dlg = next((d for d in reversed(self.dialogos) if d.open), None)
        if dlg is None:
            return None
        dlg.open = False
        self.updates += 1
        return dlg

    def update(self):
        self.updates += 1

    @property
    def visible(self):
        """El diálogo que Flutter pinta: el último abierto de la pila."""
        return next((d for d in reversed(self.dialogos) if d.open), None)


class EventoFalso:
    def __init__(self, page, control=None):
        self.page = page
        self.control = control


@pytest.fixture
def pagina():
    return PageFalsa()


@pytest.fixture
def evento(pagina):
    return EventoFalso(pagina)


def _vista(rol: str) -> VentasView:
    v = VentasView(user_data={"username": "usuario_test", "role": rol})
    v.get_body()
    limpiar_sesion(v._sid)  # El sid headless se comparte entre tests.
    return v


@pytest.fixture
def entorno(db_temporal):
    """Catálogo, cliente y vista headless. AAA: lista $100, costo $40."""
    actualizar_tasa(40.0)
    crear_producto(
        codigo="AAA", referencia="REF-A", descripcion_general="Producto A",
        departamento="Pruebas", precio_dolares=100.0, precio_bcv=110.0,
        existencia=10.0, costo_usd_efectivo=40.0, rol_usuario="administrador",
    )
    crear_cliente(nombre="Cliente Uno", cedula_rif="V-22222222",
                  telefono="0412-0000000", direccion="Calle Vieja", correo="uno@ejemplo.com")
    crear_cliente(nombre="Cliente Sin Datos", cedula_rif="V-33333333")
    return db_temporal


@pytest.fixture
def vista_admin(entorno):
    v = _vista("administrador")
    yield v
    limpiar_sesion(v._sid)


@pytest.fixture
def vista_vendedor(entorno):
    v = _vista("vendedor")
    yield v
    limpiar_sesion(v._sid)


def _cargar_carrito(vista, cantidad=1.0):
    vista.agregar_producto_directo(
        {"codigo": "AAA", "precio_dolares": 100.0, "precio_bcv": 110.0,
         "nombre_referencia_corto": "Prod A"},
        cantidad, None,
    )


def _vincular(vista, cedula="V-22222222"):
    from services.cartera_service import obtener_cliente

    vincular_cliente_a_carrito(vista._sid, obtener_cliente(cedula))


def _accion(dlg, etiqueta: str):
    """Localiza un botón del diálogo por su etiqueta (en Flet 0.86 el texto de
    un botón puede vivir en `content` y no en `text`)."""
    from tests.test_ventas_flujo_busqueda import _textos

    for accion in dlg.actions:
        etiquetas = [
            valor for valor in (getattr(accion, "text", None), getattr(accion, "content", None))
            if isinstance(valor, str)
        ]
        etiquetas.extend(_textos(accion))
        if any(etiqueta.lower() in texto.lower() for texto in etiquetas):
            return accion
    raise AssertionError(f"No se encontró la acción '{etiqueta}'")


def _click(dlg, etiqueta: str, ev):
    _accion(dlg, etiqueta).on_click(ev)


# ─── 1. El diálogo único de cobro ────────────────────────────────────────────

def test_procesar_venta_con_el_carrito_vacio_no_abre_el_dialogo(vista_admin, evento):
    vista_admin.handle_procesar_venta(evento)

    assert vista_admin._dialog_stack == []
    assert evento.page.visible is None


def test_procesar_venta_abre_el_dialogo_de_cobro_en_la_pila_de_la_pagina(vista_admin, evento):
    establecer_tipo_venta(vista_admin._sid, "Informal")
    _cargar_carrito(vista_admin)

    vista_admin.handle_procesar_venta(evento)

    assert evento.page.visible is vista_admin._dlg_cobro
    assert vista_admin._dialog_stack == [vista_admin._dlg_cobro]


def test_el_monto_a_cobrar_se_autorellena_con_el_total_en_efectivo(vista_admin, evento):
    establecer_tipo_venta(vista_admin._sid, "Informal")
    _cargar_carrito(vista_admin, cantidad=2.0)

    vista_admin.handle_procesar_venta(evento)

    assert vista_admin.txt_monto_cobrar.value == "200.00"
    assert vista_admin.txt_monto_cobrar.read_only is True
    assert vista_admin._monto_predeterminado == 200.0


def test_el_monto_a_cobrar_se_autorellena_en_bolivares_con_un_metodo_en_bs(vista_admin, evento):
    establecer_tipo_venta(vista_admin._sid, "Informal")
    _cargar_carrito(vista_admin)
    establecer_metodo_pago(vista_admin._sid, "Transferencia")

    vista_admin.handle_procesar_venta(evento)

    # Precio USD BCV 110 x tasa 40 = Bs. 4.400 por unidad.
    assert vista_admin._monto_predeterminado == 4400.0
    assert "Bs." in vista_admin.txt_monto_cobrar.label


def test_el_efectivo_no_muestra_la_casilla_de_referencia_ni_la_omision(vista_admin, evento):
    establecer_tipo_venta(vista_admin._sid, "Informal")
    _cargar_carrito(vista_admin)

    vista_admin.handle_procesar_venta(evento)

    assert vista_admin.txt_referencia_pago.visible is False
    with pytest.raises(AssertionError):
        _accion(vista_admin._dlg_cobro, "Omitir referencia")


def test_un_metodo_distinto_de_efectivo_exige_la_referencia_en_el_dialogo(vista_admin, evento):
    establecer_tipo_venta(vista_admin._sid, "Informal")
    _cargar_carrito(vista_admin)
    establecer_metodo_pago(vista_admin._sid, "Punto")

    vista_admin.handle_procesar_venta(evento)
    assert vista_admin.txt_referencia_pago.visible is True

    _click(vista_admin._dlg_cobro, "Confirmar Cobro", evento)

    assert "referencia" in vista_admin._lbl_err_cobro.value.lower()
    assert evento.page.visible is vista_admin._dlg_cobro, "el diálogo no se cierra con el error"


# ─── 2. Porcentaje de descuento con sus dos signos ───────────────────────────

def test_la_casilla_descuento_vacia_no_muestra_porcentaje(vista_admin, evento):
    establecer_tipo_venta(vista_admin._sid, "Informal")
    _cargar_carrito(vista_admin)
    vista_admin.handle_procesar_venta(evento)

    vista_admin.txt_descuento.value = ""
    vista_admin.txt_descuento.on_change(evento)

    assert vista_admin.lbl_pct_descuento.value == ""


def test_un_descuento_por_debajo_de_la_lista_se_muestra_en_rojo(vista_admin, evento):
    import flet as ft

    establecer_tipo_venta(vista_admin._sid, "Informal")
    _cargar_carrito(vista_admin)
    vista_admin.handle_procesar_venta(evento)

    vista_admin.txt_descuento.value = "66,25"
    vista_admin.txt_descuento.on_change(evento)

    assert vista_admin.lbl_pct_descuento.value == "-33,75% OFF"
    assert vista_admin.lbl_pct_descuento.color == ft.Colors.RED_500


def test_un_monto_por_encima_de_la_lista_se_muestra_en_verde(vista_admin, evento):
    import flet as ft

    establecer_tipo_venta(vista_admin._sid, "Informal")
    _cargar_carrito(vista_admin)
    vista_admin.handle_procesar_venta(evento)

    vista_admin.txt_descuento.value = "111,23"
    vista_admin.txt_descuento.on_change(evento)

    assert vista_admin.lbl_pct_descuento.value == "+11,23% ON"
    assert vista_admin.lbl_pct_descuento.color == ft.Colors.GREEN_600


# ─── 3. El costo solo se le muestra a quien puede verlo ──────────────────────

def test_el_hint_del_costo_se_muestra_a_un_administrador(vista_admin, evento):
    establecer_tipo_venta(vista_admin._sid, "Informal")
    _cargar_carrito(vista_admin, cantidad=2.0)

    vista_admin.handle_procesar_venta(evento)

    assert vista_admin.txt_descuento.hint_text == "Costo: $ 80.00"


def test_la_casilla_descuento_aparece_vacia_y_sin_hint_para_un_vendedor(vista_vendedor, evento):
    """Fuga de información: los costos son reservados a la administración."""
    establecer_tipo_venta(vista_vendedor._sid, "Informal")
    _cargar_carrito(vista_vendedor, cantidad=2.0)

    vista_vendedor.handle_procesar_venta(evento)

    assert vista_vendedor.txt_descuento.value in (None, "")
    assert vista_vendedor.txt_descuento.hint_text is None


def test_el_hint_del_costo_desaparece_al_escribir_en_la_casilla(vista_admin, evento):
    establecer_tipo_venta(vista_admin._sid, "Informal")
    _cargar_carrito(vista_admin)
    vista_admin.handle_procesar_venta(evento)
    assert vista_admin.txt_descuento.hint_text is not None

    vista_admin.txt_descuento.value = "90"
    vista_admin.txt_descuento.on_change(evento)
    assert vista_admin.txt_descuento.hint_text is None

    # Y vuelve a asomarse cuando la casilla queda vacía otra vez.
    vista_admin.txt_descuento.value = ""
    vista_admin.txt_descuento.on_change(evento)
    assert vista_admin.txt_descuento.hint_text == "Costo: $ 40.00"


def test_el_piso_rechazado_a_un_vendedor_no_revela_el_costo(vista_vendedor, evento):
    establecer_tipo_venta(vista_vendedor._sid, "Informal")
    _cargar_carrito(vista_vendedor)
    vista_vendedor.handle_procesar_venta(evento)
    vista_vendedor.txt_descuento.value = "30"

    _click(vista_vendedor._dlg_cobro, "Confirmar Cobro", evento)

    mensaje = vista_vendedor._lbl_err_cobro.value
    assert "administrador" in mensaje.lower()
    assert "40" not in mensaje
    assert obtener_carrito_activo(vista_vendedor._sid)["items"], "la venta no se registró"


# ─── 4. Confirmación de omitir la referencia ─────────────────────────────────

def test_omitir_referencia_apila_la_confirmacion_encima_del_cobro(vista_admin, evento):
    establecer_tipo_venta(vista_admin._sid, "Informal")
    _cargar_carrito(vista_admin)
    establecer_metodo_pago(vista_admin._sid, "Pago Móvil")
    vista_admin.handle_procesar_venta(evento)

    _click(vista_admin._dlg_cobro, "Omitir referencia", evento)

    assert vista_admin._dialog_stack == [vista_admin._dlg_cobro, vista_admin._dlg_omitir_referencia]
    assert evento.page.visible is vista_admin._dlg_omitir_referencia


def test_el_no_de_la_confirmacion_devuelve_al_dialogo_de_cobro(vista_admin, evento):
    establecer_tipo_venta(vista_admin._sid, "Informal")
    _cargar_carrito(vista_admin)
    establecer_metodo_pago(vista_admin._sid, "Pago Móvil")
    vista_admin.handle_procesar_venta(evento)
    _click(vista_admin._dlg_cobro, "Omitir referencia", evento)
    dlg_confirmar = vista_admin._dlg_omitir_referencia

    _click(dlg_confirmar, "NO", evento)

    assert dlg_confirmar.open is False
    assert evento.page.visible is vista_admin._dlg_cobro
    assert obtener_carrito_activo(vista_admin._sid)["items"], "no se cobró nada"


def test_el_si_de_la_confirmacion_cobra_y_registra_la_omision(vista_admin, evento):
    from core.database import get_connection

    establecer_tipo_venta(vista_admin._sid, "Informal")
    _cargar_carrito(vista_admin)
    establecer_metodo_pago(vista_admin._sid, "Pago Móvil")
    vista_admin.handle_procesar_venta(evento)
    _click(vista_admin._dlg_cobro, "Omitir referencia", evento)

    _click(vista_admin._dlg_omitir_referencia, "Sí, omitir", evento)

    with get_connection() as conn:
        fila = conn.execute("SELECT * FROM ventas ORDER BY id DESC LIMIT 1").fetchone()
    assert fila["referencia_omitida"] == 1
    assert fila["referencia_pago"] is None
    assert obtener_carrito_activo(vista_admin._sid)["items"] == [], "el carrito se vacía"


# ─── 5. Cobro completo con descuento ─────────────────────────────────────────

def test_el_cobro_persiste_referencia_monto_y_porcentaje(vista_admin, evento):
    from core.database import get_connection

    establecer_tipo_venta(vista_admin._sid, "Informal")
    _cargar_carrito(vista_admin)
    establecer_metodo_pago(vista_admin._sid, "Punto")
    vista_admin.handle_procesar_venta(evento)
    vista_admin.txt_referencia_pago.value = "REF-7788"
    vista_admin.txt_descuento.value = "3960"  # Bs, sobre Bs 4.400 de lista

    _click(vista_admin._dlg_cobro, "Confirmar Cobro", evento)

    with get_connection() as conn:
        fila = conn.execute("SELECT * FROM ventas ORDER BY id DESC LIMIT 1").fetchone()
    assert fila["referencia_pago"] == "REF-7788"
    assert fila["monto_cobrado"] == 3960.0
    assert fila["total_bcv"] == 4400.0, "el precio de lista se conserva"
    assert fila["porcentaje_descuento"] == pytest.approx(-10.0)
    assert fila["usuario_nombre"] == "usuario_test"
    assert vista_admin._dialog_stack == [vista_admin._dlg_pdf], "solo queda el diálogo del PDF"


# ─── 6. Crédito en la vista ──────────────────────────────────────────────────

def test_el_credito_se_ofrece_solo_en_venta_formal(vista_admin, evento):
    claves_formal = [o.key for o in vista_admin._opciones_metodo_pago({"tipo_venta": "Formal"})]
    claves_mostrador = [o.key for o in vista_admin._opciones_metodo_pago({"tipo_venta": "Informal"})]

    assert "Credito" in claves_formal
    assert "Credito" not in claves_mostrador


def test_pasar_a_mostrador_con_credito_devuelve_el_selector_a_efectivo(vista_admin, evento):
    import flet as ft

    _cargar_carrito(vista_admin)
    _vincular(vista_admin)
    establecer_metodo_pago(vista_admin._sid, "Credito")

    selector = ft.SegmentedButton(selected=["Informal"], segments=[])
    vista_admin.handle_cambio_tipo_venta(EventoFalso(evento.page, control=selector))

    assert obtener_carrito_activo(vista_admin._sid)["metodo_pago"] == "Efectivo"
    assert vista_admin.dd_metodo_pago.value == "Efectivo"
    assert "Credito" not in [o.key for o in vista_admin.dd_metodo_pago.options]


def test_elegir_credito_abre_la_ventana_del_compromiso_autorellenada(vista_admin, evento):
    _cargar_carrito(vista_admin)
    _vincular(vista_admin)

    vista_admin.dd_metodo_pago.value = "Credito"
    vista_admin.handle_cambio_metodo_pago(EventoFalso(evento.page, control=vista_admin.dd_metodo_pago))

    assert evento.page.visible is vista_admin._dlg_credito
    assert vista_admin.txt_credito_telefono.value == "0412-0000000"
    assert vista_admin.txt_credito_direccion.value == "Calle Vieja"
    assert vista_admin.txt_credito_correo.value == "uno@ejemplo.com"


def test_la_ventana_de_credito_deja_en_blanco_lo_que_el_cliente_no_tenia(vista_admin, evento):
    _cargar_carrito(vista_admin)
    _vincular(vista_admin, "V-33333333")

    vista_admin.abrir_ventana_credito(evento)

    assert vista_admin.txt_credito_telefono.value == ""
    assert vista_admin.txt_credito_direccion.value == ""
    assert vista_admin.txt_credito_contacto2.value == ""


def test_sin_cliente_vinculado_la_ventana_de_credito_no_se_puede_completar(vista_admin, evento):
    establecer_tipo_venta(vista_admin._sid, "Informal")
    _cargar_carrito(vista_admin)

    vista_admin.abrir_ventana_credito(evento)

    assert "Cédula/RIF" in vista_admin._lbl_err_credito.value
    assert _accion(vista_admin._dlg_credito, "Guardar Compromiso").disabled is True


def test_la_ventana_de_credito_rechaza_una_fecha_limite_mal_escrita(vista_admin, evento):
    _cargar_carrito(vista_admin)
    _vincular(vista_admin)
    vista_admin.abrir_ventana_credito(evento)
    vista_admin.txt_credito_fecha.value = "mañana"

    _click(vista_admin._dlg_credito, "Guardar Compromiso", evento)

    assert "ERR_DEUDA_FECHA" in vista_admin._lbl_err_credito.value
    assert vista_admin._datos_credito is None


def test_guardar_el_compromiso_actualiza_la_ficha_del_cliente(vista_admin, evento):
    from services.cartera_service import obtener_cliente

    _cargar_carrito(vista_admin)
    _vincular(vista_admin, "V-33333333")
    vista_admin.abrir_ventana_credito(evento)
    vista_admin.txt_credito_fecha.value = "15/01/2027"
    vista_admin.txt_credito_telefono.value = "0424-5556677"
    vista_admin.txt_credito_direccion.value = "Av. Nueva, casa 5"
    vista_admin.txt_credito_correo.value = "nuevo@ejemplo.com"

    _click(vista_admin._dlg_credito, "Guardar Compromiso", evento)

    assert vista_admin._datos_credito["fecha_limite_pago"] == "2027-01-15"
    cliente = obtener_cliente("V-33333333")
    assert cliente["telefono"] == "0424-5556677"
    assert cliente["direccion"] == "Av. Nueva, casa 5"
    assert cliente["correo"] == "nuevo@ejemplo.com"


def test_cancelar_el_compromiso_devuelve_el_metodo_a_efectivo(vista_admin, evento):
    _cargar_carrito(vista_admin)
    _vincular(vista_admin)
    establecer_metodo_pago(vista_admin._sid, "Credito")
    vista_admin.abrir_ventana_credito(evento)

    _click(vista_admin._dlg_credito, "Cancelar", evento)

    assert obtener_carrito_activo(vista_admin._sid)["metodo_pago"] == "Efectivo"
    assert vista_admin._datos_credito is None
    assert evento.page.visible is None


def test_cobrar_a_credito_crea_la_venta_y_su_deuda(vista_admin, evento):
    from services import deudas_service

    _cargar_carrito(vista_admin)
    _vincular(vista_admin)
    establecer_metodo_pago(vista_admin._sid, "Credito")
    vista_admin.abrir_ventana_credito(evento)
    vista_admin.txt_credito_fecha.value = "20/11/2026"
    _click(vista_admin._dlg_credito, "Guardar Compromiso", evento)

    vista_admin.handle_procesar_venta(evento)
    vista_admin.txt_referencia_pago.value = "COMPROMISO-55"
    _click(vista_admin._dlg_cobro, "Confirmar Cobro", evento)

    deudas = deudas_service.listar_deudas()
    assert len(deudas) == 1
    assert deudas[0]["cliente_id"] == "V-22222222"
    assert deudas[0]["monto_total_usd"] == 100.0
    assert deudas[0]["fecha_limite_pago"] == "2026-11-20"
    # Tras cobrar a crédito el carrito queda sin cliente: el método vuelve a
    # Efectivo para no arrancar la próxima venta en un estado inválido.
    assert obtener_carrito_activo(vista_admin._sid)["metodo_pago"] == "Efectivo"


def test_el_descuento_a_credito_mayor_al_cinco_por_ciento_se_rechaza_en_el_dialogo(vista_admin, evento):
    _cargar_carrito(vista_admin)
    _vincular(vista_admin)
    establecer_metodo_pago(vista_admin._sid, "Credito")
    vista_admin.abrir_ventana_credito(evento)
    vista_admin.txt_credito_fecha.value = "20/11/2026"
    _click(vista_admin._dlg_credito, "Guardar Compromiso", evento)

    vista_admin.handle_procesar_venta(evento)
    vista_admin.txt_referencia_pago.value = "COMPROMISO-56"
    vista_admin.txt_descuento.value = "90"  # -10% sobre $100 de lista
    _click(vista_admin._dlg_cobro, "Confirmar Cobro", evento)

    assert "ERR_VENTA_CREDITO_DESCUENTO" in vista_admin._lbl_err_cobro.value
    assert obtener_carrito_activo(vista_admin._sid)["items"], "no se cobró nada"
