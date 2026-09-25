"""Pruebas de regresión de la máquina de estados del formulario de Inventario
(`ui.views.inventario_view.InventarioView`).

Las vistas de este proyecto se pueden instanciar sin `page` (headless): los
accesos a `self.page` lanzan `RuntimeError`, que `_get_page`/`_safe_update` ya
capturan. Eso permite disparar los handlers reales de los diálogos con un
evento `None` y observar la pila `_dialog_stack`.

Cubre:
  1. El flujo de cancelación al crear un ítem (bug del código duplicado que
     dejaba al usuario atrapado en el paso 1).
  2. El acotado del texto largo en el resumen del paso 3 (desbordaba a la
     derecha del diálogo).
  3. La propiedad de scroll de la vista (un solo dueño del eje vertical).
"""
import asyncio

import flet as ft
import pytest


@pytest.fixture
def vista(db_temporal):
    """`InventarioView` headless sobre la base temporal, con la vista ya
    construida (`get_body`) para tener tabla, filtros y paneles listos."""
    from ui.views.inventario_view import InventarioView

    v = InventarioView(es_admin=True)
    v.get_body()
    return v


@pytest.fixture
def producto_existente(db_temporal):
    """Producto de prueba creado con el servicio real (para el duplicado)."""
    from services.inventario_service import crear_producto

    crear_producto(
        codigo="DUP-001",
        referencia="REF-DUP",
        descripcion_general="Taladro percutor industrial",
        departamento="Herramientas",
        marca="Bosch",
        precio_dolares=100.0,
        precio_bcv=110.0,
        existencia=5,
        # Con existencia, el costo es obligatorio (ERR_PROD_COSTO) y solo un
        # rol administrativo puede enviarlo (ERR_PROD_ROL).
        costo_usd_efectivo=70.0,
        rol_usuario="administrador",
    )
    return "DUP-001"


def _accion(dlg: ft.AlertDialog, etiqueta: str):
    """Localiza un botón del diálogo por el texto de su etiqueta."""
    for a in dlg.actions:
        texto = getattr(a, "text", None) or getattr(a, "content", None)
        if isinstance(texto, str) and etiqueta.lower() in texto.lower():
            return a
    raise AssertionError(f"No se encontró la acción '{etiqueta}' en el diálogo")


def _click(dlg: ft.AlertDialog, etiqueta: str, ev=None):
    """Dispara el `on_click` de un botón; si es `async def`, lo ejecuta."""
    resultado = _accion(dlg, etiqueta).on_click(ev)
    if asyncio.iscoroutine(resultado):
        asyncio.run(resultado)


def _campo_codigo(dlg_paso1: ft.AlertDialog) -> ft.TextField:
    return next(c for c in dlg_paso1.content.controls if isinstance(c, ft.TextField))


# ─────────────────────────────────────────────────────────────────────────────
# 1. Flujo de cancelación con código duplicado
# ─────────────────────────────────────────────────────────────────────────────
def test_abrir_flujo_ingreso_apila_el_paso1_con_estado_limpio(vista):
    vista._abrir_flujo_ingreso(None)

    assert len(vista._dialog_stack) == 1
    assert vista._dialog is vista._dialog_stack[-1]
    assert vista._form_codigo_verificado is False
    assert vista._editing_codigo is None


def test_codigo_duplicado_superpone_el_aviso_sin_perder_el_paso1(vista, producto_existente):
    vista._abrir_flujo_ingreso(None)
    dlg_paso1 = vista._dialog
    _campo_codigo(dlg_paso1).value = producto_existente

    _click(dlg_paso1, "Verificar")

    assert len(vista._dialog_stack) == 2, "el aviso debe apilarse SOBRE el paso 1"
    assert vista._dialog_stack[0] is dlg_paso1
    assert vista._dialog is not dlg_paso1
    assert vista._form_codigo_verificado is False


def test_tras_no_limpiar_codigo_el_paso1_vuelve_al_tope_y_el_campo_queda_vacio(vista, producto_existente):
    vista._abrir_flujo_ingreso(None)
    dlg_paso1 = vista._dialog
    campo = _campo_codigo(dlg_paso1)
    campo.value = producto_existente
    _click(dlg_paso1, "Verificar")
    dlg_dup = vista._dialog

    _click(dlg_dup, "No")

    assert vista._dialog_stack == [dlg_paso1], "el paso 1 debe quedar solo en el tope"
    assert dlg_paso1.open is not False, "el paso 1 no debe haberse cerrado"
    assert dlg_dup.open is False
    assert (campo.value or "") == ""


