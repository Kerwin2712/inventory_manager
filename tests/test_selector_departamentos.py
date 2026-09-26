"""Pruebas de `ui.components.selector_departamentos`.

El componente recibe sus fuentes de datos por inyección de dependencias, así
que estas pruebas usan proveedores FALSOS: no tocan la base ni
`departamentos_service`, y todo corre headless (sin `page`).
"""
import flet as ft
import pytest

from ui.components.selector_departamentos import (
    ETIQUETA_NUEVO_DEPARTAMENTO,
    ETIQUETA_NUEVO_SUB_DEPARTAMENTO,
    OPCION_NUEVO_DEPARTAMENTO,
    OPCION_NUEVO_SUB_DEPARTAMENTO,
    SelectorDepartamentos,
    construir_opciones,
)

# Jerarquía falsa con dos padres, para comprobar que los hijos no se cruzan.
CATALOGO = {
    "Ferretería": ["Tornillos", "Clavos", "Anclajes"],
    "Electricidad": ["Cables", "Breakers"],
}


def _proveedores(catalogo=None):
    catalogo = CATALOGO if catalogo is None else catalogo
    return (
        lambda: list(catalogo.keys()),
        lambda padre: list(catalogo.get(padre, [])),
    )


@pytest.fixture
def selector():
    obtener_deptos, obtener_subs = _proveedores()
    return SelectorDepartamentos(obtener_deptos, obtener_subs)


def _claves(dropdown: ft.Dropdown) -> list[str]:
    return [o.key for o in dropdown.options]


def _textos(dropdown: ft.Dropdown) -> list[str]:
    return [o.text for o in dropdown.options]


# ─────────────────────────────────────────────────────────────────────────────
# 1. Ordenamiento, deduplicación y posición de la opción especial
# ─────────────────────────────────────────────────────────────────────────────
def test_construir_opciones_ordena_alfabeticamente_ignorando_mayusculas():
    opciones = construir_opciones(
        ["zapatos", "Alfombras", "muebles", "Bombillos"],
        ETIQUETA_NUEVO_DEPARTAMENTO, OPCION_NUEVO_DEPARTAMENTO,
    )

    assert [o.key for o in opciones[:-1]] == ["Alfombras", "Bombillos", "muebles", "zapatos"]


def test_construir_opciones_fija_el_criterio_para_los_acentos():
    """Criterio idéntico a `departamentos_service._ordenar_alfabetico`: la clave
    es `(valor.lower(), valor)`, de modo que las vocales acentuadas ordenan por
    su punto de código, detrás de la `z`."""
    opciones = construir_opciones(
        ["Ámbar", "banana", "Apple", "árboles"],
        ETIQUETA_NUEVO_DEPARTAMENTO, OPCION_NUEVO_DEPARTAMENTO,
    )

    assert [o.key for o in opciones[:-1]] == ["Apple", "banana", "Ámbar", "árboles"]


def test_construir_opciones_deduplica_y_descarta_vacios():
    opciones = construir_opciones(
        ["Ferretería", "ferretería", "FERRETERÍA", "", "   ", None, "Pintura"],
        ETIQUETA_NUEVO_DEPARTAMENTO, OPCION_NUEVO_DEPARTAMENTO,
    )

    assert [o.key for o in opciones[:-1]] == ["Ferretería", "Pintura"]


def test_la_opcion_de_registrar_nuevo_queda_siempre_al_final():
    for valores in ([], ["Zapatos"], ["zzz", "aaa"], ["", None]):
        opciones = construir_opciones(
            valores, ETIQUETA_NUEVO_DEPARTAMENTO, OPCION_NUEVO_DEPARTAMENTO
        )
        assert opciones[-1].key == OPCION_NUEVO_DEPARTAMENTO
        assert opciones[-1].text == ETIQUETA_NUEVO_DEPARTAMENTO
        assert [o.key for o in opciones[:-1]].count(OPCION_NUEVO_DEPARTAMENTO) == 0


