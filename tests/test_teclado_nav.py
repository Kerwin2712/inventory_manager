"""Atajos de teclado: flechas para navegar y F1–F6 para los íconos del ítem.

Lo que más importa aquí son las dos reglas que deciden si una tecla hace algo
o no: las flechas se callan cuando hay un campo de texto con el foco, y las
teclas de función se callan cuando no hay ningún ítem marcado. Las dos son
fáciles de romper al tocar la interfaz, y las dos son invisibles en una
captura de pantalla.
"""
import pytest

from ui.components.teclado_nav import (
    ABAJO,
    ACCIONES_CON_CLAVE,
    ACCIONES_SOLO_ADMIN,
    ARRIBA,
    ATAJOS_ITEM,
    DERECHA,
    EXTREMO,
    IZQUIERDA,
    LIMPIAR_SELECCION,
    PASO,
    PASO_HORIZONTAL,
    PASO_VERTICAL,
    IntencionAccion,
    IntencionScroll,
    IntencionSimple,
    RegistroFoco,
    desplazamiento,
    etiqueta_atajo,
    interpretar,
    interpretar_evento,
    tooltip_con_atajo,
)


class EventoFalso:
    """Doble del `KeyboardEvent` de Flet. Trae solo `key` a propósito, para
    comprobar que el intérprete no asume que los modificadores existen."""

    def __init__(self, key, **modificadores):
        self.key = key
        for nombre, valor in modificadores.items():
            setattr(self, nombre, valor)


# ─── Flechas: navegación ─────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "tecla,direccion",
    [
        ("Arrow Up", ARRIBA),
        ("Arrow Down", ABAJO),
        ("Arrow Left", IZQUIERDA),
        ("Arrow Right", DERECHA),
    ],
)
def test_las_cuatro_flechas_dan_un_paso(tecla, direccion):
    intencion = interpretar(tecla)
    assert isinstance(intencion, IntencionScroll)
    assert intencion.direccion == direccion
    assert intencion.alcance == PASO


@pytest.mark.parametrize("tecla", ["Arrow Up", "Arrow Down", "Arrow Left", "Arrow Right"])
def test_control_mas_flecha_va_al_extremo(tecla):
    """Ctrl+flecha es "hasta el final de la vista" en ese eje."""
    assert interpretar(tecla, ctrl=True).alcance == EXTREMO


def test_el_eje_y_el_signo_salen_de_la_direccion():
    assert interpretar("Arrow Up").eje == "vertical"
    assert interpretar("Arrow Right").eje == "horizontal"
    assert interpretar("Arrow Up").signo == -1
    assert interpretar("Arrow Down").signo == 1
    assert interpretar("Arrow Left").signo == -1
    assert interpretar("Arrow Right").signo == 1


# ─── La regla del foco ───────────────────────────────────────────────────────

@pytest.mark.parametrize("tecla", ["Arrow Up", "Arrow Down", "Arrow Left", "Arrow Right"])
def test_con_un_campo_enfocado_las_flechas_son_del_cursor(tecla):
    """Nadie espera que al corregir una palabra se le mueva la pantalla."""
    assert interpretar(tecla, hay_campo_con_foco=True) is None


def test_con_un_campo_enfocado_control_flecha_tampoco_navega():
    assert interpretar("Arrow Down", ctrl=True, hay_campo_con_foco=True) is None


def test_escape_funciona_incluso_con_un_campo_enfocado():
    """Es la excepción deliberada: el trabajo de Escape es justamente soltar
    el foco y devolver la navegación."""
    intencion = interpretar("Escape", hay_campo_con_foco=True)
    assert isinstance(intencion, IntencionSimple)
    assert intencion.nombre == LIMPIAR_SELECCION


def test_alt_y_meta_no_navegan():
    """Son combinaciones del sistema operativo y de la propia aplicación."""
    assert interpretar("Arrow Down", alt=True) is None
    assert interpretar("Arrow Down", meta=True) is None


def test_shift_flecha_sigue_navegando_fuera_de_un_campo():
    """Shift+flecha solo tiene un significado propio dentro de un campo de
    texto (seleccionar); fuera, no hay razón para ignorar la flecha."""
    assert interpretar("Arrow Down", shift=True) is not None


# ─── F1–F6: acciones sobre el ítem marcado ──────────────────────────────────

@pytest.mark.parametrize(
    "tecla,accion",
    [
        ("F1", "info"),
        ("F2", "cobrar"),
        ("F3", "carrito"),
        ("F4", "historial"),
        ("F5", "editar"),
        ("F6", "borrar"),
    ],
)
def test_mapeo_fijo_de_los_seis_iconos(tecla, accion):
    """Mapeo fijo por decisión del usuario: la misma tecla hace lo mismo para
    todos los roles."""
    intencion = interpretar(tecla, hay_seleccion=True)
    assert isinstance(intencion, IntencionAccion)
    assert intencion.accion == accion
    assert intencion.tecla == tecla


@pytest.mark.parametrize("tecla", list(ATAJOS_ITEM))
def test_sin_item_marcado_las_teclas_de_funcion_no_hacen_nada(tecla):
    """Adivinar un ítem sería disparar una acción —incluido un borrado— sobre
    algo que el usuario no eligió."""
    assert interpretar(tecla, hay_seleccion=False) is None


def test_f7_y_mas_alla_no_estan_asignadas():
    assert interpretar("F7", hay_seleccion=True) is None
    assert interpretar("F12", hay_seleccion=True) is None


def test_control_f_no_dispara_la_accion():
    """Ctrl+F suele ser "buscar": no debe confundirse con el atajo del ícono."""
    assert interpretar("F1", ctrl=True, hay_seleccion=True) is None


