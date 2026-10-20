"""Acciones de un ítem en la Auditoría Preventiva del Inicio.

Decisión del usuario del proyecto: SOLO las acciones de reposición —ver
detalle, historial clínico, editar y contactar al proveedor—. Cobrar y Carrito
se descartaron expresamente ("es una lista para reponer stock, no para
vender") y Borrar no está entre las elegidas.

Lo que se blinda aquí:
  - Los cuatro íconos existen en los tres formatos y TODOS entran por el mismo
    punto de entrada con nombre (`ejecutar_accion_auditoria`), que es el que
    van a recorrer también los atajos de teclado.
  - Las tres acciones que ya existen en el catálogo se le piden a una vista de
    Inventario auxiliar en vez de duplicar sus modales, y esa vista comparte el
    registro de foco y refresca ESTA lista al guardar.
  - "Contactar proveedor" no repite el mismo proveedor dos veces.
"""
import flet as ft
import pytest

from services.cartera_service import crear_proveedor
from services.inventario_service import crear_producto
from ui.components.teclado_nav import ATAJOS_ITEM

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
    """Página headless con pila de diálogos y teclado, como la real."""

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


@pytest.fixture
def pagina():
    return PaginaFalsa()


@pytest.fixture
def evento(pagina):
    return EventoFalso(pagina)


@pytest.fixture
def datos(db_temporal):
    """Tres productos críticos: dos del mismo proveedor y uno huérfano."""
    acme = crear_proveedor(
        empresa="Acme C.A.", contacto="Juan Pérez", telefono="0412-1112233",
        correo="ventas@acme.com", rif="J-111111",
    )
    for codigo in ("AUD-001", "AUD-002"):
        crear_producto(
            codigo=codigo, referencia=f"REF-{codigo}",
            descripcion_general=f"Producto critico {codigo}",
            departamento="Ferretería", marca="Acme",
            precio_dolares=2.0, existencia=0.0,
            nombre_referencia_corto=f"Corto {codigo}",
            proveedor_id=acme["id"],
            costo_usd_efectivo=None, rol_usuario="administrador",
        )
    crear_producto(
        codigo="AUD-003", referencia="REF-3",
        descripcion_general="Producto sin proveedor",
        departamento="Ferretería", precio_dolares=1.0, existencia=0.0,
        nombre_referencia_corto="Corto AUD-003",
        costo_usd_efectivo=None, rol_usuario="administrador",
    )
    return {"acme": acme["id"]}


@pytest.fixture
def vista(datos, pagina):
    from ui.views.dashboard_view import DashboardView

    DashboardView.ensure_settings_loaded()
    v = DashboardView(user_info={"username": "tester", "role": "administrador"})
    v.get_current_page = lambda e=None: pagina
    v.current_section = "Inicio"
    v.get_body()
    return v


MODOS = ["separado", "agrupado", "tarjetas"]


@pytest.fixture(params=MODOS)
def vista_modo(request, vista):
    vista._modo_vista_auditoria = request.param
    vista._cargar_filas_auditoria()
    return vista


# ── Lectura de los íconos de una fila ───────────────────────────────────────
def _icono_de(control) -> ft.IconButton:
    """Los botones con atajo viajan dentro de un `Stack` junto a su etiqueta."""
    if isinstance(control, ft.Stack):
        return next(c for c in control.controls if isinstance(c, ft.IconButton))
    return control


def _botones(vista, codigo) -> list[ft.IconButton]:
    """Los íconos de acción del ítem `codigo`, en el modo vigente."""
    if vista._modo_vista_auditoria == "tarjetas":
        raiz = next(
            t for t in vista._vista_auditoria.content.controls[0].controls
            if any(codigo in txt for txt in _textos(t))
        )
    else:
        raiz = next(
            f for f in vista._dt_auditoria.rows
            if any(codigo in txt for txt in _textos(f))
        )
    # Un botón con atajo aparece dos veces en el recorrido (el `Stack` y el
    # `IconButton` de dentro): se cuenta una sola vez, por identidad.
    encontrados, vistos = [], set()
    for c in _controles(raiz):
        if isinstance(c, ft.Stack):
            boton = _icono_de(c)
        elif isinstance(c, ft.IconButton) and c.on_click:
            boton = c
        else:
            continue
        if id(boton) not in vistos:
            vistos.add(id(boton))
            encontrados.append(boton)
    return encontrados


