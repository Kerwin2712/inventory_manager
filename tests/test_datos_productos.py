"""Capa de datos del inventario: migración incremental, costos con permisos de
rol y catálogo jerárquico Departamento → Sub-Departamento."""
import pytest

from core.database import get_connection, init_db
from services.departamentos_service import (
    crear_departamento,
    crear_sub_departamento,
    listar_departamentos,
    listar_sub_departamentos,
    sincronizar_catalogo_departamentos,
)
from services.inventario_service import (
    actualizar_producto,
    crear_producto,
    listar_productos,
    obtener_producto,
)
from services.permisos_service import es_admin, filtrar_campos_costo

CAMPOS_COSTO = ("costo_usd_efectivo", "costo_usd_bcv")


def _columnas_productos(conexion) -> set[str]:
    cursor = conexion.cursor()
    cursor.execute("PRAGMA table_info(productos)")
    return {fila["name"] for fila in cursor.fetchall()}


def _tablas(conexion) -> set[str]:
    cursor = conexion.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return {fila["name"] for fila in cursor.fetchall()}


@pytest.fixture
def producto_admin(db_temporal):
    """Producto con existencia y costos registrados por un administrador."""
    crear_producto(
        codigo="P-100",
        referencia="REF-100",
        descripcion_general="Taladro percutor industrial",
        departamento="Ferretería",
        sub_departamento="Herramientas Eléctricas",
        precio_dolares=85.0,
        precio_bcv=90.0,
        existencia=7.0,
        costo_usd_efectivo=55.0,
        costo_usd_bcv=58.5,
        alerta_stock_minimo=3,
        rol_usuario="administrador",
    )
    return "P-100"


# ─── 1. Migración incremental ────────────────────────────────────────────────

def test_migracion_agrega_las_cuatro_columnas_nuevas(db_temporal, conexion):
    columnas = _columnas_productos(conexion)
    assert {
        "costo_usd_efectivo",
        "costo_usd_bcv",
        "sub_departamento",
        "alerta_stock_minimo",
    } <= columnas


def test_migracion_crea_tablas_del_catalogo(db_temporal, conexion):
    assert {"departamentos", "sub_departamentos"} <= _tablas(conexion)


def test_init_db_es_idempotente_y_no_duplica_columnas(db_temporal, conexion):
    antes = sorted(_columnas_productos(conexion))
    init_db()
    init_db()
    assert sorted(_columnas_productos(conexion)) == antes
    assert len(antes) == len(set(antes))


# ─── 2. Validaciones de negocio de los campos nuevos ─────────────────────────

def test_error_si_hay_existencia_sin_costo_usd_efectivo(db_temporal):
    with pytest.raises(ValueError) as ex:
        crear_producto(
            codigo="P-SIN-COSTO",
            referencia="REF",
            descripcion_general="Producto con stock pero sin costo",
            departamento="Ferretería",
            precio_dolares=10.0,
            existencia=4.0,
            rol_usuario="administrador",
        )
    assert str(ex.value).startswith("ERR_PROD_COSTO")


def test_error_si_el_costo_efectivo_llega_vacio_con_existencia(db_temporal):
    with pytest.raises(ValueError) as ex:
        crear_producto(
            codigo="P-COSTO-VACIO",
            referencia="REF",
            descripcion_general="Producto con stock y costo en blanco",
            departamento="Ferretería",
            precio_dolares=10.0,
            existencia=1.0,
            costo_usd_efectivo="",
            rol_usuario="administrador",
        )
    assert str(ex.value).startswith("ERR_PROD_COSTO")


def test_guardar_con_costo_usd_bcv_nulo_funciona(db_temporal):
    prod = crear_producto(
        codigo="P-BCV-NULO",
        referencia="REF",
        descripcion_general="El costo BCV siempre es opcional",
        departamento="Ferretería",
        precio_dolares=12.0,
        existencia=3.0,
        costo_usd_efectivo=8.0,
        costo_usd_bcv=None,
        rol_usuario="administrador",
    )
    assert prod["costo_usd_efectivo"] == 8.0
    assert prod["costo_usd_bcv"] is None


def test_existencia_cero_sin_costo_se_puede_guardar(db_temporal):
    prod = crear_producto(
        codigo="P-CERO",
        referencia="REF",
        descripcion_general="Producto agotado sin costo registrado",
        departamento="Ferretería",
        existencia=0.0,
        rol_usuario="administrador",
    )
    assert prod["existencia"] == 0.0
    assert prod["costo_usd_efectivo"] is None


