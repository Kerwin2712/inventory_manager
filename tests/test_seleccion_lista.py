"""Pruebas del modelo de selección de listas (`ui.components.seleccion_lista`).

Se prueba SIN Flet y sin base de datos: el componente es estado puro, y eso es
justamente lo que permite reutilizarlo en Inventario, Ventas y Deudas sin
arrastrar la interfaz de ninguna de las tres.

El contrato crítico que estas pruebas blindan es la regla "Importante" del PDF:
mientras no haya nada marcado, `puede_accionar()` dice sí para TODOS los ítems
(el sistema trabaja como la versión anterior); en cuanto hay algo marcado, solo
el marcado puede accionar.
"""
import pytest

from ui.components.seleccion_lista import (
    MODO_MULTIPLE, MODO_UNICO, SeleccionLista,
)


@pytest.fixture
def seleccion():
    return SeleccionLista()


# ─────────────────────────────────────────────────────────────────────────────
# Estado inicial y regla "sin selección todo funciona como antes"
# ─────────────────────────────────────────────────────────────────────────────
def test_arranca_sin_seleccion_y_en_modo_unico(seleccion):
    assert seleccion.modo == MODO_UNICO
    assert seleccion.hay_seleccion is False
    assert seleccion.seleccionado is None
    assert seleccion.seleccionados == ()
    assert seleccion.cantidad == 0


def test_sin_seleccion_cualquier_item_puede_accionar(seleccion):
    for codigo in ("A-1", "B-2", "C-3"):
        assert seleccion.puede_accionar(codigo) is True


def test_con_un_item_marcado_solo_ese_puede_accionar(seleccion):
    seleccion.seleccionar("A-1")

    assert seleccion.puede_accionar("A-1") is True
    assert seleccion.puede_accionar("B-2") is False
    assert seleccion.puede_accionar("C-3") is False


def test_tras_limpiar_vuelve_a_poder_accionar_cualquiera(seleccion):
    seleccion.seleccionar("A-1")
    seleccion.limpiar()

    assert seleccion.puede_accionar("B-2") is True


# ─────────────────────────────────────────────────────────────────────────────
# Modo único: marcador del PDF
# ─────────────────────────────────────────────────────────────────────────────
def test_modo_unico_mantiene_una_sola_clave_marcada(seleccion):
    seleccion.seleccionar("A-1")
    seleccion.seleccionar("B-2")

    assert seleccion.seleccionados == ("B-2",)
    assert seleccion.seleccionado == "B-2"


def test_seleccionar_nunca_desmarca(seleccion):
    """Clic en la fila (fuera de la casilla): solo puede marcar."""
    seleccion.seleccionar("A-1")
    seleccion.seleccionar("A-1")

    assert seleccion.seleccionado == "A-1"


def test_alternar_sobre_la_casilla_marcada_deselecciona(seleccion):
    seleccion.seleccionar("A-1")

    seleccion.alternar("A-1")

    assert seleccion.hay_seleccion is False


def test_alternar_sobre_otra_casilla_mueve_el_marcador(seleccion):
    seleccion.seleccionar("A-1")

    seleccion.alternar("B-2")

    assert seleccion.seleccionados == ("B-2",)


def test_limpiar_es_idempotente_sin_seleccion(seleccion):
    assert seleccion.limpiar() is False


def test_claves_vacias_se_ignoran(seleccion):
    assert seleccion.seleccionar(None) is False
    assert seleccion.seleccionar("   ") is False
    assert seleccion.alternar(None) is False
    assert seleccion.hay_seleccion is False


def test_las_claves_se_comparan_como_texto_sin_espacios(seleccion):
    seleccion.seleccionar(7)

    assert seleccion.esta_seleccionado("7") is True
    assert seleccion.esta_seleccionado(" 7 ") is True


