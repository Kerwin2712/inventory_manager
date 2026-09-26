"""Pruebas de `ui.components.producto_detalle_modal`.

Lo crítico es el GATING DE COSTOS: `costo_usd_efectivo` y `costo_usd_bcv` son
lo que le cuesta al negocio adquirir el producto y no deben aparecer nunca con
`es_admin=False`, ni siquiera si el diccionario los trae. Los tests recorren el
árbol de controles y verifican por etiqueta y por valor, no por confianza.
"""
import flet as ft
import pytest

from ui.components.producto_detalle_modal import (
    CAMPOS_DETALLE,
    MARCADOR_VACIO,
    campos_visibles,
    construir_modal_detalle_producto,
)

PRODUCTO_COMPLETO = {
    "codigo": "FER-001",
    "referencia": "REF-9988",
    "descripcion_general": "Taladro percutor industrial de 850W",
    "nombre_referencia_corto": "Taladro 850W",
    "codigo_barras": "7591234567890",
    "departamento": "Ferretería",
    "sub_departamento": "Herramientas Eléctricas",
    "marca": "Bosch",
    "existencia": 12.0,
    "alerta_stock_minimo": 3,
    "precio_dolares": 120.5,
    "precio_bcv": 128.0,
    "monto_bcv_bolivares": 9376.0,
    "costo_usd_efectivo": 78.25,
    "costo_usd_bcv": 80.0,
    "proveedor_id": 4,
    "created_at": "2026-01-15 09:12:00",
    "fecha_ultima_modificacion": "2026-02-02 17:40:00",
}

CLAVES_COSTO = ("costo_usd_efectivo", "costo_usd_bcv")
ETIQUETAS_COSTO = ("Costo USD (Efectivo)", "Costo USD (BCV)")


def _descendientes(control, _vistos=None):
    if _vistos is None:
        _vistos = set()
    if control is None or id(control) in _vistos:
        return
    _vistos.add(id(control))
    yield control
    hijos = []
    for attr in ("controls", "actions", "rows", "cells", "columns"):
        hijos.extend(getattr(control, attr, None) or [])
    for attr in ("content", "title", "label", "icon"):
        hijo = getattr(control, attr, None)
        if isinstance(hijo, ft.Control):
            hijos.append(hijo)
    for hijo in hijos:
        yield from _descendientes(hijo, _vistos)


def _etiqueta_accion(accion) -> str:
    """Etiqueta de un botón de `actions` (en Flet 0.86 el texto llega por
    `content` cuando se pasa como primer argumento posicional)."""
    texto = getattr(accion, "text", None) or getattr(accion, "content", None)
    return texto if isinstance(texto, str) else ""


def _textos(dlg: ft.AlertDialog) -> list[str]:
    return [c.value for c in _descendientes(dlg) if isinstance(c, ft.Text) and c.value]


def _filas(dlg: ft.AlertDialog) -> list[ft.Row]:
    return [f for f in dlg.content.content.controls if isinstance(f, ft.Row)]


def _valor_de(dlg: ft.AlertDialog, etiqueta: str) -> str:
    for fila in _filas(dlg):
        if fila.controls[0].value == f"{etiqueta}:":
            return fila.controls[1].content.value
    raise AssertionError(f"No se encontró la fila '{etiqueta}'")


def _etiquetas(dlg: ft.AlertDialog) -> list[str]:
    return [f.controls[0].value.rstrip(":") for f in _filas(dlg)]


# ─────────────────────────────────────────────────────────────────────────────
# 1. Construcción con datos completos y con datos faltantes
# ─────────────────────────────────────────────────────────────────────────────
def test_se_construye_para_un_producto_completo():
    dlg = construir_modal_detalle_producto(PRODUCTO_COMPLETO, es_admin=True)

    assert isinstance(dlg, ft.AlertDialog)
    assert dlg.modal is True
    etiquetas = _etiquetas(dlg)
    assert "Código" in etiquetas and "Departamento" in etiquetas
    assert _valor_de(dlg, "Sub-Departamento") == "Herramientas Eléctricas"
    assert _valor_de(dlg, "Marca") == "Bosch"
    assert MARCADOR_VACIO not in [_valor_de(dlg, et) for et in etiquetas]


def test_solo_se_renderizan_las_claves_presentes_en_el_diccionario():
    dlg = construir_modal_detalle_producto({"codigo": "X", "marca": "ACME"})

    assert _etiquetas(dlg) == ["Código", "Marca"]


def test_los_campos_vacios_muestran_el_marcador_de_no_llenado():
    dlg = construir_modal_detalle_producto({
        "codigo": "PAR-001",
        "referencia": "",
        "descripcion_general": "   ",
        "sub_departamento": None,
        "marca": "ACME",
    })

    assert _valor_de(dlg, "Referencia") == MARCADOR_VACIO
    assert _valor_de(dlg, "Descripción General") == MARCADOR_VACIO
    assert _valor_de(dlg, "Sub-Departamento") == MARCADOR_VACIO
    assert _valor_de(dlg, "Marca") == "ACME"