@pytest.mark.parametrize("valor,esperado", [(5, 5), ("5", 5), (0, 0), (None, None), ("", None)])
def test_alerta_stock_minimo_acepta_enteros_y_cadenas_enteras(db_temporal, valor, esperado):
    prod = crear_producto(
        codigo=f"P-AL-{valor!r}",
        referencia="REF",
        descripcion_general="Umbral propio de alerta",
        departamento="Ferretería",
        existencia=0.0,
        alerta_stock_minimo=valor,
        rol_usuario="administrador",
    )
    assert prod["alerta_stock_minimo"] == esperado


@pytest.mark.parametrize("valor", [5.7, "abc", -1, "-3", "2,5"])
def test_alerta_stock_minimo_rechaza_decimales_no_numericos_y_negativos(db_temporal, valor):
    with pytest.raises(ValueError) as ex:
        crear_producto(
            codigo="P-AL-MALA",
            referencia="REF",
            descripcion_general="Umbral inválido",
            departamento="Ferretería",
            existencia=0.0,
            alerta_stock_minimo=valor,
            rol_usuario="administrador",
        )
    assert str(ex.value).startswith("ERR_PROD_ALERTA")


def test_modelo_producto_valida_los_mismos_campos_nuevos():
    from core.models import Producto

    with pytest.raises(ValueError) as ex:
        Producto(
            codigo_producto="M-1",
            referencia="REF",
            departamento="Ferretería",
            descripcion_general="Modelo con stock sin costo",
            marca="ACME",
            precio_dolares=10.0,
            existencia=2.0,
        )
    assert str(ex.value).startswith("ERR_PROD_COSTO")

    prod = Producto(
        codigo_producto="M-2",
        referencia="REF",
        departamento="Ferretería",
        descripcion_general="Modelo válido",
        marca="ACME",
        precio_dolares=10.0,
        existencia=2.0,
        costo_usd_efectivo="7,50",
        alerta_stock_minimo="4",
        sub_departamento="  Tornillería  ",
    )
    assert prod.costo_usd_efectivo == 7.5
    assert prod.costo_usd_bcv is None
    assert prod.alerta_stock_minimo == 4
    assert prod.sub_departamento == "Tornillería"


# ─── 3. Permisos de rol sobre los costos ─────────────────────────────────────

@pytest.mark.parametrize("rol", ["administrador", "superadmin", "gerencia", "ADMINISTRADOR"])
def test_es_admin_reconoce_los_roles_administrativos(rol):
    assert es_admin(rol) is True


@pytest.mark.parametrize("rol", [None, "", "vendedor", "VENDEDOR", "desconocido"])
def test_es_admin_es_fail_closed(rol):
    assert es_admin(rol) is False


def test_filtrar_campos_costo_devuelve_copia_sin_costos_para_no_admin():
    datos = {"codigo": "X", "costo_usd_efectivo": 1.0, "costo_usd_bcv": 2.0}
    filtrado = filtrar_campos_costo(datos, "vendedor")
    assert "costo_usd_efectivo" not in filtrado and "costo_usd_bcv" not in filtrado
    assert datos["costo_usd_efectivo"] == 1.0  # el original no se muta


@pytest.mark.parametrize("rol", ["vendedor", None])
def test_rol_no_admin_no_lee_los_costos(producto_admin, rol):
    prod = obtener_producto(producto_admin, rol_usuario=rol)
    assert all(campo not in prod for campo in CAMPOS_COSTO)
    # Los PRECIOS de venta sí se siguen viendo (no son costos).
    assert prod["precio_dolares"] == 85.0
    assert prod["precio_bcv"] == 90.0

    listado = listar_productos(rol_usuario=rol)
    assert listado and all(campo not in p for p in listado for campo in CAMPOS_COSTO)


@pytest.mark.parametrize("rol", ["administrador", "superadmin", "gerencia"])
def test_rol_admin_lee_los_costos(producto_admin, rol):
    prod = obtener_producto(producto_admin, rol_usuario=rol)
    assert prod["costo_usd_efectivo"] == 55.0
    assert prod["costo_usd_bcv"] == 58.5

    listado = listar_productos(rol_usuario=rol)
    assert listado[0]["costo_usd_efectivo"] == 55.0