def test_las_teclas_de_funcion_actuan_aunque_haya_un_campo_enfocado():
    """Una tecla de función no edita texto, así que el foco no la bloquea; lo
    que no puede faltar es el ítem marcado."""
    assert interpretar("F5", hay_campo_con_foco=True, hay_seleccion=True) is not None


def test_historial_es_la_unica_accion_solo_admin():
    assert ACCIONES_SOLO_ADMIN == ("historial",)


def test_borrar_es_la_unica_accion_que_pide_clave():
    assert ACCIONES_CON_CLAVE == ("borrar",)


# ─── Teclas desconocidas ─────────────────────────────────────────────────────

@pytest.mark.parametrize("tecla", ["", None, "A", "Enter", "Tab", "Page Down"])
def test_las_teclas_sin_atajo_devuelven_none(tecla):
    assert interpretar(tecla, hay_seleccion=True) is None


# ─── Etiquetas visibles ──────────────────────────────────────────────────────

def test_cada_accion_sabe_decir_su_tecla():
    """El PDF pide los atajos a la vista: uno que hay que recordar de memoria
    no se usa."""
    assert etiqueta_atajo("info") == "F1"
    assert etiqueta_atajo("borrar") == "F6"
    assert etiqueta_atajo("inexistente") == ""


def test_el_tooltip_agrega_la_tecla():
    assert tooltip_con_atajo("Editar", "editar") == "Editar (F5)"
    assert tooltip_con_atajo("Otra cosa", "inexistente") == "Otra cosa"


# ─── Registro de foco ────────────────────────────────────────────────────────

def test_el_registro_arranca_sin_foco():
    assert RegistroFoco().hay_campo_con_foco is False


def test_tomar_y_soltar_el_foco():
    registro = RegistroFoco()
    registro.tomar("busqueda")
    assert registro.hay_campo_con_foco is True
    registro.soltar("busqueda")
    assert registro.hay_campo_con_foco is False


def test_el_cruce_de_eventos_de_foco_no_deja_el_registro_en_falso():
    """Al pasar de un campo a otro, Flet puede entregar el `on_focus` del
    nuevo antes que el `on_blur` del anterior. Con una bandera booleana ese
    cruce dejaría la navegación activa teniendo el cursor dentro de un campo;
    con un conjunto el orden deja de importar."""
    registro = RegistroFoco()
    registro.tomar("campo_a")
    registro.tomar("campo_b")      # entra al segundo
    registro.soltar("campo_a")     # y solo después sale del primero
    assert registro.hay_campo_con_foco is True

    registro.soltar("campo_b")
    assert registro.hay_campo_con_foco is False


def test_soltar_un_campo_que_no_estaba_no_falla():
    registro = RegistroFoco()
    registro.soltar("nunca_enfocado")
    assert registro.hay_campo_con_foco is False


def test_limpiar_suelta_todos_los_campos():
    registro = RegistroFoco()
    registro.tomar("uno")
    registro.tomar("dos")
    registro.limpiar()
    assert registro.hay_campo_con_foco is False


def test_enlazar_conecta_los_eventos_de_un_campo():
    class CampoFalso:
        on_focus = None
        on_blur = None

    registro = RegistroFoco()
    campo = registro.enlazar(CampoFalso(), "busqueda")

    campo.on_focus(None)
    assert registro.hay_campo_con_foco is True
    campo.on_blur(None)
    assert registro.hay_campo_con_foco is False


# ─── Desde el evento de Flet ─────────────────────────────────────────────────

def test_interpretar_evento_lee_un_evento_sin_modificadores():
    """El doble trae solo `key`: el intérprete no debe asumir que los
    modificadores existen."""
    intencion = interpretar_evento(EventoFalso("Arrow Down"))
    assert isinstance(intencion, IntencionScroll)
    assert intencion.direccion == ABAJO


def test_interpretar_evento_respeta_el_control():
    evento = EventoFalso("Arrow Right", ctrl=True)
    assert interpretar_evento(evento).alcance == EXTREMO


def test_interpretar_evento_respeta_el_foco_y_la_seleccion():
    assert interpretar_evento(EventoFalso("Arrow Up"), hay_campo_con_foco=True) is None
    assert interpretar_evento(EventoFalso("F2"), hay_seleccion=False) is None
    assert interpretar_evento(EventoFalso("F2"), hay_seleccion=True) is not None


# ─── Desplazamiento concreto ─────────────────────────────────────────────────

def test_un_paso_vertical_usa_delta_con_signo():
    assert desplazamiento(interpretar("Arrow Down")) == {"delta": PASO_VERTICAL}
    assert desplazamiento(interpretar("Arrow Up")) == {"delta": -PASO_VERTICAL}


def test_un_paso_horizontal_usa_su_propio_tamano():
    """El paso horizontal es mayor: una columna de la tabla ancha mide mucho
    más que una fila."""
    assert desplazamiento(interpretar("Arrow Right")) == {"delta": PASO_HORIZONTAL}
    assert desplazamiento(interpretar("Arrow Left")) == {"delta": -PASO_HORIZONTAL}
    assert PASO_HORIZONTAL > PASO_VERTICAL


def test_ir_al_principio_usa_offset_exacto():
    """`offset=0` es exacto; un delta negativo enorme se acumularía sobre la
    posición actual."""
    assert desplazamiento(interpretar("Arrow Up", ctrl=True)) == {"offset": 0.0}
    assert desplazamiento(interpretar("Arrow Left", ctrl=True)) == {"offset": 0.0}


def test_ir_al_final_usa_un_delta_que_flutter_acota():
    for tecla in ("Arrow Down", "Arrow Right"):
        resultado = desplazamiento(interpretar(tecla, ctrl=True))
        assert "delta" in resultado
        assert resultado["delta"] > 10000