def test_una_existencia_en_cero_es_dato_y_no_marcador():
    """Un `0` numérico es información válida, no un campo sin llenar."""
    dlg = construir_modal_detalle_producto({"codigo": "Z", "existencia": 0.0})

    assert _valor_de(dlg, "Existencia") == "0"


def test_un_diccionario_vacio_no_rompe_el_modal():
    dlg = construir_modal_detalle_producto({})

    assert _filas(dlg) == []
    assert "Sin datos para mostrar." in _textos(dlg)


def test_los_montos_se_formatean_con_su_moneda():
    dlg = construir_modal_detalle_producto(PRODUCTO_COMPLETO, es_admin=True)

    assert _valor_de(dlg, "Precio USD (Efectivo)") == "$ 120.50"
    assert _valor_de(dlg, "Monto Bs (BCV)") == "Bs 9,376.00"
    assert _valor_de(dlg, "Costo USD (Efectivo)") == "$ 78.25"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Gating de costos por rol
# ─────────────────────────────────────────────────────────────────────────────
def test_sin_es_admin_ninguna_clave_de_costo_aparece_en_el_arbol():
    dlg = construir_modal_detalle_producto(PRODUCTO_COMPLETO, es_admin=False)

    arbol = " | ".join(_textos(dlg))
    for etiqueta in ETIQUETAS_COSTO:
        assert etiqueta not in arbol, f"'{etiqueta}' se filtró a un rol no admin"
    assert "78.25" not in arbol and "80.00" not in arbol
    assert _etiquetas(dlg).count("Precio USD (Efectivo)") == 1, "los precios sí se muestran"


def test_es_admin_falso_es_el_valor_por_defecto_fail_closed():
    dlg = construir_modal_detalle_producto(PRODUCTO_COMPLETO)

    for etiqueta in ETIQUETAS_COSTO:
        assert etiqueta not in _etiquetas(dlg)


def test_con_es_admin_los_costos_si_se_renderizan():
    dlg = construir_modal_detalle_producto(PRODUCTO_COMPLETO, es_admin=True)

    for etiqueta in ETIQUETAS_COSTO:
        assert etiqueta in _etiquetas(dlg)


def test_un_admin_sin_costos_en_el_dict_no_ve_filas_de_costo():
    sin_costos = {k: v for k, v in PRODUCTO_COMPLETO.items() if k not in CLAVES_COSTO}

    dlg = construir_modal_detalle_producto(sin_costos, es_admin=True)

    for etiqueta in ETIQUETAS_COSTO:
        assert etiqueta not in _etiquetas(dlg)


def test_campos_visibles_es_la_unica_fuente_del_gating():
    assert [c for _, c in campos_visibles(PRODUCTO_COMPLETO, es_admin=False) if c in CLAVES_COSTO] == []
    assert [c for _, c in campos_visibles(PRODUCTO_COMPLETO, es_admin=True) if c in CLAVES_COSTO] == list(CLAVES_COSTO)
    # La especificación declarativa marca exactamente esas dos claves.
    assert tuple(c for _, c, solo_admin in CAMPOS_DETALLE if solo_admin) == CLAVES_COSTO


# ─────────────────────────────────────────────────────────────────────────────
# 3. Sin desbordamientos: texto acotado y un solo scroll
# ─────────────────────────────────────────────────────────────────────────────
def test_una_descripcion_de_600_caracteres_queda_acotada():
    descripcion = "A" * 600
    dlg = construir_modal_detalle_producto({
        "codigo": "LARGO-001",
        "descripcion_general": descripcion,
        "referencia": "R" * 300,
        "nombre_referencia_corto": "N" * 300,
    })

    fila = next(f for f in _filas(dlg) if f.controls[0].value == "Descripción General:")
    contenedor, texto = fila.controls[1], fila.controls[1].content

    assert texto.value == descripcion
    assert isinstance(contenedor, ft.Container)
    assert contenedor.expand or contenedor.width, "el valor necesita un ancho delimitado"
    assert texto.no_wrap is False, "debe envolver en varias líneas"
    assert texto.max_lines and texto.max_lines <= 6
    assert texto.overflow == ft.TextOverflow.ELLIPSIS


def test_todas_las_filas_acotan_su_valor():
    dlg = construir_modal_detalle_producto(PRODUCTO_COMPLETO, es_admin=True)

    for fila in _filas(dlg):
        etiqueta, valor = fila.controls[0], fila.controls[1]
        assert etiqueta.width, "la etiqueta conserva su ancho fijo"
        assert isinstance(valor, ft.Container) and (valor.expand or valor.width)
        assert valor.content.no_wrap is False
        assert valor.content.max_lines


def test_el_contenido_tiene_un_unico_scroll_vertical():
    dlg = construir_modal_detalle_producto(PRODUCTO_COMPLETO, es_admin=True)
    contenedor = dlg.content
    columna = contenedor.content

    assert isinstance(columna, ft.Column)
    assert columna.scroll == ft.ScrollMode.AUTO
    assert contenedor.height, "el scroll necesita un alto acotado dentro del diálogo"
    # Ninguna fila anida otro scroll que compita por el gesto.
    for control in _descendientes(columna):
        if control is columna:
            continue
        assert getattr(control, "scroll", None) is None


