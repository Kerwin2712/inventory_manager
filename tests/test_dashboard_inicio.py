"""Área de Inicio del Dashboard (especificación 17/10/2026).

Mismo enfoque que `test_dashboard_secciones.py`: se construye el árbol de
controles de la vista SIN página de Flet (doble headless) y se recorre, porque
`BaseView.setup_layout()` atrapa cualquier excepción y la convierte en el panel
"Error al Cargar Módulo" — un fallo de construcción sería silencioso.

El recorrido baja también por `rows`/`columns`/`cells`, que es donde viven las
celdas de un `DataTable`.
"""
import flet as ft
import pytest

from services.inventario_service import crear_producto

ATRIBUTOS_HIJOS = ("controls", "content", "actions", "title", "rows", "columns", "cells", "label")

DESCRIPCION_LARGA = (
    "Tornillo autoperforante de acero galvanizado cabeza hexagonal de una "
    "pulgada y media para lamina metalica calibre veinticuatro"
)


def _controles(control):
    """Aplana el árbol de controles de una vista (incluidas celdas de tabla)."""
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


@pytest.fixture
def vista(db_temporal):
    from ui.views.dashboard_view import DashboardView

    return DashboardView(user_info={"username": "tester", "role": "administrador"})


@pytest.fixture
def producto_critico(db_temporal):
    """Producto en cero con descripción larga: dispara la Auditoría Preventiva
    y obliga a la celda a usar la segunda línea."""
    return crear_producto(
        codigo="TOR-001",
        referencia="REF-9988",
        descripcion_general=DESCRIPCION_LARGA,
        departamento="Ferretería",
        marca="Acme",
        precio_dolares=1.5,
        existencia=0.0,
        nombre_referencia_corto="Tornillo AP 1/4",
        costo_usd_efectivo=None,
        rol_usuario="administrador",
    )


# ─── Cambios 1 y 2: Auditoría e Inteligencia a ancho completo ────────────────

def test_auditoria_e_inteligencia_van_a_ancho_completo_y_en_ese_orden(vista, producto_critico):
    seccion = vista.build_data_sections()

    assert isinstance(seccion, ft.ResponsiveRow)
    assert len(seccion.controls) == 2
    for tarjeta in seccion.controls:
        assert tarjeta.col == {"sm": 12, "lg": 12}, (
            "las tarjetas del Inicio deben ocupar la pantalla de izquierda a derecha"
        )

    textos_auditoria = _textos(seccion.controls[0])
    textos_inteligencia = _textos(seccion.controls[1])
    assert any("Auditoría Preventiva" in t for t in textos_auditoria)
    assert any("Inteligencia de Negocio" in t for t in textos_inteligencia)


def test_la_descripcion_de_auditoria_admite_dos_lineas(vista, producto_critico):
    """El modo agrupado del Inventario parte la descripción en dos líneas; la
    Auditoría ampliada debe comportarse igual (`max_lines=2` + elipsis)."""
    seccion = vista.build_data_sections()

    descripciones = [
        c for c in _controles(seccion)
        if isinstance(c, ft.Text) and c.value == DESCRIPCION_LARGA
    ]
    assert descripciones, "la Auditoría no mostró la descripción general del ítem"
    for texto in descripciones:
        assert texto.max_lines == 2
        assert texto.overflow == ft.TextOverflow.ELLIPSIS


def test_auditoria_muestra_la_informacion_completa_del_item(vista, producto_critico):
    """El ancho ganado se gasta en los datos que antes no cabían: código,
    referencia, nombre corto y departamento/marca."""
    textos = _textos(vista.build_data_sections())

    assert any("Cód: TOR-001" in t for t in textos)
    assert any("Ref: REF-9988" in t for t in textos)
    assert any("Tornillo AP 1/4" in t for t in textos)
    assert any(t == "Ferretería" for t in textos)
    assert any(t == "Acme" for t in textos)


# ─── Cambio 4: tarjeta de Tasa BCV en el Inicio ──────────────────────────────

def test_la_tarjeta_de_tasa_bcv_es_la_primera_de_la_fila(vista):
    """El cliente la pidió a la izquierda de las demás: es el primer dato que
    corrige cada mañana al abrir el programa."""
    fila = vista.build_metrics_cards()

    # Tasa de cambio + Ventas del Día + Productos en Stock + Alertas.
    assert len(fila.controls) == 4
    assert any("Tasa de Cambio BCV" in t for t in _textos(fila.controls[0]))


def test_la_tarjeta_de_tasa_abre_el_modal_global_de_actualizacion(vista):
    """Reutiliza `BaseView.mostrar_modal_tasa_bcv` en lugar de duplicar la caja
    de texto del panel de Inventario (la tarjeta debe ser pequeña)."""
    botones = [
        c for c in _controles(vista.build_tarjeta_tasa_bcv())
        if isinstance(c, ft.Button)
    ]

    assert len(botones) == 1
    assert botones[0].on_click == vista.mostrar_modal_tasa_bcv
    assert any("Actualizar Tasa" in t for t in _textos(botones[0]))


