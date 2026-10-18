"""Pruebas del diálogo genérico de clave (`ui.components.dialogo_clave`).

El verificador entra inyectado, así que estas pruebas no necesitan base de
datos ni usuario real: lo que se blinda aquí es el CONTRATO de seguridad del
componente (campo enmascarado, error genérico, fail-closed, la clave no se
filtra a ningún texto visible) y que cancelar no ejecuta la acción.
"""
import flet as ft

from ui.components.dialogo_clave import (
    MENSAJE_ERROR_GENERICO, DialogoClave, construir_dialogo_clave,
)

CLAVE_BUENA = "s3cr3t0-del-usuario"


def _componente(verificar=None, **kwargs):
    ejecutado = []
    cerrado = []
    comp = DialogoClave(
        titulo=kwargs.pop("titulo", "Confirmar Eliminación"),
        mensaje=kwargs.pop("mensaje", "Se eliminará el ítem 'ABC-1'."),
        verificar_clave=verificar if verificar is not None else (lambda c: c == CLAVE_BUENA),
        on_exito=lambda e=None: ejecutado.append(True),
        on_cerrar=lambda e=None: cerrado.append(True),
        **kwargs,
    )
    return comp, ejecutado, cerrado


# ─────────────────────────────────────────────────────────────────────────────
# Forma del diálogo
# ─────────────────────────────────────────────────────────────────────────────
def test_el_campo_de_clave_esta_enmascarado_y_puede_revelarse():
    comp, _, _ = _componente()

    assert comp.campo.password is True
    assert comp.campo.can_reveal_password is True


def test_el_mensaje_enuncia_que_se_va_a_borrar():
    comp, _, _ = _componente(mensaje="Se eliminarán 3 ítems del inventario.")

    textos = [c.value for c in comp.dialogo.content.controls if isinstance(c, ft.Text)]
    assert any("3 ítems" in (t or "") for t in textos)


def test_el_componente_viaja_en_el_data_del_dialogo():
    comp, _, _ = _componente()

    assert comp.dialogo.data is comp


def test_el_atajo_devuelve_el_alert_dialog_con_su_componente():
    dlg = construir_dialogo_clave(
        titulo="T", mensaje="M",
        verificar_clave=lambda c: True,
        on_exito=lambda e=None: None,
    )

    assert isinstance(dlg, ft.AlertDialog)
    assert isinstance(dlg.data, DialogoClave)


# ─────────────────────────────────────────────────────────────────────────────
# Verificación
# ─────────────────────────────────────────────────────────────────────────────
def test_la_clave_correcta_cierra_y_ejecuta_la_accion():
    comp, ejecutado, cerrado = _componente()
    comp.campo.value = CLAVE_BUENA

    assert comp.confirmar(None) is True
    assert ejecutado == [True]
    assert cerrado == [True], "el cierre va antes de la acción, igual que en el resto del flujo"


def test_la_clave_incorrecta_no_ejecuta_y_da_un_error_generico():
    comp, ejecutado, cerrado = _componente()
    comp.campo.value = "no-es-la-clave"

    assert comp.confirmar(None) is False
    assert ejecutado == []
    assert cerrado == [], "el diálogo debe quedarse abierto para reintentar"
    assert comp.error.value == MENSAJE_ERROR_GENERICO


def test_la_clave_vacia_da_el_mismo_error_que_la_equivocada():
    """Sin distinguir casos: cualquier distinción informa a quien prueba claves."""
    comp, ejecutado, _ = _componente()
    comp.campo.value = ""

    comp.confirmar(None)

    assert ejecutado == []
    assert comp.error.value == MENSAJE_ERROR_GENERICO


def test_el_error_nunca_contiene_la_clave_tecleada():
    comp, _, _ = _componente()
    comp.campo.value = "clave-tecleada-por-el-usuario"

    comp.confirmar(None)

    assert "clave-tecleada" not in comp.error.value


def test_la_clave_se_descarta_del_campo_tras_cada_intento():
    comp, _, _ = _componente()
    comp.campo.value = "intento-fallido"
    comp.confirmar(None)
    assert comp.campo.value == ""

    comp.campo.value = CLAVE_BUENA
    comp.confirmar(None)
    assert comp.campo.value == ""


def test_un_verificador_que_estalla_no_autoriza_nada():
    def verificador_roto(_clave):
        raise RuntimeError("base de datos caída")

    comp, ejecutado, _ = _componente(verificar=verificador_roto)
    comp.campo.value = CLAVE_BUENA

    assert comp.confirmar(None) is False
    assert ejecutado == []
    assert comp.error.value == MENSAJE_ERROR_GENERICO


def test_la_clave_no_se_le_pasa_al_callback_de_exito():
    """`on_exito` recibe el evento, nunca la clave: así ningún consumidor puede
    terminar escribiéndola en un snackbar o en un log."""
    recibido = []
    comp = DialogoClave(
        titulo="T", mensaje="M",
        verificar_clave=lambda c: True,
        on_exito=lambda e=None: recibido.append(e),
    )
    comp.campo.value = CLAVE_BUENA

    comp.confirmar("evento")

    assert recibido == ["evento"]


# ─────────────────────────────────────────────────────────────────────────────
# Cancelación
# ─────────────────────────────────────────────────────────────────────────────
def test_cancelar_cierra_sin_ejecutar_la_accion():
    comp, ejecutado, cerrado = _componente()
    comp.campo.value = CLAVE_BUENA

    comp.cancelar(None)

    assert ejecutado == []
    assert cerrado == [True]
    assert comp.campo.value == ""


def test_los_botones_estan_cableados_a_los_metodos_con_nombre():
    """La segunda ola (atajos de teclado) necesita handlers invocables, no
    closures anónimas inalcanzables."""
    comp, _, _ = _componente()

    assert comp.boton_confirmar.on_click == comp.confirmar
    assert comp.boton_cancelar.on_click == comp.cancelar
    assert comp.campo.on_submit == comp.confirmar