def test_el_titulo_no_desborda_con_una_descripcion_larga():
    dlg = construir_modal_detalle_producto(
        {"codigo": "T-1", "descripcion_general": "D" * 400}
    )

    contenedor = dlg.title.controls[-1]
    assert contenedor.expand
    assert contenedor.content.max_lines == 1
    assert contenedor.content.overflow == ft.TextOverflow.ELLIPSIS


# ─────────────────────────────────────────────────────────────────────────────
# 4. Paleta y acciones
# ─────────────────────────────────────────────────────────────────────────────
def test_la_paleta_se_recibe_por_parametro_y_admite_claves_parciales():
    dlg = construir_modal_detalle_producto(
        {"codigo": "P-1"}, paleta={"fondo": "#FFFFFF", "texto": "#000000"}
    )

    assert dlg.bgcolor == "#FFFFFF"
    assert _filas(dlg)[0].controls[1].content.color == "#000000"


def test_sin_on_editar_no_se_dibuja_el_boton_de_editar():
    dlg = construir_modal_detalle_producto({"codigo": "P-1"})

    assert [_etiqueta_accion(a) for a in dlg.actions] == ["Cerrar"]


def test_los_callbacks_de_cerrar_y_editar_se_cablean():
    llamadas = []
    dlg = construir_modal_detalle_producto(
        {"codigo": "P-1"},
        on_cerrar=lambda e: llamadas.append("cerrar"),
        on_editar=lambda e: llamadas.append("editar"),
    )

    for accion in dlg.actions:
        accion.on_click(None)

    assert llamadas == ["editar", "cerrar"]


# ─────────────────────────────────────────────────────────────────────────────
# 5. Cableado en `InventarioView`
# ─────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def producto(db_temporal):
    from services.inventario_service import crear_producto

    crear_producto(
        codigo="INV-001", referencia="REF-INV",
        descripcion_general="Cable THW calibre 12",
        departamento="Electricidad", sub_departamento="Cables",
        marca="Cabel", precio_dolares=1.2, precio_bcv=1.3, existencia=50,
        costo_usd_efectivo=0.8, costo_usd_bcv=0.85,
        rol_usuario="administrador",
    )
    return "INV-001"


def _vista(es_admin: bool, rol: str | None):
    from ui.views.inventario_view import InventarioView

    v = InventarioView(es_admin=es_admin, rol_usuario=rol)
    v.get_body()
    return v


def test_el_inventario_abre_el_modal_desde_una_fila(producto):
    vista = _vista(True, "administrador")

    vista._abrir_modal_detalle({"codigo": producto}, None)

    assert len(vista._dialog_stack) == 1
    assert _valor_de(vista._dialog, "Código") == producto
    assert _valor_de(vista._dialog, "Sub-Departamento") == "Cables"


def test_un_vendedor_no_ve_los_costos_en_el_modal_del_inventario(producto):
    """Doble barrera: el servicio no los devuelve para ese rol y el componente
    tampoco los renderizaría."""
    vista = _vista(False, "vendedor")

    vista._abrir_modal_detalle({"codigo": producto}, None)

    arbol = " | ".join(_textos(vista._dialog))
    for etiqueta in ETIQUETAS_COSTO:
        assert etiqueta not in arbol
    assert "0.80" not in arbol


def test_un_administrador_si_ve_los_costos_en_el_modal_del_inventario(producto):
    vista = _vista(True, "administrador")

    vista._abrir_modal_detalle({"codigo": producto}, None)

    assert _valor_de(vista._dialog, "Costo USD (Efectivo)") == "$ 0.80"


def test_el_modal_usa_la_pila_de_dialogos_de_la_vista(producto):
    vista = _vista(True, "administrador")
    vista._abrir_modal_detalle({"codigo": producto}, None)
    dlg = vista._dialog

    next(a for a in dlg.actions if _etiqueta_accion(a) == "Cerrar").on_click(None)

    assert vista._dialog_stack == []
    assert dlg.open is False


def test_editar_desde_el_modal_abre_el_formulario_de_edicion(producto):
    vista = _vista(True, "administrador")
    vista._abrir_modal_detalle({"codigo": producto}, None)
    dlg = vista._dialog

    next(a for a in dlg.actions if _etiqueta_accion(a) == "Editar").on_click(None)

    assert dlg.open is False
    assert vista._editing_codigo == producto
    assert vista._dialog is not dlg


def test_cada_fila_y_cada_tarjeta_ofrecen_el_acceso_al_detalle(producto):
    """El botón de detalle existe en los tres modos de vista del catálogo."""
    for modo in ("separado", "agrupado", "tarjetas"):
        vista = _vista(True, "administrador")
        vista._modo_vista = modo
        vista._cargar_filas()

        tooltips = [
            c.tooltip for c in _descendientes(vista._vista_container)
            if getattr(c, "tooltip", None)
        ]
        assert "Ver detalle del ítem" in tooltips, f"falta en el modo '{modo}'"