# ─────────────────────────────────────────────────────────────────────────────
# Las cuatro acciones, y solo esas
# ─────────────────────────────────────────────────────────────────────────────
def test_las_acciones_son_solo_las_de_reposicion(vista):
    assert vista.ACCIONES_AUDITORIA == ("info", "historial", "editar", "proveedor")
    for accion in vista.ACCIONES_AUDITORIA:
        assert callable(vista._handlers_accion_auditoria()[accion])


@pytest.mark.parametrize("descartada", ["cobrar", "carrito", "borrar"])
def test_cobrar_carrito_y_borrar_no_existen_en_esta_lista(vista, descartada):
    """Descartadas por el usuario: no se vende desde una lista de reposición, y
    Borrar no estuvo entre las elegidas."""
    assert descartada not in vista.ACCIONES_AUDITORIA
    assert descartada not in vista._handlers_accion_auditoria()


def test_cada_fila_dibuja_los_cuatro_iconos(vista_modo):
    assert len(_botones(vista_modo, "AUD-001")) == 4


def test_los_iconos_entran_por_el_punto_de_entrada_unico(vista_modo, evento):
    """Es el mismo camino que recorren los atajos de teclado."""
    ejecutadas = []
    vista_modo.ejecutar_accion_auditoria = lambda a, c, ev=None: ejecutadas.append((a, c))
    vista_modo._cargar_filas_auditoria()

    for boton in _botones(vista_modo, "AUD-002"):
        boton.on_click(evento)

    assert ejecutadas == [(a, "AUD-002") for a in vista_modo.ACCIONES_AUDITORIA]


# ─────────────────────────────────────────────────────────────────────────────
# El punto de entrada revalida y devuelve False cuando no aplica
# ─────────────────────────────────────────────────────────────────────────────
def test_una_accion_desconocida_falla_ruidosamente(vista):
    with pytest.raises(ValueError):
        vista.ejecutar_accion_auditoria("teletransportar", "AUD-001", None)


def test_sin_codigo_no_se_acciona_nada(vista, evento):
    assert vista.ejecutar_accion_auditoria("info", "", evento) is False
    assert vista.ejecutar_accion_auditoria("info", None, evento) is False


def test_un_vendedor_no_puede_accionar_la_auditoria(datos, pagina):
    """ERS 3.6: el panel entero es admin/gerencia, así que la guarda también
    vale para quien entre por código o por teclado y no por los íconos."""
    from ui.views.dashboard_view import DashboardView

    v = DashboardView(user_info={"username": "tester", "role": "vendedor"})
    v.get_current_page = lambda e=None: pagina

    assert v.es_admin is False
    assert v.ejecutar_accion_auditoria("info", "AUD-001", EventoFalso(pagina)) is False
    assert pagina.dialogos == []


# ─────────────────────────────────────────────────────────────────────────────
# Ver detalle, Historial y Editar: los modales del catálogo, sin duplicarlos
# ─────────────────────────────────────────────────────────────────────────────
def test_ver_detalle_abre_la_ficha_del_producto(vista, evento, pagina):
    assert vista.ejecutar_accion_auditoria("info", "AUD-001", evento) is True

    assert pagina.dialogos, "no se abrió ningún modal"
    assert "AUD-001" in " ".join(_textos(pagina.dialogos[-1]))


def test_el_historial_abre_el_historial_clinico(vista, evento, pagina):
    assert vista.ejecutar_accion_auditoria("historial", "AUD-001", evento) is True

    assert any("Historial Clínico" in t for t in _textos(pagina.dialogos[-1]))


def test_editar_abre_el_formulario_del_producto(vista, evento):
    assert vista.ejecutar_accion_auditoria("editar", "AUD-002", evento) is True

    assert vista._vista_inventario_auxiliar._editing_codigo == "AUD-002"


def test_la_vista_auxiliar_se_crea_una_sola_vez(vista, evento):
    vista.ejecutar_accion_auditoria("info", "AUD-001", evento)
    primera = vista._vista_inventario_auxiliar

    vista.ejecutar_accion_auditoria("editar", "AUD-001", evento)

    assert vista._vista_inventario_auxiliar is primera


def test_la_vista_auxiliar_comparte_el_registro_de_foco(vista, evento):
    """Sin esto, al escribir en el formulario de edición las flechas
    desplazarían el Inicio que está detrás."""
    auxiliar = vista._vista_inventario_para_modales(evento)

    assert auxiliar._teclado.foco is vista._teclado.foco


