"""Densidad de la previsualización antes de guardar un ítem (paso 3).

Cambio 3 de la actualización de octubre 2026: la separación entre casillas
desperdiciaba la ventana y obligaba a desplazarse. El criterio de aceptación es
que TODA la información se vea en una sola ventana SIN deslizable, con una sola
excepción: "Descripción General", que alberga textos largos (unos 300
caracteres como mínimo) y conserva el espacio que necesita.

Lo que estas pruebas NO deben dejar revertir: el espaciado grande se había
introducido para arreglar un desborde de la casilla de descripción, así que
compactar no puede devolver el texto largo a desbordarse (eso lo cubre también
`test_inventario_form_estado.py`, y aquí se vuelve a afirmar sobre el resumen
compacto).
"""
import flet as ft
import pytest


@pytest.fixture
def vista(db_temporal):
    from ui.views.inventario_view import InventarioView

    v = InventarioView(es_admin=True)
    v.get_body()
    return v


DATOS_COMPLETOS = {
    "codigo": "COMP-001",
    "referencia": "REF-COMP",
    "descripcion_general": "D" * 320,
    "departamento": "Herramientas",
    "sub_departamento": "Taladros",
    "marca": "Bosch",
    "existencia": "5",
    "alerta_stock_minimo": "2",
    "precio_dolares": "100",
    "precio_bcv": "110",
    "costo_usd_efectivo": "70",
    "costo_usd_bcv": "72",
    "proveedor_id": "1",
    "codigo_barras": "7591234567890",
    "nombre_referencia_corto": "Taladro Bosch",
}


def _contenedor_resumen(vista) -> ft.Container:
    return vista._dialog.content


def _filas(vista) -> list[ft.Row]:
    return _contenedor_resumen(vista).content.controls


def _fila(vista, etiqueta: str) -> ft.Row:
    for f in _filas(vista):
        if isinstance(f.controls[0], ft.Text) and f.controls[0].value.startswith(etiqueta):
            return f
    raise AssertionError(f"No se encontró la fila '{etiqueta}' en el resumen")


def _scrolls_del_subarbol(control) -> list:
    """Recorre el contenido del diálogo juntando todos los `scroll` declarados."""
    encontrados = []
    pendientes = [control]
    while pendientes:
        c = pendientes.pop()
        if c is None or isinstance(c, str):
            continue
        encontrados.append(getattr(c, "scroll", None))
        hijos = list(getattr(c, "controls", None) or [])
        contenido = getattr(c, "content", None)
        if contenido is not None:
            hijos.append(contenido)
        pendientes.extend(hijos)
    return encontrados


# ─────────────────────────────────────────────────────────────────────────────
# Una sola ventana, sin deslizable
# ─────────────────────────────────────────────────────────────────────────────
def test_el_resumen_del_paso3_no_declara_ningun_scroll(vista):
    vista._mostrar_paso3_confirmacion(None, dict(DATOS_COMPLETOS))

    assert all(s is None for s in _scrolls_del_subarbol(_contenedor_resumen(vista))), (
        "el paso 3 debe mostrarse completo en una sola ventana, sin deslizable"
    )


def test_el_contenedor_del_resumen_no_tiene_alto_fijo_que_lo_recorte(vista):
    vista._mostrar_paso3_confirmacion(None, dict(DATOS_COMPLETOS))

    assert _contenedor_resumen(vista).height is None
    assert _contenedor_resumen(vista).width, "el ancho sí se acota (es lo que envuelve el texto largo)"


def test_las_casillas_van_pegadas_sin_separacion_entre_ellas(vista):
    vista._mostrar_paso3_confirmacion(None, dict(DATOS_COMPLETOS))

    assert _contenedor_resumen(vista).content.spacing == 0


def test_el_resumen_completo_cabe_en_una_ventana_de_escritorio(vista):
    """Estimación del alto: filas de una línea + el bloque de descripción. Con
    los 15 campos del formulario administrativo el resumen debe seguir entrando
    en una ventana modal normal; si alguien vuelve a inflar el espaciado o a
    reservar alto en más casillas, esta cuenta se dispara."""
    vista._mostrar_paso3_confirmacion(None, dict(DATOS_COMPLETOS))

    alto_linea = 22  # una línea de texto tamaño 12 con su interlineado
    alto_estimado = 0
    for fila in _filas(vista):
        contenedor = fila.controls[1]
        alto_estimado += contenedor.height or alto_linea

    assert len(_filas(vista)) == len(DATOS_COMPLETOS), "deben resumirse todos los campos enviados"
    assert alto_estimado <= 500, f"el resumen pide {alto_estimado}px de alto"


# ─────────────────────────────────────────────────────────────────────────────
# La excepción: "Descripción General"
# ─────────────────────────────────────────────────────────────────────────────
def test_la_descripcion_general_conserva_su_espacio(vista):
    vista._mostrar_paso3_confirmacion(None, dict(DATOS_COMPLETOS))

    contenedor = _fila(vista, "Descripción General").controls[1]

    assert contenedor.height, "la descripción es la única casilla con alto reservado"
    assert contenedor.height >= 90, "debe caber un texto de unos 300 caracteres"
    assert contenedor.content.max_lines >= 5


def test_el_texto_largo_de_la_descripcion_sigue_envolviendo_dentro_del_ancho(vista):
    """El espaciado grande existía para arreglar este desborde: compactar no
    puede devolver la descripción a crecer hacia la derecha del diálogo."""
    descripcion = "A" * 600
    datos = dict(DATOS_COMPLETOS, descripcion_general=descripcion)
    vista._mostrar_paso3_confirmacion(None, datos)

    contenedor = _fila(vista, "Descripción General").controls[1]
    texto = contenedor.content

    assert texto.value == descripcion
    assert contenedor.expand or contenedor.width
    assert texto.no_wrap is False
    assert texto.overflow in (ft.TextOverflow.ELLIPSIS, ft.TextOverflow.CLIP)


@pytest.mark.parametrize("etiqueta", ["Código", "Referencia", "Marca", "Nombre Corto"])
def test_las_demas_casillas_no_reservan_alto_extra(vista, etiqueta):
    vista._mostrar_paso3_confirmacion(None, dict(DATOS_COMPLETOS))

    contenedor = _fila(vista, etiqueta).controls[1]

    assert contenedor.height is None
    assert contenedor.content.max_lines == 1


def test_los_tres_botones_del_paso3_siguen_disponibles(vista):
    vista._mostrar_paso3_confirmacion(None, dict(DATOS_COMPLETOS))

    etiquetas = [
        (getattr(a, "text", None) or getattr(a, "content", None))
        for a in vista._dialog.actions
    ]
    textos = " ".join(t for t in etiquetas if isinstance(t, str)).lower()
    assert "cancelar" in textos and "editar" in textos and "guardar" in textos
