"""Motor de búsqueda multicriterio de productos (`services/busqueda_service.py`).

Cubre el contrato que consume el módulo de Ventas: filtrado por criterio,
coincidencia parcial insensible a mayúsculas, multi-palabra en AND, límite,
ausencia de columnas de costo y resolución determinista del escáneo de códigos.
"""
import pytest

from services.bcv_service import actualizar_tasa
from services.busqueda_service import (
    CRITERIOS_BUSQUEDA,
    COLUMNAS_RESULTADO,
    buscar_productos,
    resolver_coincidencia_exacta,
)
from services.inventario_service import crear_producto

CAMPOS_COSTO = ("costo_usd_efectivo", "costo_usd_bcv")


@pytest.fixture
def catalogo(db_temporal):
    """Catálogo mínimo diseñado para que cada criterio tenga un producto que
    solo él puede encontrar (así un criterio nunca 'pesca' en otra columna)."""
    actualizar_tasa(40.0)
    crear_producto(
        codigo="LAP-001",
        referencia="REF-LAPTOP",
        descripcion_general="Laptop empresarial de 14 pulgadas",
        departamento="Tecnologia",
        marca="Lenovo",
        precio_dolares=500.0,
        precio_bcv=520.0,
        existencia=6.0,
        codigo_barras="7591234567890",
        nombre_referencia_corto="Laptop 14",
        costo_usd_efectivo=400.0,
        costo_usd_bcv=415.0,
        rol_usuario="administrador",
    )
    crear_producto(
        codigo="MAR-777",
        referencia="REF-MOUSE",
        descripcion_general="Mouse inalambrico ergonomico",
        departamento="Accesorios",
        marca="Tecnologia Global",  # la MARCA contiene la palabra "Tecnologia"
        precio_dolares=15.0,
        precio_bcv=16.0,
        existencia=30.0,
        codigo_barras="7599876543210",
        nombre_referencia_corto="Mouse Ergo",
        costo_usd_efectivo=9.0,
        rol_usuario="administrador",
    )
    crear_producto(
        codigo="TEC-050",
        referencia="REF-TECLADO",
        descripcion_general="Teclado mecanico retroiluminado",
        departamento="Accesorios",
        marca="Redragon",
        precio_dolares=45.0,
        precio_bcv=48.0,
        existencia=12.0,
        codigo_barras="LAP-001",  # código de barras que colisiona con otro código
        nombre_referencia_corto="Teclado Mec",
        costo_usd_efectivo=30.0,
        rol_usuario="administrador",
    )
    return db_temporal


# ─── 1. Filtrado por criterio ────────────────────────────────────────────────

def test_criterio_codigo_encuentra_por_codigo_y_por_codigo_de_barras(catalogo):
    assert [p["codigo"] for p in buscar_productos("MAR-777", criterio="Código")] == ["MAR-777"]
    assert [p["codigo"] for p in buscar_productos("7591234567890", criterio="Código")] == ["LAP-001"]


def test_criterio_descripcion_busca_en_descripcion_y_nombre_corto(catalogo):
    assert [p["codigo"] for p in buscar_productos("retroiluminado", criterio="Descripción")] == ["TEC-050"]
    assert [p["codigo"] for p in buscar_productos("Mouse Ergo", criterio="Descripción")] == ["MAR-777"]


def test_criterio_referencia_solo_mira_la_columna_referencia(catalogo):
    assert [p["codigo"] for p in buscar_productos("REF-TECLADO", criterio="Referencia")] == ["TEC-050"]
    # "Lenovo" vive en `marca`, no en `referencia`.
    assert buscar_productos("Lenovo", criterio="Referencia") == []


def test_criterio_departamento_filtra_por_departamento(catalogo):
    codigos = [p["codigo"] for p in buscar_productos("Accesorios", criterio="Departamento")]
    assert codigos == ["MAR-777", "TEC-050"]


def test_criterio_departamento_no_devuelve_producto_cuya_marca_coincide(catalogo):
    """"Tecnologia" es el departamento de LAP-001 y parte de la MARCA de
    MAR-777: el criterio Departamento no debe pescar en la columna marca."""
    codigos = [p["codigo"] for p in buscar_productos("Tecnologia", criterio="Departamento")]
    assert codigos == ["LAP-001"]


def test_criterio_marca_no_devuelve_producto_cuyo_departamento_coincide(catalogo):
    codigos = [p["codigo"] for p in buscar_productos("Tecnologia", criterio="Marca")]
    assert codigos == ["MAR-777"]


def test_criterio_todos_abarca_departamento_y_marca_a_la_vez(catalogo):
    codigos = {p["codigo"] for p in buscar_productos("Tecnologia", criterio="Todos")}
    assert codigos == {"LAP-001", "MAR-777"}


def test_criterio_por_defecto_es_todos(catalogo):
    assert buscar_productos("Tecnologia") == buscar_productos("Tecnologia", criterio="Todos")


# ─── 2. Coincidencia parcial e insensibilidad a mayúsculas ───────────────────

def test_busqueda_es_parcial(catalogo):
    assert [p["codigo"] for p in buscar_productos("lap", criterio="Descripción")] == ["LAP-001"]


def test_busqueda_es_insensible_a_mayusculas(catalogo):
    minusculas = buscar_productos("lap", criterio="Descripción")
    mayusculas = buscar_productos("LAP", criterio="Descripción")
    capitalizada = buscar_productos("Lap", criterio="Descripción")
    assert minusculas == mayusculas == capitalizada
    assert [p["codigo"] for p in minusculas] == ["LAP-001"]


