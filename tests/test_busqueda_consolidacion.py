"""Cierre de los dos cabos que la ejecución concurrente dejó pendientes:

1. El criterio "Sub-Departamento" del buscador de Ventas, que quedó preparado
   pero inactivo mientras otro agente añadía la columna al esquema.
2. La búsqueda libre de `listar_productos` sobre columnas nullables: en SQL
   `NULL LIKE ?` evalúa a NULL, no a falso, así que una sola columna nula
   anulaba el OR y la búsqueda perdía coincidencias válidas de las demás.
"""
import pytest

from services.busqueda_service import CRITERIOS_BUSQUEDA, buscar_productos
from services.inventario_service import crear_producto, listar_productos


@pytest.fixture
def catalogo(db_temporal):
    """Dos productos con sub-departamentos distintos; el segundo deja nulos
    `marca`, `codigo_barras` y `nombre_referencia_corto`."""
    crear_producto(
        codigo="TAL-001",
        referencia="REF-TAL",
        descripcion_general="Taladro percutor industrial",
        departamento="Herramientas",
        sub_departamento="Electricas",
        marca="Bosch",
        codigo_barras="7591234567890",
        nombre_referencia_corto="Taladro percutor",
        precio_dolares=100.0,
    )
    crear_producto(
        codigo="MAR-002",
        referencia="REF-MAR",
        descripcion_general="Martillo de carpintero",
        departamento="Herramientas",
        sub_departamento="Manuales",
        precio_dolares=8.0,
    )
    return ("TAL-001", "MAR-002")


# ── 1. Criterio "Sub-Departamento" ───────────────────────────────────────────
def test_el_criterio_sub_departamento_esta_disponible():
    assert "Sub-Departamento" in CRITERIOS_BUSQUEDA
    assert CRITERIOS_BUSQUEDA["Sub-Departamento"] == ("sub_departamento",)


def test_buscar_por_sub_departamento_filtra_solo_ese_hijo(catalogo):
    resultados = buscar_productos("Manuales", criterio="Sub-Departamento")
    assert [r["codigo"] for r in resultados] == ["MAR-002"]


def test_el_criterio_sub_departamento_no_pesca_en_otras_columnas(catalogo):
    """"Herramientas" es el departamento PADRE, no un sub-departamento."""
    assert buscar_productos("Herramientas", criterio="Sub-Departamento") == []


def test_la_busqueda_general_tambien_cubre_el_sub_departamento(catalogo):
    resultados = buscar_productos("Electricas", criterio="Todos")
    assert [r["codigo"] for r in resultados] == ["TAL-001"]


def test_los_resultados_exponen_el_sub_departamento(catalogo):
    resultado = buscar_productos("TAL-001", criterio="Código")[0]
    assert resultado["sub_departamento"] == "Electricas"


# ── 2. Regresión: columnas nullables en la búsqueda libre ────────────────────
def test_listar_productos_encuentra_un_producto_con_columnas_nulas(catalogo):
    """Antes del IFNULL, `marca`/`codigo_barras` nulos anulaban todo el OR y
    este producto era imposible de encontrar por su descripción."""
    resultados = listar_productos(busqueda="Martillo")
    assert [p["codigo"] for p in resultados] == ["MAR-002"]


def test_listar_productos_sigue_encontrando_por_columnas_llenas(catalogo):
    assert [p["codigo"] for p in listar_productos(busqueda="Bosch")] == ["TAL-001"]


def test_listar_productos_multipalabra_con_columnas_nulas(catalogo):
    """Cada palabra se exige con AND; ninguna debe perderse por un NULL."""
    resultados = listar_productos(busqueda="Martillo carpintero")
    assert [p["codigo"] for p in resultados] == ["MAR-002"]
    assert listar_productos(busqueda="Martillo Bosch") == []
