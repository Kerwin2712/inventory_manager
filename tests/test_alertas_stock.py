"""Auditoría preventiva (ERS 3.6): umbral propio de cada producto y su unión
con el umbral global parametrizado."""
import pytest

from services.inventario_service import crear_producto
from services.reportes_service import (
    actualizar_stock_minimo,
    obtener_alertas_stock,
    obtener_alertas_stock_por_producto,
    obtener_metricas_dashboard,
)

CLAVES_DASHBOARD = {
    "codigo",
    "nombre_corto",
    "existencia",
    "minimo",
    "departamento",
    "proveedor_nombre",
    "proveedor_telefono",
    "proveedor_contacto",
}


def _crear(codigo: str, existencia: float, alerta=None, **extra):
    """Alta rápida de producto administrativo para los escenarios de alerta."""
    return crear_producto(
        codigo=codigo,
        referencia=f"REF-{codigo}",
        descripcion_general=f"Producto de prueba {codigo}",
        departamento="Ferretería",
        precio_dolares=10.0,
        existencia=existencia,
        alerta_stock_minimo=alerta,
        costo_usd_efectivo=6.0 if existencia >= 1 else None,
        rol_usuario="administrador",
        **extra,
    )


@pytest.fixture
def escenario(db_temporal):
    """Cuatro productos que cubren cada combinación de criterios.

    Umbral global fijado en 5:
    - A: existencia 2, alerta propia 4  → alerta por AMBOS (prevalece producto).
    - B: existencia 3, alerta propia 3  → caso de IGUALDAD, debe alertar.
    - C: existencia 9, alerta propia 10 → solo por umbral propio.
    - D: existencia 1, sin alerta propia → solo por umbral global.
    - E: existencia 40, alerta propia 5 → no alerta por ningún criterio.
    """
    actualizar_stock_minimo(5.0)
    _crear("A", 2.0, alerta=4)
    _crear("B", 3.0, alerta=3)
    _crear("C", 9.0, alerta=10)
    _crear("D", 1.0, alerta=None)
    _crear("E", 40.0, alerta=5)
    return None


# ─── Umbral propio del producto ──────────────────────────────────────────────

def test_alertas_por_producto_usa_el_comparador_mayor_o_igual(escenario):
    alertas = obtener_alertas_stock_por_producto()
    assert {a["codigo"] for a in alertas} == {"A", "B", "C"}
    assert all(a["origen"] == "producto" for a in alertas)


def test_la_igualdad_entre_umbral_propio_y_existencia_si_alerta(escenario):
    alertas = {a["codigo"]: a for a in obtener_alertas_stock_por_producto()}
    assert "B" in alertas
    assert alertas["B"]["existencia"] == 3.0
    assert alertas["B"]["alerta_stock_minimo"] == 3


def test_alertas_por_producto_ignora_a_quien_no_tiene_umbral_propio(escenario):
    assert "D" not in {a["codigo"] for a in obtener_alertas_stock_por_producto()}


def test_el_minimo_reportado_es_el_umbral_propio(escenario):
    alertas = {a["codigo"]: a for a in obtener_alertas_stock_por_producto()}
    assert alertas["C"]["minimo"] == 10.0
    assert alertas["C"]["alerta_stock_minimo"] == 10


def test_sin_umbrales_propios_no_hay_alertas_por_producto(db_temporal):
    _crear("SOLO", 0.0)
    assert obtener_alertas_stock_por_producto() == []


# ─── Unión con el umbral global ──────────────────────────────────────────────

def test_la_union_no_duplica_productos(escenario):
    alertas = obtener_alertas_stock(minimo=5.0)
    codigos = [a["codigo"] for a in alertas]
    assert sorted(codigos) == ["A", "B", "C", "D"]
    assert len(codigos) == len(set(codigos))


def test_el_origen_producto_prevalece_sobre_el_global(escenario):
    alertas = {a["codigo"]: a for a in obtener_alertas_stock(minimo=5.0)}
    # A y B califican por ambos criterios; gana el umbral propio.
    assert alertas["A"]["origen"] == "producto"
    assert alertas["A"]["minimo"] == 4.0
    assert alertas["B"]["origen"] == "producto"
    # D solo califica por el umbral global.
    assert alertas["D"]["origen"] == "global"
    assert alertas["D"]["minimo"] == 5.0
    assert alertas["D"]["alerta_stock_minimo"] is None


def test_alertas_stock_conserva_las_claves_que_consume_el_dashboard(escenario):
    alertas = obtener_alertas_stock(minimo=5.0)
    assert alertas
    for alerta in alertas:
        assert CLAVES_DASHBOARD <= set(alerta)
        # El Dashboard formatea `minimo` como float (f"{item['minimo']:.0f}").
        assert isinstance(alerta["minimo"], float)
        assert isinstance(alerta["existencia"], float)
        assert alerta["origen"] in ("producto", "global")


def test_alertas_stock_usa_el_minimo_parametrizado_si_no_se_indica(db_temporal):
    actualizar_stock_minimo(8.0)
    _crear("Z", 7.0)
    alertas = obtener_alertas_stock()
    assert [a["codigo"] for a in alertas] == ["Z"]
    assert alertas[0]["origen"] == "global"
    assert alertas[0]["minimo"] == 8.0


def test_producto_sin_alertas_no_aparece(escenario):
    assert "E" not in {a["codigo"] for a in obtener_alertas_stock(minimo=5.0)}


def test_proveedor_sin_asignar_usa_los_textos_por_defecto(escenario):
    alerta = next(a for a in obtener_alertas_stock(minimo=5.0) if a["codigo"] == "A")
    assert alerta["proveedor_nombre"] == "Sin Proveedor Asignado"
    assert alerta["proveedor_telefono"] == "N/A"
    assert alerta["proveedor_contacto"] == "N/A"


def test_la_metrica_del_dashboard_cuenta_los_dos_criterios(escenario):
    # A, B, C y D alertan; E no. El conteo debe coincidir con la tabla.
    assert obtener_metricas_dashboard()["total_criticos"] == 4