# ─── 3. Multi-palabra en AND ─────────────────────────────────────────────────

def test_multipalabra_exige_todas_las_palabras(catalogo):
    assert [p["codigo"] for p in buscar_productos("teclado mecanico", criterio="Todos")] == ["TEC-050"]


def test_multipalabra_descarta_si_falta_una_palabra(catalogo):
    # "teclado" coincide, "inalambrico" pertenece a otro producto → AND vacío.
    assert buscar_productos("teclado inalambrico", criterio="Todos") == []


def test_multipalabra_puede_repartirse_entre_columnas_del_criterio(catalogo):
    # "Lenovo" está en marca y "Tecnologia" en departamento: con "Todos" cada
    # palabra se satisface en una columna distinta del mismo producto.
    assert [p["codigo"] for p in buscar_productos("Lenovo Tecnologia", criterio="Todos")] == ["LAP-001"]


# ─── 4. Bordes del contrato ──────────────────────────────────────────────────

@pytest.mark.parametrize("termino", ["", "   ", "\t\n", None])
def test_termino_vacio_devuelve_lista_vacia_no_la_tabla_entera(catalogo, termino):
    assert buscar_productos(termino, criterio="Todos") == []


def test_criterio_inexistente_lanza_value_error(catalogo):
    with pytest.raises(ValueError) as exc:
        buscar_productos("laptop", criterio="Proveedor")
    assert "ERR_BUSQ_CRITERIO" in str(exc.value)


def test_criterio_inexistente_se_valida_antes_del_termino_vacio(catalogo):
    with pytest.raises(ValueError):
        buscar_productos("", criterio="Proveedor")


def test_el_limite_de_resultados_se_respeta(catalogo):
    assert len(buscar_productos("Accesorios", criterio="Departamento", limite=1)) == 1
    assert len(buscar_productos("Accesorios", criterio="Departamento", limite=50)) == 2


def test_orden_estable_por_departamento_y_codigo(catalogo):
    codigos = [p["codigo"] for p in buscar_productos("REF-", criterio="Referencia")]
    assert codigos == ["MAR-777", "TEC-050", "LAP-001"]


def test_los_resultados_no_exponen_columnas_de_costo(catalogo):
    """Ventas no debe ver los costos del negocio: nunca salen de la base."""
    resultados = buscar_productos("REF-", criterio="Referencia")
    assert len(resultados) == 3
    for producto in resultados:
        assert not set(producto) & set(CAMPOS_COSTO)


def test_los_resultados_traen_las_columnas_declaradas_mas_el_monto_en_bolivares(catalogo):
    producto = buscar_productos("LAP-001", criterio="Código")[0]
    assert set(producto) == set(COLUMNAS_RESULTADO) | {"monto_bcv_bolivares"}


def test_monto_en_bolivares_se_calcula_en_vivo_con_la_tasa_vigente(catalogo):
    def _monto_laptop() -> float:
        resultados = buscar_productos("7591234567890", criterio="Código")
        return resultados[0]["monto_bcv_bolivares"]

    assert _monto_laptop() == pytest.approx(520.0 * 40.0)
    actualizar_tasa(50.0)
    assert _monto_laptop() == pytest.approx(520.0 * 50.0)


def test_el_mapa_de_criterios_expone_las_etiquetas_esperadas(catalogo):
    assert list(CRITERIOS_BUSQUEDA) == [
        "Todos", "Código", "Descripción", "Referencia",
        "Departamento", "Marca", "Sub-Departamento",
    ]
    assert CRITERIOS_BUSQUEDA["Código"] == ("codigo", "codigo_barras")
    assert CRITERIOS_BUSQUEDA["Departamento"] == ("departamento",)


# ─── 5. Resolución de coincidencia exacta (escáner de código de barras) ──────

def test_coincidencia_exacta_por_codigo(catalogo):
    resultados = buscar_productos("MAR-777", criterio="Código")
    assert resolver_coincidencia_exacta("MAR-777", resultados)["codigo"] == "MAR-777"


def test_coincidencia_exacta_por_codigo_de_barras(catalogo):
    resultados = buscar_productos("7599876543210", criterio="Código")
    assert resolver_coincidencia_exacta("7599876543210", resultados)["codigo"] == "MAR-777"


def test_coincidencia_exacta_prioriza_codigo_sobre_codigo_de_barras(catalogo):
    """"LAP-001" es el código de LAP-001 y el código de barras de TEC-050: el
    código propio manda, sin depender del orden de la lista."""
    resultados = buscar_productos("LAP-001", criterio="Código")
    assert {p["codigo"] for p in resultados} == {"LAP-001", "TEC-050"}
    assert resolver_coincidencia_exacta("LAP-001", resultados)["codigo"] == "LAP-001"


def test_coincidencia_exacta_ignora_mayusculas_y_espacios(catalogo):
    resultados = buscar_productos("mar-777", criterio="Código")
    assert resolver_coincidencia_exacta("  mar-777  ", resultados)["codigo"] == "MAR-777"


def test_coincidencia_exacta_devuelve_none_cuando_solo_hay_parciales(catalogo):
    resultados = buscar_productos("lap", criterio="Todos")
    assert resultados
    assert resolver_coincidencia_exacta("lap", resultados) is None


@pytest.mark.parametrize("termino", ["", "   ", None])
def test_coincidencia_exacta_con_termino_vacio_devuelve_none(catalogo, termino):
    resultados = buscar_productos("LAP-001", criterio="Código")
    assert resolver_coincidencia_exacta(termino, resultados) is None
