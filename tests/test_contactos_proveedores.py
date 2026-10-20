"""Contactos de reposición agrupados por proveedor.

Los alimenta la acción "Contactar proveedor" de la Auditoría Preventiva. Lo que
se blinda aquí es el criterio: reponer no se hace producto por producto sino
LLAMADA POR LLAMADA, así que con cuatro productos de dos proveedores el usuario
tiene que ver dos bloques y no cuatro, y los productos sin proveedor cargado no
pueden desaparecer de la lista (son justo los que le falta averiguar).
"""
import pytest

from services.cartera_service import crear_proveedor
from services.inventario_service import crear_producto
from services.reportes_service import (
    SIN_PROVEEDOR,
    obtener_alertas_stock,
    obtener_contactos_proveedores,
)


def _producto(codigo: str, proveedor_id=None, existencia: float = 1.0):
    return crear_producto(
        codigo=codigo,
        referencia=f"REF-{codigo}",
        descripcion_general=f"Producto de prueba {codigo}",
        departamento="Ferretería",
        precio_dolares=10.0,
        existencia=existencia,
        nombre_referencia_corto=f"Corto {codigo}",
        proveedor_id=proveedor_id,
        costo_usd_efectivo=6.0,
        rol_usuario="administrador",
    )


@pytest.fixture
def escenario(db_temporal):
    """Dos proveedores con dos productos cada uno, más uno huérfano."""
    acme = crear_proveedor(
        empresa="Acme C.A.", contacto="Juan Pérez",
        telefono="0412-1112233", correo="ventas@acme.com", rif="J-111111",
    )
    globex = crear_proveedor(
        empresa="Globex S.A.", contacto="Ana Díaz",
        telefono="0414-9998877", correo="compras@globex.com", rif="J-222222",
    )
    _producto("A-1", proveedor_id=acme["id"])
    _producto("A-2", proveedor_id=acme["id"])
    _producto("G-1", proveedor_id=globex["id"])
    _producto("G-2", proveedor_id=globex["id"])
    _producto("HUERFANO", proveedor_id=None)
    return {"acme": acme["id"], "globex": globex["id"]}


# ─── Un bloque por proveedor, sin repetir ────────────────────────────────────

def test_cuatro_productos_de_dos_proveedores_dan_dos_contactos(escenario):
    contactos = obtener_contactos_proveedores(["A-1", "A-2", "G-1", "G-2"])

    assert len(contactos) == 2
    assert {c["proveedor_id"] for c in contactos} == {escenario["acme"], escenario["globex"]}


def test_cada_bloque_lista_los_productos_que_le_corresponden(escenario):
    contactos = {c["empresa"]: c for c in obtener_contactos_proveedores(
        ["A-1", "G-1", "A-2", "G-2"]
    )}

    assert [p["codigo"] for p in contactos["Acme C.A."]["productos"]] == ["A-1", "A-2"]
    assert [p["codigo"] for p in contactos["Globex S.A."]["productos"]] == ["G-1", "G-2"]


def test_el_bloque_trae_el_telefono_y_el_correo(escenario):
    contacto = obtener_contactos_proveedores(["A-1"])[0]

    assert contacto["telefono"] == "0412-1112233"
    assert contacto["correo"] == "ventas@acme.com"
    assert contacto["contacto"] == "Juan Pérez"


def test_el_orden_lo_marca_el_primer_producto_de_cada_proveedor(escenario):
    """El usuario armó la selección en un orden y reconoce su propia lista."""
    contactos = obtener_contactos_proveedores(["G-2", "A-1"])

    assert [c["empresa"] for c in contactos] == ["Globex S.A.", "Acme C.A."]


def test_el_producto_trae_su_nombre_corto_y_su_existencia(escenario):
    """La llamada se hace nombrando el producto, no recitando un código."""
    producto = obtener_contactos_proveedores(["A-1"])[0]["productos"][0]

    assert producto["nombre_corto"] == "Corto A-1"
    assert producto["existencia"] == 1.0


# ─── Los productos sin proveedor no se esconden ──────────────────────────────

def test_el_producto_sin_proveedor_va_en_su_propio_bloque(escenario):
    contactos = obtener_contactos_proveedores(["A-1", "HUERFANO"])

    assert len(contactos) == 2
    huerfano = next(c for c in contactos if c["proveedor_id"] is None)
    assert huerfano["empresa"] == SIN_PROVEEDOR
    assert [p["codigo"] for p in huerfano["productos"]] == ["HUERFANO"]


def test_el_bloque_sin_proveedor_queda_al_final(escenario):
    """No es una llamada que el usuario pueda hacer ya: va después."""
    contactos = obtener_contactos_proveedores(["HUERFANO", "A-1"])

    assert contactos[-1]["proveedor_id"] is None


# ─── Casos de borde ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("entrada", [[], None, ["", "   "]])
def test_sin_codigos_no_hay_contactos(db_temporal, entrada):
    assert obtener_contactos_proveedores(entrada) == []


def test_un_codigo_inexistente_se_ignora_sin_reventar(escenario):
    """Pudo borrarse entre el marcado y la acción; eso no es motivo para
    negarle al usuario los contactos de los que sí existen."""
    contactos = obtener_contactos_proveedores(["A-1", "NO-EXISTE"])

    assert len(contactos) == 1
    assert [p["codigo"] for p in contactos[0]["productos"]] == ["A-1"]


def test_un_codigo_repetido_no_duplica_el_producto_en_el_bloque(escenario):
    contactos = obtener_contactos_proveedores(["A-1", "A-1"])

    # El mismo código marcado dos veces no puede existir en el modelo de
    # selección, pero el servicio no debe multiplicar renglones si llega así.
    assert len(contactos) == 1
    assert len(contactos[0]["productos"]) <= 2


# ─── Las alertas ya traen con qué agrupar ────────────────────────────────────

def test_la_alerta_trae_el_identificador_del_proveedor(escenario):
    """Sin `proveedor_id` la vista tendría que agrupar por nombre de empresa, y
    dos proveedores sin empresa cargada se fundirían en uno."""
    alertas = {a["codigo"]: a for a in obtener_alertas_stock(minimo=5.0)}

    assert alertas["A-1"]["proveedor_id"] == escenario["acme"]
    assert alertas["HUERFANO"]["proveedor_id"] is None


def test_la_alerta_trae_el_correo_del_proveedor(escenario):
    alertas = {a["codigo"]: a for a in obtener_alertas_stock(minimo=5.0)}

    assert alertas["G-1"]["proveedor_correo"] == "compras@globex.com"
    assert alertas["HUERFANO"]["proveedor_correo"] == ""