def test_cancelar_el_paso1_tras_el_aviso_de_duplicado_cierra_todo(vista, producto_existente):
    """Reproduce el bug: con una única referencia de diálogo, "Cancelar" del
    paso 1 volvía a cerrar el aviso ya cerrado y el paso 1 quedaba abierto."""
    vista._abrir_flujo_ingreso(None)
    dlg_paso1 = vista._dialog
    _campo_codigo(dlg_paso1).value = producto_existente
    _click(dlg_paso1, "Verificar")
    _click(vista._dialog, "No")

    _click(dlg_paso1, "Cancelar")

    assert dlg_paso1.open is False, "el paso 1 debe cerrarse al cancelar"
    assert vista._dialog_stack == []
    assert vista._dialog is None
    assert vista._form_codigo_verificado is False
    assert vista._editing_codigo is None


def test_tras_cancelar_un_nuevo_flujo_de_ingreso_arranca_limpio(vista, producto_existente):
    vista._abrir_flujo_ingreso(None)
    _campo_codigo(vista._dialog).value = producto_existente
    _click(vista._dialog_stack[0], "Verificar")
    _click(vista._dialog, "No")
    _click(vista._dialog_stack[0], "Cancelar")

    vista._abrir_flujo_ingreso(None)

    assert len(vista._dialog_stack) == 1
    assert (_campo_codigo(vista._dialog).value or "") == ""
    assert vista._form_codigo_verificado is False
    assert vista._editing_codigo is None


def test_codigo_libre_cierra_el_paso1_y_abre_el_paso2(vista):
    vista._abrir_flujo_ingreso(None)
    dlg_paso1 = vista._dialog
    _campo_codigo(dlg_paso1).value = "NUEVO-001"

    _click(dlg_paso1, "Verificar")

    assert vista._dialog_stack == [vista._dialog], "solo el paso 2 debe quedar abierto"
    assert vista._dialog is not dlg_paso1
    assert dlg_paso1.open is False
    assert vista._form_codigo_verificado is True


def test_cancelar_en_el_paso2_restablece_el_estado_del_formulario(vista):
    vista._abrir_flujo_ingreso(None)
    _campo_codigo(vista._dialog).value = "NUEVO-002"
    _click(vista._dialog, "Verificar")

    _click(vista._dialog, "Cancelar")

    assert vista._dialog_stack == []
    assert vista._form_codigo_verificado is False
    assert vista._editing_codigo is None


def test_cancelar_la_edicion_no_deja_editing_codigo_contaminado(vista, producto_existente):
    vista._abrir_flujo_edicion(producto_existente, None)
    assert vista._editing_codigo == producto_existente
    assert vista._form_codigo_verificado is True

    _click(vista._dialog, "Cancelar")

    assert vista._dialog_stack == []
    assert vista._editing_codigo is None
    assert vista._form_codigo_verificado is False


def test_cancelar_en_el_paso3_descarta_todo_el_flujo(vista):
    vista._mostrar_paso3_confirmacion(None, {"codigo": "NUEVO-003", "referencia": "R"})
    vista._form_codigo_verificado = True

    _click(vista._dialog, "Cancelar")

    assert vista._dialog_stack == []
    assert vista._form_codigo_verificado is False
    assert vista._editing_codigo is None


def test_ver_producto_desde_el_duplicado_deja_solo_el_formulario_de_edicion(vista, producto_existente):
    vista._abrir_flujo_ingreso(None)
    dlg_paso1 = vista._dialog
    _campo_codigo(dlg_paso1).value = producto_existente
    _click(dlg_paso1, "Verificar")

    _click(vista._dialog, "Sí")

    assert len(vista._dialog_stack) == 1, "paso 1 y aviso deben haberse cerrado"
    assert dlg_paso1.open is False
    assert vista._editing_codigo == producto_existente
    assert vista._form_codigo_verificado is True


# ─────────────────────────────────────────────────────────────────────────────
# 2. Acotado del texto largo en el resumen del paso 3
# ─────────────────────────────────────────────────────────────────────────────
def _filas_resumen(vista) -> list[ft.Row]:
    return vista._dialog.content.content.controls