def test_la_tarjeta_de_tasa_refleja_el_estado_del_servicio_bcv(vista):
    """Misma vista que el panel de Inventario: la tasa vigente y su antigüedad."""
    from services.bcv_service import actualizar_tasa

    actualizar_tasa(732.48)
    textos = _textos(vista.build_tarjeta_tasa_bcv())

    assert any("732.48 Bs/$" in t for t in textos)
    assert any("Actualizado hace" in t for t in textos)


def test_sin_tasa_configurada_la_tarjeta_no_miente_con_un_cero(vista):
    textos = _textos(vista.build_tarjeta_tasa_bcv())

    assert any("Sin tasa" in t for t in textos)


# ─── Nueva función 1: ventana "Ventas Diarias" ───────────────────────────────

def _registrar_venta_de_hoy(codigos_y_cantidades, metodo_pago="Efectivo", referencia=None):
    """Venta con `fecha` explícita de hoy (hora local, el criterio con el que
    el reporte recorta el día)."""
    from datetime import datetime

    from core.database import get_connection

    fecha = datetime.now().replace(hour=12, minute=30, second=0, microsecond=0)
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO ventas (
                tipo_venta, total_usd, total_bcv, metodo_pago, fecha,
                referencia_pago, monto_cobrado
            ) VALUES ('Informal', 25.0, 27.5, ?, ?, ?, 25.0)
            """,
            (metodo_pago, fecha.strftime("%Y-%m-%d %H:%M:%S"), referencia),
        )
        venta_id = cursor.lastrowid
        for codigo, cantidad in codigos_y_cantidades:
            cursor.execute(
                """
                INSERT INTO ventas_detalle (
                    venta_id, producto_codigo, cantidad,
                    precio_unitario_usd, precio_unitario_bcv,
                    subtotal_usd, subtotal_bcv
                ) VALUES (?, ?, ?, 10.0, 11.0, ?, ?)
                """,
                (venta_id, codigo, cantidad, 10.0 * cantidad, 11.0 * cantidad),
            )
    return venta_id


def test_ventas_diarias_se_renderiza_entre_las_tarjetas_y_la_auditoria(vista, producto_critico):
    """Orden exigido: tarjetas · Ventas Diarias · Auditoría · Inteligencia."""
    vista.current_section = "Inicio"
    vista.setup_layout()

    titulos_de_seccion = [
        t for t in _textos(vista.controls[0])
        if t in ("Tasa de Cambio BCV", "Ventas Diarias", "Inteligencia de Negocio")
        or t.startswith("Auditoría Preventiva")
    ]

    assert titulos_de_seccion[0] == "Tasa de Cambio BCV"
    assert titulos_de_seccion[1] == "Ventas Diarias"
    assert titulos_de_seccion[2].startswith("Auditoría Preventiva")
    assert titulos_de_seccion[3] == "Inteligencia de Negocio"


def test_ventas_diarias_va_a_ancho_completo(vista):
    seccion = vista.build_ventas_diarias()

    assert isinstance(seccion, ft.ResponsiveRow)
    assert seccion.controls[0].col == {"sm": 12, "lg": 12}


def test_ventas_diarias_lista_las_casillas_de_la_especificacion(vista, producto_critico):
    _registrar_venta_de_hoy([("TOR-001", 3.0)], metodo_pago="Pago Móvil", referencia="0412555")

    textos = _textos(vista.build_ventas_diarias())

    for encabezado in (
        "Fecha y hora", "Descripción Corta", "Método de Pago",
        "Referencia de Pago", "Cantidad de Artículos", "Monto Total Pagado",
    ):
        assert encabezado in textos
    assert "Tornillo AP 1/4" in textos
    assert "Pago Móvil" in textos
    assert "0412555" in textos
    assert "3" in textos
    assert "1 venta(s) hoy" in textos


def test_la_descripcion_de_ventas_diarias_admite_dos_lineas(vista, producto_critico):
    """Un carrito con varios artículos concatena todos sus nombres cortos: en
    una sola línea quedarían casi todos fuera."""
    crear_producto(
        codigo="TUE-002", referencia="REF-2", descripcion_general="Tuerca hexagonal",
        departamento="Ferretería", precio_dolares=0.5, existencia=50.0,
        nombre_referencia_corto="Tuerca 1/4", costo_usd_efectivo=0.2,
        rol_usuario="administrador",
    )
    _registrar_venta_de_hoy([("TOR-001", 1.0), ("TUE-002", 2.0)])

    concatenadas = [
        c for c in _controles(vista.build_ventas_diarias())
        if isinstance(c, ft.Text) and c.value == "Tornillo AP 1/4, Tuerca 1/4"
    ]

    assert concatenadas, "la lista no concatenó los nombres cortos del carrito"
    assert concatenadas[0].max_lines == 2
    assert concatenadas[0].overflow == ft.TextOverflow.ELLIPSIS


def test_en_efectivo_la_referencia_se_muestra_con_un_guion(vista, producto_critico):
    _registrar_venta_de_hoy([("TOR-001", 1.0)], metodo_pago="Efectivo", referencia=None)

    textos = _textos(vista.build_ventas_diarias())

    assert "-" in textos


def test_sin_ventas_hoy_la_ventana_explica_que_no_hay_nada(vista):
    textos = _textos(vista.build_ventas_diarias())

    assert any("ninguna venta hoy" in t for t in textos)
    assert "0 venta(s) hoy" in textos