def test_el_dropdown_de_departamento_nace_ordenado_y_con_la_opcion_especial(selector):
    assert _claves(selector.dd_departamento) == [
        "Electricidad", "Ferretería", OPCION_NUEVO_DEPARTAMENTO,
    ]
    assert ETIQUETA_NUEVO_DEPARTAMENTO in _textos(selector.dd_departamento)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Jerarquía: cada padre solo ofrece sus propios hijos
# ─────────────────────────────────────────────────────────────────────────────
def test_los_sub_departamentos_son_los_del_padre_seleccionado(selector):
    selector.dd_departamento.value = "Ferretería"
    selector.manejar_cambio_departamento()

    assert _claves(selector.dd_sub_departamento) == [
        "Anclajes", "Clavos", "Tornillos", OPCION_NUEVO_SUB_DEPARTAMENTO,
    ]


def test_los_hijos_de_un_padre_no_se_filtran_al_otro(selector):
    selector.dd_departamento.value = "Electricidad"
    selector.manejar_cambio_departamento()

    hijos = _claves(selector.dd_sub_departamento)
    assert hijos == ["Breakers", "Cables", OPCION_NUEVO_SUB_DEPARTAMENTO]
    for ajeno in CATALOGO["Ferretería"]:
        assert ajeno not in hijos


def test_la_opcion_de_nuevo_sub_departamento_tambien_va_al_final(selector):
    selector.dd_departamento.value = "Ferretería"
    selector.manejar_cambio_departamento()

    assert selector.dd_sub_departamento.options[-1].key == OPCION_NUEVO_SUB_DEPARTAMENTO
    assert selector.dd_sub_departamento.options[-1].text == ETIQUETA_NUEVO_SUB_DEPARTAMENTO


def test_un_padre_sin_hijos_solo_ofrece_la_opcion_de_registrar_uno_nuevo():
    obtener_deptos, obtener_subs = _proveedores({"Servicios": []})
    selector = SelectorDepartamentos(obtener_deptos, obtener_subs)

    selector.dd_departamento.value = "Servicios"
    selector.manejar_cambio_departamento()

    assert _claves(selector.dd_sub_departamento) == [OPCION_NUEVO_SUB_DEPARTAMENTO]
    assert selector.dd_sub_departamento.visible is True


# ─────────────────────────────────────────────────────────────────────────────
# 3. Visibilidad condicional del sub-departamento
# ─────────────────────────────────────────────────────────────────────────────
def test_sin_padre_el_sub_departamento_es_invisible_e_inhabilitado(selector):
    assert selector.dd_sub_departamento.visible is False
    assert selector.dd_sub_departamento.disabled is True
    assert selector.tf_nuevo_sub_departamento.visible is False
    assert selector.valor_sub_departamento() == ""


def test_al_elegir_un_padre_real_el_sub_departamento_se_habilita(selector):
    selector.dd_departamento.value = "Ferretería"
    selector.manejar_cambio_departamento()

    assert selector.dd_sub_departamento.visible is True
    assert selector.dd_sub_departamento.disabled is False


def test_con_la_opcion_de_nuevo_departamento_el_sub_sigue_invisible(selector):
    selector.dd_departamento.value = OPCION_NUEVO_DEPARTAMENTO
    selector.manejar_cambio_departamento()

    assert selector.tf_nuevo_departamento.visible is True
    assert selector.dd_sub_departamento.visible is False
    assert selector.dd_sub_departamento.disabled is True
    assert selector.dd_sub_departamento.options == []
    assert selector.valor_sub_departamento() == ""


def test_volver_a_dejar_el_departamento_vacio_oculta_todo(selector):
    selector.dd_departamento.value = "Ferretería"
    selector.manejar_cambio_departamento()

    selector.dd_departamento.value = None
    selector.manejar_cambio_departamento()

    assert selector.dd_sub_departamento.visible is False
    assert selector.dd_sub_departamento.disabled is True
    assert selector.tf_nuevo_departamento.visible is False
    assert selector.valor_departamento() == ""


