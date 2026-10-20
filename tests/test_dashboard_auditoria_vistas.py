"""Modos de vista y navegación con botones de la Auditoría Preventiva.

Pedido del usuario del proyecto: "en Auditoría Preventiva hay que hacer lo
mismo que en las otras vistas para poder tener distintos tipos de vistas ... y
navegación con botones". Antes era una tabla pasiva de formato único.

Mismo enfoque que `test_dashboard_inicio.py`: se construye el árbol de
controles SIN página de Flet (doble headless) y se recorre, porque
`BaseView.setup_layout()` atrapa cualquier excepción y la convierte en el panel
"Error al Cargar Módulo" — un fallo de construcción sería silencioso.
"""
import flet as ft
import pytest

from services.inventario_service import crear_producto

ATRIBUTOS_HIJOS = (
    "controls", "content", "actions", "title", "rows", "columns", "cells", "label",
)

DESCRIPCION_LARGA = (
    "Tornillo autoperforante de acero galvanizado cabeza hexagonal de una "
    "pulgada y media para lamina metalica calibre veinticuatro"
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


class EventoSegmentado:
    """Evento mínimo de `ft.SegmentedButton` (headless, sin `page`)."""

    def __init__(self, seleccion):
        self.control = type("C", (), {"selected": {seleccion}})()
        self.page = None


@pytest.fixture
def productos(db_temporal):
    """Dos productos en cero: disparan la auditoría por umbral global."""
    crear_producto(
        codigo="AUD-001", referencia="REF-1",
        descripcion_general=DESCRIPCION_LARGA,
        departamento="Ferretería", marca="Acme",
        precio_dolares=1.5, existencia=0.0,
        nombre_referencia_corto="Tornillo AP 1/4",
        costo_usd_efectivo=None, rol_usuario="administrador",
    )
    crear_producto(
        codigo="AUD-002", referencia="REF-2",
        descripcion_general="Tuerca hexagonal de media pulgada",
        departamento="Ferretería", marca="Globex",
        precio_dolares=0.5, existencia=1.0,
        nombre_referencia_corto="Tuerca 1/2",
        costo_usd_efectivo=0.2, rol_usuario="administrador",
    )
    return ["AUD-001", "AUD-002"]


@pytest.fixture
def vista(productos):
    from ui.views.dashboard_view import DashboardView

    v = DashboardView(user_info={"username": "tester", "role": "administrador"})
    v.build_data_sections()
    return v


MODOS = ["separado", "agrupado", "tarjetas"]


# ─── El selector existe y arranca donde debe ─────────────────────────────────

def test_el_modo_por_defecto_es_el_formato_con_el_que_ya_se_mostraba(vista):
    """Arrancar en otro formato le cambiaría la pantalla de la mañana a quien
    no pidió nada."""
    assert vista._modo_vista_auditoria == "agrupado"
    assert vista._btn_modo_vista_auditoria.selected == ["agrupado"]


def test_el_selector_ofrece_los_tres_formatos(vista):
    valores = [s.value for s in vista._btn_modo_vista_auditoria.segments]

    assert valores == MODOS
    assert list(vista.MODOS_VISTA_AUDITORIA) == MODOS


def test_los_segmentos_llevan_etiqueta_visible(vista):
    """Un selector de tres iconos sin texto no se descubre."""
    etiquetas = _textos(ft.Row(controls=list(vista._btn_modo_vista_auditoria.segments)))

    assert "Separado" in etiquetas
    assert "Agrupado" in etiquetas
    assert "Tarjetas" in etiquetas


# ─── Los tres modos se renderizan ────────────────────────────────────────────

@pytest.mark.parametrize("modo", MODOS)
def test_cada_modo_renderiza_los_dos_items(vista, modo):
    vista._modo_vista_auditoria = modo
    vista._cargar_filas_auditoria()

    textos = " ".join(_textos(vista._vista_auditoria))
    assert "AUD-001" in textos
    assert "AUD-002" in textos


@pytest.mark.parametrize("modo", MODOS)
def test_cada_modo_indexa_lo_que_hay_en_pantalla(vista, modo):
    """El índice por código es lo que permite que una acción invocada por
    nombre (un atajo no tiene fila) resuelva el producto."""
    vista._modo_vista_auditoria = modo
    vista._cargar_filas_auditoria()

    assert set(vista._alertas_en_pantalla) == {"AUD-001", "AUD-002"}


def test_el_selector_cambia_de_modo_y_recarga(vista):
    vista._handle_cambio_modo_vista_auditoria(EventoSegmentado("tarjetas"))

    assert vista._modo_vista_auditoria == "tarjetas"
    assert isinstance(vista._vista_auditoria.content, ft.Column)


def test_el_modo_sobrevive_al_cambio_de_seccion(vista):
    """El Dashboard es una sola instancia durante la sesión: volver al Inicio
    no puede devolver al usuario a un formato que ya había cambiado."""
    vista._handle_cambio_modo_vista_auditoria(EventoSegmentado("separado"))

    vista.current_section = "Ventas"
    vista.get_body()
    vista.current_section = "Inicio"
    vista.get_body()

    assert vista._modo_vista_auditoria == "separado"
    assert vista._btn_modo_vista_auditoria.selected == ["separado"]


# ─── Modo separado: una columna por campo ────────────────────────────────────

def test_el_modo_separado_pone_una_columna_por_campo(vista):
    vista._modo_vista_auditoria = "separado"
    vista._cargar_filas_auditoria()

    encabezados = [c.label.value for c in vista._dt_auditoria.columns]
    for esperado in ("Código", "Referencia", "Descripción", "Stock Actual", "Mínimo", "Proveedor"):
        assert esperado in encabezados


def test_en_el_modo_separado_cada_fila_tiene_una_celda_por_columna(vista):
    vista._modo_vista_auditoria = "separado"
    vista._cargar_filas_auditoria()

    for fila in vista._dt_auditoria.rows:
        assert len(fila.cells) == len(vista._dt_auditoria.columns)


def test_el_selector_de_columnas_oculta_una_columna(vista):
    vista._modo_vista_auditoria = "separado"
    vista._cargar_filas_auditoria()

    vista._toggle_columna_auditoria("marca")

    assert vista._columnas_visibles_auditoria["marca"] is False
    assert "Marca" not in [c.label.value for c in vista._dt_auditoria.columns]


def test_no_se_puede_dejar_la_tabla_sin_ninguna_columna(vista):
    """Una tabla de cero columnas no es una vista, es una pantalla en blanco."""
    vista._modo_vista_auditoria = "separado"
    vista._cargar_filas_auditoria()
    for key in vista._columnas_ocultables_auditoria[:-1]:
        vista._toggle_columna_auditoria(key)

    ultima = vista._columnas_ocultables_auditoria[-1]
    vista._toggle_columna_auditoria(ultima)

    assert vista._columnas_visibles_auditoria[ultima] is True


def test_el_selector_de_columnas_solo_se_ve_en_el_modo_separado(vista):
    for modo, visible in (("separado", True), ("agrupado", False), ("tarjetas", False)):
        vista._modo_vista_auditoria = modo
        vista._cargar_filas_auditoria()
        assert vista._btn_columnas_auditoria.visible is visible


# ─── Modo agrupado: dos líneas y sin deslizable horizontal ───────────────────

def test_el_modo_agrupado_agrupa_varios_datos_por_celda(vista):
    vista._modo_vista_auditoria = "agrupado"
    vista._cargar_filas_auditoria()

    textos = " ".join(_textos(vista._dt_auditoria))
    assert "Cód: AUD-001" in textos
    assert "Ref: REF-1" in textos
    assert "Corto: Tornillo AP 1/4" in textos


def test_la_descripcion_agrupada_admite_dos_lineas(vista):
    vista._modo_vista_auditoria = "agrupado"
    vista._cargar_filas_auditoria()

    descripciones = [
        c for c in _controles(vista._dt_auditoria)
        if isinstance(c, ft.Text) and c.value == DESCRIPCION_LARGA
    ]
    assert descripciones, "la lista agrupada no mostró la descripción general"
    for texto in descripciones:
        assert texto.max_lines == 2
        assert texto.overflow == ft.TextOverflow.ELLIPSIS


def test_el_modo_agrupado_entra_en_una_pantalla_normal(vista):
    """La condición de la especificación: sin deslizable horizontal. Los
    anchos fijos de las celdas no pueden pasarse del ancho útil (~1120 px)."""
    vista._modo_vista_auditoria = "agrupado"
    vista._cargar_filas_auditoria()

    fila = vista._dt_auditoria.rows[0]
    anchos = [
        celda.content.width or 0 for celda in fila.cells
        if isinstance(celda.content, ft.Container)
    ]
    assert sum(anchos) <= 1120, f"la fila agrupada mide {sum(anchos)} px"


# ─── Modo tarjetas ───────────────────────────────────────────────────────────

def test_el_modo_tarjetas_dibuja_una_tarjeta_por_item(vista):
    vista._modo_vista_auditoria = "tarjetas"
    vista._cargar_filas_auditoria()

    tarjetas = vista._vista_auditoria.content.controls[0].controls
    assert len(tarjetas) == 2
    assert all(t.width == 320 for t in tarjetas)


def test_en_tarjetas_no_hay_tabla_ni_flechas_horizontales(vista):
    """Sin tabla no hay eje horizontal: un cluster que no desplaza nada es
    peor que no tenerlo."""
    vista._modo_vista_auditoria = "tarjetas"
    vista._cargar_filas_auditoria()

    assert vista._dt_auditoria.rows == []
    assert vista._nav_h_auditoria.visible is False
    assert vista._nav_v_auditoria.visible is False


# ─── Navegación con botones ──────────────────────────────────────────────────

@pytest.mark.parametrize("modo", ["separado", "agrupado"])
def test_los_dos_clusters_de_flechas_estan_en_las_vistas_con_tabla(vista, modo):
    vista._modo_vista_auditoria = modo
    vista._cargar_filas_auditoria()

    assert vista._nav_h_auditoria.visible is True
    assert vista._nav_v_auditoria.visible is True
    # Cuatro botones por cluster: extremo, un paso, un paso, extremo.
    assert len(vista._nav_h_auditoria.content.controls) == 4
    assert len(vista._nav_v_auditoria.content.controls) == 4
    assert all(b.on_click for b in vista._nav_h_auditoria.content.controls)


def test_el_cluster_vertical_flota_sin_tapar_la_ultima_fila(vista):
    """Se reserva holgura al pie: el cluster se dibujaba encima del texto."""
    vista._modo_vista_auditoria = "agrupado"
    vista._cargar_filas_auditoria()

    assert isinstance(vista._vista_auditoria.content, ft.Stack)
    assert vista._tabla_auditoria_con_holgura.padding.bottom == vista._HOLGURA_NAV_FLOTANTE


def test_la_lista_de_auditoria_es_la_duena_del_eje_horizontal(vista):
    """Hay dos tablas anchas en el Inicio y una sola pulsación no puede
    desplazar las dos: las flechas son de la lista con la que se trabaja."""
    vista.current_section = "Inicio"
    vista.get_body()

    assert vista._scroll_inicio_h is vista._tabla_auditoria_row


def test_un_solo_dueno_por_eje_en_la_lista_de_auditoria(vista):
    """La Row desplaza en horizontal; la Column intermedia no desplaza nada."""
    assert vista._tabla_auditoria_row.scroll == ft.ScrollMode.AUTO
    assert vista._tabla_auditoria_col.scroll is None


# ─── Lista vacía ─────────────────────────────────────────────────────────────

def test_sin_nada_que_reponer_no_se_dibuja_una_lista_vacia(db_temporal):
    from ui.views.dashboard_view import DashboardView

    v = DashboardView(user_info={"username": "tester", "role": "administrador"})
    v.build_data_sections()

    textos = " ".join(_textos(v._vista_auditoria))
    assert "sobre el stock mínimo" in textos
    assert v._nav_h_auditoria.visible is False