def test_rol_no_admin_no_puede_crear_con_costos(db_temporal):
    with pytest.raises(PermissionError) as ex:
        crear_producto(
            codigo="P-VEND",
            referencia="REF",
            descripcion_general="Intento de vendedor",
            departamento="Ferretería",
            existencia=0.0,
            costo_usd_efectivo=10.0,
            rol_usuario="vendedor",
        )
    assert str(ex.value).startswith("ERR_PROD_ROL")


def test_rol_no_admin_no_puede_actualizar_los_costos(producto_admin):
    with pytest.raises(PermissionError) as ex:
        actualizar_producto(
            codigo=producto_admin,
            referencia="REF-100",
            descripcion_general="Taladro percutor industrial",
            departamento="Ferretería",
            precio_dolares=85.0,
            existencia=7.0,
            costo_usd_efectivo=1.0,
            rol_usuario="vendedor",
        )
    assert str(ex.value).startswith("ERR_PROD_ROL")


def test_actualizacion_de_no_admin_preserva_los_costos_almacenados(producto_admin):
    actualizar_producto(
        codigo=producto_admin,
        referencia="REF-100-B",
        descripcion_general="Taladro percutor industrial (revisado)",
        departamento="Ferretería",
        precio_dolares=95.0,
        precio_bcv=99.0,
        existencia=6.0,
        rol_usuario="vendedor",
    )
    prod = obtener_producto(producto_admin, rol_usuario="administrador")
    assert prod["referencia"] == "REF-100-B"
    assert prod["precio_dolares"] == 95.0
    assert prod["costo_usd_efectivo"] == 55.0
    assert prod["costo_usd_bcv"] == 58.5


def test_rol_admin_puede_sobrescribir_los_costos(producto_admin):
    prod = actualizar_producto(
        codigo=producto_admin,
        referencia="REF-100",
        descripcion_general="Taladro percutor industrial",
        departamento="Ferretería",
        precio_dolares=85.0,
        existencia=7.0,
        costo_usd_efectivo=61.25,
        costo_usd_bcv=64.0,
        rol_usuario="superadmin",
    )
    assert prod["costo_usd_efectivo"] == 61.25
    assert prod["costo_usd_bcv"] == 64.0


def test_actualizar_con_existencia_y_costo_ya_almacenado_no_falla(producto_admin):
    """La obligatoriedad se satisface con el costo que ya está en la base."""
    prod = actualizar_producto(
        codigo=producto_admin,
        referencia="REF-100",
        descripcion_general="Taladro percutor industrial",
        departamento="Ferretería",
        precio_dolares=85.0,
        existencia=20.0,
        rol_usuario="administrador",
    )
    assert prod["existencia"] == 20.0
    assert prod["costo_usd_efectivo"] == 55.0


def test_actualizar_con_existencia_sin_costo_previo_falla(db_temporal):
    crear_producto(
        codigo="P-VACIO",
        referencia="REF",
        descripcion_general="Producto agotado sin costo",
        departamento="Ferretería",
        existencia=0.0,
        rol_usuario="administrador",
    )
    with pytest.raises(ValueError) as ex:
        actualizar_producto(
            codigo="P-VACIO",
            referencia="REF",
            descripcion_general="Producto agotado sin costo",
            departamento="Ferretería",
            precio_dolares=5.0,
            existencia=3.0,
            rol_usuario="administrador",
        )
    assert str(ex.value).startswith("ERR_PROD_COSTO")


# ─── 4. Jerarquía Departamento → Sub-Departamento ────────────────────────────

def test_listar_departamentos_en_orden_alfabetico_estricto(db_temporal):
    for nombre in ("zapatería", "Ferretería", "alimentos", "Bazar"):
        crear_departamento(nombre)
    assert listar_departamentos() == ["alimentos", "Bazar", "Ferretería", "zapatería"]


def test_crear_departamento_es_idempotente_e_insensible_a_capitalizacion(db_temporal, conexion):
    # Sin tildes: el COLLATE NOCASE de SQLite solo plega letras ASCII.
    assert crear_departamento("Ferreteria") == "Ferreteria"
    assert crear_departamento("  FERRETERIA  ") == "Ferreteria"
    assert crear_departamento("ferreteria") == "Ferreteria"
    cursor = conexion.cursor()
    cursor.execute("SELECT COUNT(*) AS total FROM departamentos")
    assert cursor.fetchone()["total"] == 1


def test_crear_departamento_rechaza_nombre_vacio(db_temporal):
    with pytest.raises(ValueError):
        crear_departamento("   ")