def test_cambiar_de_padre_resetea_la_seleccion_y_recarga_la_lista(selector):
    selector.dd_departamento.value = "Ferretería"
    selector.manejar_cambio_departamento()
    selector.dd_sub_departamento.value = "Tornillos"
    selector.manejar_cambio_sub_departamento()
    assert selector.valor_sub_departamento() == "Tornillos"

    selector.dd_departamento.value = "Electricidad"
    selector.manejar_cambio_departamento()

    assert selector.dd_sub_departamento.value is None, "la selección previa debe resetearse"
    assert selector.valor_sub_departamento() == ""
    assert "Tornillos" not in _claves(selector.dd_sub_departamento)


def test_el_campo_de_nuevo_sub_departamento_aparece_solo_con_la_opcion_especial(selector):
    selector.dd_departamento.value = "Ferretería"
    selector.manejar_cambio_departamento()
    assert selector.tf_nuevo_sub_departamento.visible is False

    selector.dd_sub_departamento.value = OPCION_NUEVO_SUB_DEPARTAMENTO
    selector.manejar_cambio_sub_departamento()
    assert selector.tf_nuevo_sub_departamento.visible is True

    selector.dd_sub_departamento.value = "Clavos"
    selector.manejar_cambio_sub_departamento()
    assert selector.tf_nuevo_sub_departamento.visible is False


def test_cambiar_de_padre_oculta_y_limpia_el_campo_de_nuevo_hijo(selector):
    selector.dd_departamento.value = "Ferretería"
    selector.manejar_cambio_departamento()
    selector.dd_sub_departamento.value = OPCION_NUEVO_SUB_DEPARTAMENTO
    selector.manejar_cambio_sub_departamento()
    selector.tf_nuevo_sub_departamento.value = "Tuercas"

    selector.dd_departamento.value = "Electricidad"
    selector.manejar_cambio_departamento()

    assert selector.tf_nuevo_sub_departamento.visible is False
    assert selector.tf_nuevo_sub_departamento.value == ""


# ─────────────────────────────────────────────────────────────────────────────
# 4. Lectura de valores y precarga en modo edición
# ─────────────────────────────────────────────────────────────────────────────
def test_el_valor_es_el_texto_escrito_cuando_se_registra_uno_nuevo(selector):
    selector.dd_departamento.value = OPCION_NUEVO_DEPARTAMENTO
    selector.manejar_cambio_departamento()
    selector.tf_nuevo_departamento.value = "  Jardinería  "

    assert selector.valor_departamento() == "Jardinería"


def test_el_sub_departamento_nuevo_se_lee_del_campo_de_texto(selector):
    selector.dd_departamento.value = "Ferretería"
    selector.manejar_cambio_departamento()
    selector.dd_sub_departamento.value = OPCION_NUEVO_SUB_DEPARTAMENTO
    selector.manejar_cambio_sub_departamento()
    selector.tf_nuevo_sub_departamento.value = " Tuercas "

    assert selector.valor_departamento() == "Ferretería"
    assert selector.valor_sub_departamento() == "Tuercas"


def test_set_valores_precarga_el_par_y_ajusta_la_visibilidad(selector):
    selector.set_valores("Ferretería", "Clavos")

    assert selector.dd_departamento.value == "Ferretería"
    assert selector.dd_sub_departamento.value == "Clavos"
    assert selector.dd_sub_departamento.visible is True
    assert selector.valor_departamento() == "Ferretería"
    assert selector.valor_sub_departamento() == "Clavos"


def test_set_valores_sin_departamento_deja_el_sub_oculto(selector):
    selector.set_valores("", "")

    assert selector.dd_departamento.value is None
    assert selector.dd_sub_departamento.visible is False


def test_set_valores_conserva_un_valor_historico_ausente_del_catalogo(selector):
    """Un producto viejo puede tener un departamento que ya no está en el
    catálogo: se inyecta como opción para no perderlo al editar."""
    selector.set_valores("Departamento Extinto", "Hijo Extinto")

    assert "Departamento Extinto" in _claves(selector.dd_departamento)
    assert selector.valor_departamento() == "Departamento Extinto"
    assert selector.valor_sub_departamento() == "Hijo Extinto"