def test_guardar_el_formulario_refresca_la_lista_de_auditoria(vista, evento):
    """La lista que tiene que enterarse de que el stock cambió es esta, no el
    catálogo que no está en pantalla."""
    from services.inventario_service import actualizar_producto

    auxiliar = vista._vista_inventario_para_modales(evento)
    assert "AUD-001" in vista._alertas_en_pantalla

    actualizar_producto(
        codigo="AUD-001", referencia="REF-AUD-001",
        descripcion_general="Producto critico AUD-001",
        departamento="Ferretería", existencia=500.0, precio_dolares=2.0,
        costo_usd_efectivo=1.0, rol_usuario="administrador",
    )
    auxiliar._refrescar_tabla(evento)

    assert "AUD-001" not in vista._alertas_en_pantalla


def test_la_vista_auxiliar_no_le_roba_el_teclado_al_dashboard(vista, pagina, evento):
    """Su cuerpo nunca se monta, así que su `ControlTeclado` no se instala."""
    vista._vista_inventario_para_modales(evento)

    assert pagina.on_keyboard_event is vista._teclado.handler


# ─────────────────────────────────────────────────────────────────────────────
# Contactar proveedor
# ─────────────────────────────────────────────────────────────────────────────
def test_contactar_proveedor_muestra_el_telefono_y_el_correo(vista, evento, pagina):
    assert vista.ejecutar_accion_auditoria("proveedor", "AUD-001", evento) is True

    texto = " ".join(_textos(pagina.dialogos[-1]))
    assert "Acme C.A." in texto
    assert "0412-1112233" in texto
    assert "ventas@acme.com" in texto


def test_el_contacto_nombra_el_producto_a_reponer_y_su_existencia(vista, evento, pagina):
    vista.ejecutar_accion_auditoria("proveedor", "AUD-001", evento)

    texto = " ".join(_textos(pagina.dialogos[-1]))
    assert "Corto AUD-001" in texto
    assert "quedan 0" in texto


def test_el_producto_sin_proveedor_lo_dice_en_vez_de_mentir(vista, evento, pagina):
    vista.ejecutar_accion_auditoria("proveedor", "AUD-003", evento)

    texto = " ".join(_textos(pagina.dialogos[-1]))
    assert "Sin Proveedor Asignado" in texto
    assert "Sin datos de contacto" in texto


def test_el_dialogo_de_contactos_se_cierra_por_su_boton(vista, evento, pagina):
    vista.ejecutar_accion_auditoria("proveedor", "AUD-001", evento)
    dialogo = pagina.dialogos[-1]

    dialogo.actions[0].on_click(evento)

    assert dialogo.open is False
    assert dialogo not in vista._dialogos_inicio


def test_el_dialogo_de_contactos_se_sincroniza_si_flet_lo_descarta(vista, evento, pagina):
    """Un descarte que la vista no registre deja un fantasma en su pila, y el
    siguiente cierre descartaría el diálogo equivocado."""
    vista.ejecutar_accion_auditoria("proveedor", "AUD-001", evento)
    dialogo = pagina.dialogos[-1]

    dialogo.on_dismiss(evento)

    assert dialogo not in vista._dialogos_inicio


# ─────────────────────────────────────────────────────────────────────────────
# Etiquetas de los atajos sobre los íconos
# ─────────────────────────────────────────────────────────────────────────────
def test_los_iconos_con_tecla_la_llevan_dibujada_encima(vista_modo):
    """El PDF pide que los atajos estén a la vista "para siempre ser
    consciente de ellos": un tooltip hay que ir a buscarlo con el mouse."""
    etiquetas = {
        c.value for c in _controles(vista_modo._vista_auditoria)
        if isinstance(c, ft.Text) and c.value in ATAJOS_ITEM
    }

    assert etiquetas == {"F1", "F4", "F5"}


def test_contactar_proveedor_no_promete_un_atajo_que_no_tiene(vista_modo):
    """No existe en el mapeo canónico y no se le inventó una tecla: reutilizar
    F2/F3/F6 rompería la regla de que la misma tecla hace lo mismo en todas las
    listas."""
    tooltips = [
        c.tooltip for c in _controles(vista_modo._vista_auditoria)
        if isinstance(c, ft.IconButton) and c.tooltip
    ]
    contactar = [t for t in tooltips if "Contactar proveedor" in t]

    assert contactar, "no se encontró el ícono de contactar proveedor"
    assert all("(F" not in t for t in contactar)


def test_los_tooltips_confirman_el_atajo(vista_modo):
    tooltips = [
        c.tooltip for c in _controles(vista_modo._vista_auditoria)
        if isinstance(c, ft.IconButton) and c.tooltip
    ]

    assert any(t == "Ver detalle del ítem (F1)" for t in tooltips)
    assert any(t == "Historial Clínico (F4)" for t in tooltips)
    assert any(t == "Editar (F5)" for t in tooltips)