def test_sub_departamentos_se_filtran_por_su_padre(db_temporal):
    crear_sub_departamento("Ferretería", "Tornillería")
    crear_sub_departamento("Ferretería", "Herramientas")
    crear_sub_departamento("Alimentos", "Bebidas")
    assert listar_sub_departamentos("Ferretería") == ["Herramientas", "Tornillería"]
    assert listar_sub_departamentos("Alimentos") == ["Bebidas"]


def test_crear_sub_departamento_crea_el_padre_faltante(db_temporal):
    crear_sub_departamento("Papeleria", "Cuadernos")
    assert "Papeleria" in listar_departamentos()
    # Idempotente y sin duplicar el padre, comparando sin distinguir mayúsculas.
    assert crear_sub_departamento("papeleria ", "cuadernos") == "Cuadernos"
    assert listar_departamentos() == ["Papeleria"]
    assert listar_sub_departamentos("PAPELERIA") == ["Cuadernos"]


def test_listar_sub_departamentos_devuelve_vacio_si_el_padre_no_existe(db_temporal):
    assert listar_sub_departamentos("Inexistente") == []
    assert listar_sub_departamentos("") == []


def test_backfill_del_catalogo_desde_productos(db_temporal, conexion):
    # Inserción directa: simula datos preexistentes de una instalación previa.
    conexion.execute(
        "INSERT INTO productos (codigo, referencia, departamento, descripcion_general, "
        "sub_departamento) VALUES ('X1', 'R', 'Electricidad', 'Cable', 'Cables')"
    )
    conexion.execute(
        "INSERT INTO productos (codigo, referencia, departamento, descripcion_general, "
        "sub_departamento) VALUES ('X2', 'R', 'Electricidad', 'Breaker', 'Protecciones')"
    )
    conexion.commit()

    sincronizar_catalogo_departamentos()
    assert listar_departamentos() == ["Electricidad"]
    assert listar_sub_departamentos("Electricidad") == ["Cables", "Protecciones"]

    # Idempotente: una segunda pasada no duplica nada.
    sincronizar_catalogo_departamentos()
    assert listar_sub_departamentos("Electricidad") == ["Cables", "Protecciones"]


def test_crear_producto_registra_su_departamento_en_el_catalogo(db_temporal):
    crear_producto(
        codigo="P-CAT",
        referencia="REF",
        descripcion_general="Producto con jerarquía nueva",
        departamento="Jardinería",
        sub_departamento="Mangueras",
        existencia=0.0,
        rol_usuario="administrador",
    )
    assert "Jardinería" in listar_departamentos()
    assert listar_sub_departamentos("Jardinería") == ["Mangueras"]


def test_actualizar_producto_registra_la_jerarquia_nueva(producto_admin):
    actualizar_producto(
        codigo=producto_admin,
        referencia="REF-100",
        descripcion_general="Taladro percutor industrial",
        departamento="Ferretería",
        sub_departamento="Taladros",
        precio_dolares=85.0,
        existencia=7.0,
        rol_usuario="administrador",
    )
    assert "Taladros" in listar_sub_departamentos("Ferretería")
    prod = obtener_producto(producto_admin, rol_usuario="administrador")
    assert prod["sub_departamento"] == "Taladros"


def test_filtro_por_sub_departamento_en_listar_productos(producto_admin):
    crear_producto(
        codigo="P-200",
        referencia="REF-200",
        descripcion_general="Juego de destornilladores",
        departamento="Ferretería",
        sub_departamento="Manuales",
        existencia=0.0,
        rol_usuario="administrador",
    )
    codigos = [
        p["codigo"]
        for p in listar_productos(filtros={"sub_departamento": ["Manuales"]}, rol_usuario="administrador")
    ]
    assert codigos == ["P-200"]


def test_las_columnas_nuevas_persisten_en_la_base(producto_admin, conexion):
    cursor = conexion.cursor()
    cursor.execute(
        "SELECT costo_usd_efectivo, costo_usd_bcv, sub_departamento, alerta_stock_minimo "
        "FROM productos WHERE codigo = ?",
        (producto_admin,),
    )
    fila = cursor.fetchone()
    assert fila["costo_usd_efectivo"] == 55.0
    assert fila["costo_usd_bcv"] == 58.5
    assert fila["sub_departamento"] == "Herramientas Eléctricas"
    assert fila["alerta_stock_minimo"] == 3