# ─────────────────────────────────────────────────────────────────────────────
# 5. Robustez headless y callbacks
# ─────────────────────────────────────────────────────────────────────────────
def test_los_handlers_funcionan_sin_page_y_sin_evento(selector):
    selector.manejar_cambio_departamento(None)
    selector.manejar_cambio_sub_departamento(None)

    assert selector.dd_departamento.error_text is None


def test_el_callback_on_cambio_se_invoca_en_cada_cambio():
    obtener_deptos, obtener_subs = _proveedores()
    llamadas = []
    selector = SelectorDepartamentos(
        obtener_deptos, obtener_subs, on_cambio=lambda e=None: llamadas.append(e)
    )

    selector.dd_departamento.value = "Ferretería"
    selector.manejar_cambio_departamento()
    selector.manejar_cambio_sub_departamento()

    assert len(llamadas) == 2


def test_un_proveedor_que_falla_no_tumba_el_componente():
    def explotar():
        raise RuntimeError("base caída")

    selector = SelectorDepartamentos(explotar, lambda padre: 1 / 0)

    assert _claves(selector.dd_departamento) == [OPCION_NUEVO_DEPARTAMENTO]
    selector.dd_departamento.value = "Lo que sea"
    selector.manejar_cambio_departamento()
    assert _claves(selector.dd_sub_departamento) == [OPCION_NUEVO_SUB_DEPARTAMENTO]


def test_confirmar_creacion_persiste_los_valores_nuevos_y_devuelve_el_canonico():
    obtener_deptos, obtener_subs = _proveedores()
    creados = []
    selector = SelectorDepartamentos(
        obtener_deptos, obtener_subs,
        on_crear_departamento=lambda n: (creados.append(("dep", n)), n.title())[1],
        on_crear_sub_departamento=lambda p, n: (creados.append(("sub", p, n)), n.title())[1],
    )

    selector.dd_departamento.value = OPCION_NUEVO_DEPARTAMENTO
    selector.manejar_cambio_departamento()
    selector.tf_nuevo_departamento.value = "jardinería"

    assert selector.confirmar_creacion() == ("Jardinería", "")
    assert creados == [("dep", "jardinería")]


def test_marcar_error_resalta_el_control_que_falta(selector):
    selector.marcar_error()
    assert selector.dd_departamento.error_text == "Campo obligatorio"

    selector.limpiar_errores()
    selector.dd_departamento.value = OPCION_NUEVO_DEPARTAMENTO
    selector.manejar_cambio_departamento()
    selector.marcar_error("Falta el nombre")

    assert selector.dd_departamento.error_text is None
    assert selector.tf_nuevo_departamento.error_text == "Falta el nombre"


def test_construir_fila_devuelve_los_cuatro_controles_con_envoltura(selector):
    fila = selector.construir_fila()

    assert isinstance(fila, ft.Row) and fila.wrap is True
    assert fila.controls == selector.controles
    assert len(fila.controls) == 4


# ─────────────────────────────────────────────────────────────────────────────
# 6. Cableado real en el paso 2 del formulario de Inventario
# ─────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def vista(db_temporal):
    from ui.views.inventario_view import InventarioView

    v = InventarioView(es_admin=True, rol_usuario="administrador")
    v.get_body()
    return v


def test_el_paso2_usa_el_selector_en_vez_de_un_campo_de_texto_libre(vista):
    vista._mostrar_paso2_dialogo(None, codigo="NUEVO-001")
    selector = vista._selector_depto

    assert isinstance(selector, SelectorDepartamentos)
    assert selector.dd_departamento.options[-1].key == OPCION_NUEVO_DEPARTAMENTO
    # Los controles del selector viven en el diálogo abierto.
    filas = vista._dialog.content.content.controls
    assert any(getattr(f, "controls", None) == selector.controles for f in filas)


def test_el_paso2_ofrece_el_catalogo_real_de_departamentos(vista):
    from services.departamentos_service import crear_sub_departamento

    crear_sub_departamento("Ferretería", "Tornillos")
    crear_sub_departamento("Electricidad", "Cables")

    vista._mostrar_paso2_dialogo(None, codigo="NUEVO-002")
    selector = vista._selector_depto

    assert _claves(selector.dd_departamento) == [
        "Electricidad", "Ferretería", OPCION_NUEVO_DEPARTAMENTO,
    ]

    selector.dd_departamento.value = "Ferretería"
    selector.manejar_cambio_departamento()
    assert _claves(selector.dd_sub_departamento) == ["Tornillos", OPCION_NUEVO_SUB_DEPARTAMENTO]