# ─────────────────────────────────────────────────────────────────────────────
# Notificación de cambios
# ─────────────────────────────────────────────────────────────────────────────
def test_solo_notifica_cuando_el_estado_cambia():
    avisos = []
    s = SeleccionLista(on_cambio=lambda: avisos.append(1))

    s.seleccionar("A-1")
    s.seleccionar("A-1")   # ya estaba marcada: no hay cambio
    s.alternar("A-1")      # se desmarca: sí cambia
    s.limpiar()            # ya estaba vacía: no hay cambio

    assert len(avisos) == 2


# ─────────────────────────────────────────────────────────────────────────────
# Modo múltiple: lote para el borrado masivo
# ─────────────────────────────────────────────────────────────────────────────
def test_modo_multiple_acumula_claves_en_orden_de_marcado(seleccion):
    seleccion.activar_modo_multiple()
    seleccion.alternar("C-3")
    seleccion.alternar("A-1")
    seleccion.alternar("B-2")

    assert seleccion.seleccionados == ("C-3", "A-1", "B-2")
    assert seleccion.cantidad == 3


def test_en_modo_multiple_solo_los_marcados_pueden_accionar(seleccion):
    seleccion.activar_modo_multiple()
    seleccion.alternar("A-1")
    seleccion.alternar("B-2")

    assert seleccion.puede_accionar("A-1") is True
    assert seleccion.puede_accionar("B-2") is True
    assert seleccion.puede_accionar("Z-9") is False


def test_entrar_al_modo_multiple_conserva_el_item_ya_marcado(seleccion):
    seleccion.seleccionar("A-1")

    seleccion.activar_modo_multiple()

    assert seleccion.es_multiple is True
    assert seleccion.seleccionados == ("A-1",)


def test_salir_del_modo_multiple_limpia_el_lote(seleccion):
    seleccion.activar_modo_multiple()
    seleccion.alternar("A-1")
    seleccion.alternar("B-2")

    seleccion.desactivar_modo_multiple()

    assert seleccion.modo == MODO_UNICO
    assert seleccion.hay_seleccion is False


def test_alternar_modo_entra_y_sale(seleccion):
    seleccion.alternar_modo()
    assert seleccion.es_multiple is True

    seleccion.alternar_modo()
    assert seleccion.es_multiple is False


def test_descartar_olvida_las_claves_borradas(seleccion):
    seleccion.activar_modo_multiple()
    seleccion.alternar("A-1")
    seleccion.alternar("B-2")

    seleccion.descartar(["A-1", "B-2"])

    assert seleccion.hay_seleccion is False, "una selección fantasma bloquearía las filas vivas"


def test_descartar_claves_ajenas_no_cambia_nada(seleccion):
    seleccion.seleccionar("A-1")

    assert seleccion.descartar(["Z-9"]) is False
    assert seleccion.seleccionados == ("A-1",)


def test_seleccionado_en_modo_multiple_es_el_ultimo_marcado(seleccion):
    """Los atajos F1–F6 actúan "sobre el ítem marcado": con lote, el último."""
    seleccion.activar_modo_multiple()
    seleccion.alternar("A-1")
    seleccion.alternar("B-2")

    assert seleccion.seleccionado == "B-2"


# ─────────────────────────────────────────────────────────────────────────────
# Texto de estado y validación de modo
# ─────────────────────────────────────────────────────────────────────────────
def test_descripcion_de_estado_informa_cuantos_items_lleva(seleccion):
    assert seleccion.descripcion_estado() == "Sin selección"

    seleccion.activar_modo_multiple()
    seleccion.alternar("A-1")
    assert seleccion.descripcion_estado() == "1 ítem marcado"

    seleccion.alternar("B-2")
    assert seleccion.descripcion_estado() == "2 ítems marcados"


def test_un_modo_desconocido_se_rechaza_al_construir():
    with pytest.raises(ValueError):
        SeleccionLista(modo="telepatico")


def test_se_puede_construir_directamente_en_modo_multiple():
    s = SeleccionLista(modo=MODO_MULTIPLE)

    assert s.es_multiple is True