def test_la_descripcion_extensa_del_resumen_envuelve_y_no_desborda(vista):
    descripcion = "A" * 600
    vista._mostrar_paso3_confirmacion(None, {
        "codigo": "LARGO-001",
        "referencia": "R" * 200,
        "descripcion_general": descripcion,
        "departamento": "Depto",
        "nombre_referencia_corto": "N" * 120,
    })

    fila_desc = next(
        f for f in _filas_resumen(vista)
        if isinstance(f.controls[0], ft.Text) and f.controls[0].value.startswith("Descripción General")
    )
    contenedor_valor = fila_desc.controls[1]
    texto_valor = contenedor_valor.content

    assert texto_valor.value == descripcion
    # Ancho acotado: el valor vive en un contenedor que toma el ancho restante.
    assert isinstance(contenedor_valor, ft.Container)
    assert contenedor_valor.expand or contenedor_valor.width
    # Envoltura multilínea con elipsis en vez de crecer hacia la derecha.
    assert not texto_valor.no_wrap
    assert texto_valor.max_lines and texto_valor.max_lines <= 6
    assert texto_valor.overflow in (ft.TextOverflow.ELLIPSIS, ft.TextOverflow.CLIP)


def test_todas_las_filas_del_resumen_acotan_su_valor(vista):
    vista._mostrar_paso3_confirmacion(None, {
        "codigo": "LARGO-002",
        "referencia": "R" * 300,
        "descripcion_general": "D" * 600,
        "nombre_referencia_corto": "N" * 300,
    })

    for fila in _filas_resumen(vista):
        etiqueta, valor = fila.controls[0], fila.controls[1]
        assert etiqueta.width, "la etiqueta debe conservar su ancho fijo"
        assert isinstance(valor, ft.Container) and (valor.expand or valor.width)
        assert not valor.content.no_wrap
        assert valor.content.max_lines


# ─────────────────────────────────────────────────────────────────────────────
# 3. Propiedad de scroll: un solo dueño por eje
# ─────────────────────────────────────────────────────────────────────────────
def test_el_cuerpo_de_la_vista_es_el_unico_dueno_del_scroll_vertical(vista):
    """Contrato de ejes: el `Column` devuelto por `get_body()` scrollea en
    vertical; la tabla NO anida otro scroll vertical (era lo que bloqueaba la
    rueda del mouse sobre el catálogo)."""
    cuerpo = vista.get_body()

    assert isinstance(cuerpo, ft.Column)
    assert cuerpo.scroll == ft.ScrollMode.AUTO
    assert cuerpo.expand is True
    assert cuerpo is vista._body_scroll_col

    assert vista._tabla_scroll_col.scroll is None, "scroll vertical anidado reintroducido"
    assert vista._tabla_scroll_col.height is None, "altura fija reintroducida en la tabla"
    assert vista._vista_container.height is None


def test_la_tabla_conserva_el_scroll_horizontal(vista):
    assert vista._tabla_scroll_row.scroll == ft.ScrollMode.ALWAYS
    assert vista._dt in vista._tabla_scroll_row.controls
    # Los botones flotantes siguen existiendo (targets de scroll_nav).
    assert vista._nav_h is not None and vista._nav_v is not None


@pytest.mark.parametrize("modo", ["separado", "agrupado", "tarjetas"])
def test_los_tres_modos_de_vista_no_anidan_scroll_vertical(vista, producto_existente, modo):
    """Con contenido real en los tres modos, ningún contenedor interno se queda
    con el eje vertical ni con una altura fija que lo recorte."""
    vista._modo_vista = modo
    vista._cargar_filas()

    contenido = vista._vista_container.content
    assert contenido is not None
    assert vista._vista_container.height is None
    assert getattr(contenido, "height", None) is None
    assert getattr(contenido, "scroll", None) is None
    assert vista._tabla_scroll_row.scroll == ft.ScrollMode.ALWAYS


@pytest.mark.parametrize("modo", ["separado", "agrupado", "tarjetas"])
def test_el_estado_vacio_no_reclama_el_scroll_vertical(vista, modo):
    """Sin resultados, el marcador de "no se encontraron productos" puede
    reservar alto para que el área no colapse, pero NUNCA habilita scroll
    propio: un contenedor sin scroll no compite por el gesto vertical."""
    vista._modo_vista = modo
    vista._cargar_filas()

    contenido = vista._vista_container.content
    assert contenido is not None
    assert getattr(contenido, "scroll", None) is None


def test_la_paginacion_sigue_operativa_tras_el_cambio_de_scroll(vista, producto_existente):
    vista._page_num = 1
    vista._pagina_siguiente(None)
    assert vista._page_num == 2
    vista._pagina_anterior(None)
    assert vista._page_num == 1
    assert "Página 1" in vista._lbl_pag.value