def test_el_departamento_vacio_sigue_siendo_obligatorio_en_el_paso2(vista):
    vista._mostrar_paso2_dialogo(None, codigo="NUEVO-003")
    dlg_paso2 = vista._dialog
    campos = {c.label: c for c in _todos_los_campos(dlg_paso2)}
    campos["Referencia *"].value = "R"
    campos["Descripción General *"].value = "D"

    _click_accion(dlg_paso2, "Revisar y Guardar")

    assert vista._dialog is dlg_paso2, "el diálogo debe permanecer abierto"
    assert vista._selector_depto.dd_departamento.error_text == "Campo obligatorio"


def test_el_paso2_propaga_el_par_departamento_sub_departamento_al_resumen(vista):
    from services.departamentos_service import crear_sub_departamento

    crear_sub_departamento("Ferretería", "Tornillos")
    vista._mostrar_paso2_dialogo(None, codigo="NUEVO-004")
    dlg_paso2 = vista._dialog
    campos = {c.label: c for c in _todos_los_campos(dlg_paso2)}
    campos["Referencia *"].value = "REF-1"
    campos["Descripción General *"].value = "Tornillo galvanizado"
    campos["Existencia"].value = "0"
    selector = vista._selector_depto
    selector.dd_departamento.value = "Ferretería"
    selector.manejar_cambio_departamento()
    selector.dd_sub_departamento.value = "Tornillos"
    selector.manejar_cambio_sub_departamento()

    _click_accion(dlg_paso2, "Revisar y Guardar")

    resumen = " | ".join(
        fila.controls[1].content.value for fila in vista._dialog.content.content.controls
    )
    etiquetas = " | ".join(
        fila.controls[0].value for fila in vista._dialog.content.content.controls
    )
    assert "Sub-Departamento:" in etiquetas
    assert "Ferretería" in resumen and "Tornillos" in resumen


def test_guardar_desde_el_formulario_persiste_el_sub_departamento(vista):
    from services.inventario_service import obtener_producto

    vista._ejecutar_guardado(None, {
        "codigo": "SUB-001",
        "referencia": "REF-SUB",
        "descripcion_general": "Cable THW",
        "departamento": "Electricidad",
        "sub_departamento": "Cables",
        "existencia": "0",
    })

    guardado = obtener_producto("SUB-001")
    assert guardado["departamento"] == "Electricidad"
    assert guardado["sub_departamento"] == "Cables"


def test_editar_un_producto_precarga_el_par_en_el_selector(vista):
    from services.inventario_service import crear_producto

    crear_producto(
        codigo="EDIT-001", referencia="R", descripcion_general="D",
        departamento="Electricidad", sub_departamento="Cables", existencia=0,
    )

    vista._abrir_flujo_edicion("EDIT-001", None)
    selector = vista._selector_depto

    assert selector.valor_departamento() == "Electricidad"
    assert selector.valor_sub_departamento() == "Cables"


# ── Utilidades de los tests de la vista ──────────────────────────────────────
def _todos_los_campos(dlg: ft.AlertDialog) -> list[ft.TextField]:
    campos = []

    def caminar(control):
        if isinstance(control, ft.TextField):
            campos.append(control)
        for hijo in (getattr(control, "controls", None) or []):
            caminar(hijo)
        contenido = getattr(control, "content", None)
        if isinstance(contenido, ft.Control):
            caminar(contenido)

    caminar(dlg.content)
    return campos


def _click_accion(dlg: ft.AlertDialog, etiqueta: str, ev=None):
    for accion in dlg.actions:
        texto = getattr(accion, "text", None) or getattr(accion, "content", None)
        if isinstance(texto, str) and etiqueta.lower() in texto.lower():
            return accion.on_click(ev)
    raise AssertionError(f"No se encontró la acción '{etiqueta}'")
