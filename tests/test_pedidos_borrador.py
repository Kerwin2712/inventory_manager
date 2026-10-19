"""Borrador del Generador de Archivo por Nueva Mercancía (Nueva Función 6).

Lo que se protege acá es la garantía que hace que este módulo pueda estar
disponible para TODOS los roles: armar un pedido no escribe nada en la base de
datos (no crea productos, no mueve existencias). Si eso dejara de ser cierto, un
vendedor estaría modificando el stock por la puerta de atrás.

El segundo invariante es el aislamiento por `session_id`: la aplicación Flet
atiende varias sesiones en el mismo proceso, así que dos usuarios armando
pedidos a la vez no pueden verse ni pisarse los renglones.
"""
import pytest

from services import pedidos_service


@pytest.fixture
def proveedor_registrado(db_temporal):
    from services.cartera_service import crear_proveedor

    crear_proveedor(empresa="Distribuidora Andina", telefono="0412-5550000", rif="J-123456789")
    return "Distribuidora Andina"


@pytest.fixture
def producto_banco(db_temporal):
    """Item ya registrado en el banco de datos (el caso que contempla el PDF)."""
    from services.inventario_service import crear_producto

    crear_producto(
        codigo="TUB-001",
        referencia="REF-TUB-001",
        descripcion_general="Tubo de escape universal",
        departamento="Repuestos",
        sub_departamento="Escape",
        marca="Bosch",
        precio_dolares=30.0,
        precio_bcv=33.0,
        existencia=4.0,
        codigo_barras="7591234567890",
        nombre_referencia_corto="Tubo escape",
        costo_usd_efectivo=20.0,
        rol_usuario="administrador",
    )
    return "TUB-001"


@pytest.fixture(autouse=True)
def borradores_limpios():
    """Cada test arranca con los borradores en blanco: el estado por sesión vive
    en memoria del módulo y sobreviviría de un test al siguiente."""
    yield
    pedidos_service._sesiones.clear()


def _agregar_item(session_id, codigo, cantidad=2):
    return pedidos_service.agregar_renglon_desde_banco(
        session_id,
        codigo=codigo,
        cantidad=cantidad,
        costo_usd_efectivo=21.5,
        costo_usd_bcv=23.0,
        precio_usd_efectivo=35.0,
        precio_usd_bcv=38.0,
    )


# ── Armado desde el banco de datos ───────────────────────────────────────────

def test_el_renglon_trae_del_banco_todo_lo_que_no_se_vuelve_a_escribir(producto_banco):
    renglon = _agregar_item("sesion-1", producto_banco)

    assert renglon["referencia"] == "REF-TUB-001"
    assert renglon["departamento"] == "Repuestos"
    assert renglon["sub_departamento"] == "Escape"
    assert renglon["descripcion_general"] == "Tubo de escape universal"
    assert renglon["nombre_referencia_corto"] == "Tubo escape"
    assert renglon["codigo_barras"] == "7591234567890"
    assert renglon["origen"] == "banco"


def test_la_marca_viene_prerrellenada_con_la_del_producto_registrado(producto_banco):
    renglon = _agregar_item("sesion-1", producto_banco)

    assert renglon["marca"] == "Bosch"


def test_la_marca_prerrellenada_es_editable_porque_la_pieza_puede_llegar_de_otra(producto_banco):
    """El PDF pide la Marca como casilla a llenar: una misma pieza puede llegar
    de otro fabricante en este pedido."""
    renglon = pedidos_service.agregar_renglon_desde_banco(
        "sesion-1", codigo=producto_banco, cantidad=1,
        costo_usd_efectivo=10, costo_usd_bcv=11,
        precio_usd_efectivo=20, precio_usd_bcv=22,
        marca="Monroe",
    )

    assert renglon["marca"] == "Monroe"


def test_un_codigo_inexistente_en_el_banco_es_rechazado(db_temporal):
    with pytest.raises(ValueError, match="ERR_PEDIDO_ITEM"):
        _agregar_item("sesion-1", "NO-EXISTE")


def test_repetir_un_codigo_acumula_la_cantidad_en_un_solo_renglon(producto_banco):
    """La Carga Masiva hace INSERT OR REPLACE: dos filas del mismo código no
    suman existencias, la segunda sobrescribe a la primera. El borrador debe
    consolidarlas para que el archivo salga con la cantidad total real."""
    _agregar_item("sesion-1", producto_banco, cantidad=2)
    _agregar_item("sesion-1", producto_banco, cantidad=3)

    renglones = pedidos_service.obtener_renglones("sesion-1")
    assert len(renglones) == 1
    assert renglones[0]["cantidad"] == 5


# ── Aislamiento por sesión ───────────────────────────────────────────────────

def test_el_borrador_de_una_sesion_no_se_ve_ni_se_pisa_desde_otra(producto_banco):
    _agregar_item("sesion-vendedor-a", producto_banco, cantidad=7)

    assert pedidos_service.obtener_renglones("sesion-vendedor-b") == []

    _agregar_item("sesion-vendedor-b", producto_banco, cantidad=1)

    assert pedidos_service.obtener_renglones("sesion-vendedor-a")[0]["cantidad"] == 7
    assert pedidos_service.obtener_renglones("sesion-vendedor-b")[0]["cantidad"] == 1


def test_vaciar_un_pedido_no_toca_el_de_la_otra_sesion(producto_banco):
    _agregar_item("sesion-a", producto_banco)
    _agregar_item("sesion-b", producto_banco)

    pedidos_service.vaciar_pedido("sesion-a")

    assert pedidos_service.obtener_renglones("sesion-a") == []
    assert len(pedidos_service.obtener_renglones("sesion-b")) == 1


def test_limpiar_sesion_libera_el_borrador_al_desconectarse(producto_banco):
    _agregar_item("sesion-a", producto_banco)

    pedidos_service.limpiar_sesion("sesion-a")

    assert "sesion-a" not in pedidos_service._sesiones


# ── Validaciones ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("cantidad", [0, -3, "", None, "dos"])
def test_la_cantidad_debe_ser_un_numero_mayor_a_cero(producto_banco, cantidad):
    with pytest.raises(ValueError, match="ERR_PEDIDO_CANT"):
        _agregar_item("sesion-1", producto_banco, cantidad=cantidad)


@pytest.mark.parametrize(
    "campo", ["costo_usd_efectivo", "costo_usd_bcv", "precio_usd_efectivo", "precio_usd_bcv"]
)
def test_los_costos_y_precios_no_pueden_ser_negativos(producto_banco, campo):
    valores = {
        "costo_usd_efectivo": 1.0, "costo_usd_bcv": 1.0,
        "precio_usd_efectivo": 2.0, "precio_usd_bcv": 2.0,
    }
    valores[campo] = -1

    with pytest.raises(ValueError, match="ERR_PEDIDO_MONTO"):
        pedidos_service.agregar_renglon_desde_banco(
            "sesion-1", codigo=producto_banco, cantidad=1, **valores
        )


@pytest.mark.parametrize(
    "campo", ["costo_usd_efectivo", "costo_usd_bcv", "precio_usd_efectivo", "precio_usd_bcv"]
)
def test_los_costos_y_precios_deben_ser_numericos(producto_banco, campo):
    valores = {
        "costo_usd_efectivo": 1.0, "costo_usd_bcv": 1.0,
        "precio_usd_efectivo": 2.0, "precio_usd_bcv": 2.0,
    }
    valores[campo] = "muy caro"

    with pytest.raises(ValueError, match="ERR_PEDIDO_MONTO"):
        pedidos_service.agregar_renglon_desde_banco(
            "sesion-1", codigo=producto_banco, cantidad=1, **valores
        )


def test_un_monto_vacio_se_registra_como_cero_para_que_el_admin_lo_complete(producto_banco):
    renglon = pedidos_service.agregar_renglon_desde_banco(
        "sesion-1", codigo=producto_banco, cantidad=1,
        costo_usd_efectivo="", costo_usd_bcv=None,
        precio_usd_efectivo=10, precio_usd_bcv=11,
    )

    assert renglon["costo_usd_efectivo"] == 0.0
    assert renglon["costo_usd_bcv"] == 0.0


def test_el_proveedor_es_obligatorio_al_cerrar_el_pedido():
    with pytest.raises(ValueError, match="ERR_PEDIDO_PROV"):
        pedidos_service.validar_proveedor("   ")


def test_la_fecha_de_recepcion_es_obligatoria_al_cerrar_el_pedido():
    with pytest.raises(ValueError, match="ERR_PEDIDO_FECHA"):
        pedidos_service.validar_fecha_recepcion("")


def test_la_fecha_de_recepcion_acepta_el_formato_dia_mes_anio():
    assert pedidos_service.validar_fecha_recepcion(" 17/10/2026 ") == "17/10/2026"


@pytest.mark.parametrize("fecha", ["31/02/2026", "2026-10-17", "17-10-2026", "mañana"])
def test_una_fecha_inexistente_o_con_otro_formato_es_rechazada(fecha):
    """`31/02/2026` es el caso que un split por '/' aceptaría sin chistar."""
    with pytest.raises(ValueError, match="ERR_PEDIDO_FECHA"):
        pedidos_service.validar_fecha_recepcion(fecha)


# ── Edición y borrado de renglones ───────────────────────────────────────────

def test_editar_un_renglon_cambia_solo_las_casillas_del_pedido(producto_banco):
    _agregar_item("sesion-1", producto_banco, cantidad=2)

    renglon = pedidos_service.editar_renglon(
        "sesion-1", 0, cantidad=9, marca="Monroe", costo_usd_efectivo="19,5"
    )

    assert renglon["cantidad"] == 9
    assert renglon["marca"] == "Monroe"
    assert renglon["costo_usd_efectivo"] == 19.5
    assert renglon["descripcion_general"] == "Tubo de escape universal"


def test_editar_un_renglon_revalida_la_cantidad(producto_banco):
    _agregar_item("sesion-1", producto_banco)

    with pytest.raises(ValueError, match="ERR_PEDIDO_CANT"):
        pedidos_service.editar_renglon("sesion-1", 0, cantidad=0)


def test_no_se_pueden_editar_los_datos_traidos_del_banco_de_datos(producto_banco):
    _agregar_item("sesion-1", producto_banco)

    with pytest.raises(ValueError, match="ERR_PEDIDO_CAMPO"):
        pedidos_service.editar_renglon("sesion-1", 0, descripcion_general="otra cosa")


def test_editar_una_posicion_inexistente_es_un_error_explicito(producto_banco):
    with pytest.raises(ValueError, match="ERR_PEDIDO_INDICE"):
        pedidos_service.editar_renglon("sesion-1", 5, cantidad=1)


def test_quitar_un_renglon_lo_saca_del_pedido(producto_banco, db_temporal):
    from services.inventario_service import crear_producto

    crear_producto(
        codigo="FIL-002", referencia="REF-FIL", descripcion_general="Filtro de aceite",
        departamento="Repuestos", precio_dolares=5.0, rol_usuario="administrador",
    )
    _agregar_item("sesion-1", producto_banco)
    _agregar_item("sesion-1", "FIL-002")

    assert pedidos_service.quitar_renglon("sesion-1", 0) is True

    renglones = pedidos_service.obtener_renglones("sesion-1")
    assert [r["codigo"] for r in renglones] == ["FIL-002"]
    assert pedidos_service.quitar_renglon("sesion-1", 7) is False


# ── Alta manual de mercancía que no está en el banco ─────────────────────────

def test_el_alta_manual_permite_mercancia_nueva_sin_registrarla_en_el_sistema(db_temporal):
    """Un pedido real trae piezas nuevas, y el empleado no puede crear
    productos: el renglón manual existe para no dejarlo bloqueado."""
    renglon = pedidos_service.agregar_renglon_manual(
        "sesion-1",
        codigo="NUEVO-77",
        descripcion_general="Amortiguador trasero reforzado",
        cantidad=4,
        costo_usd_efectivo=40, costo_usd_bcv=44,
        precio_usd_efectivo=70, precio_usd_bcv=77,
        marca="Monroe",
    )

    assert renglon["origen"] == "manual"
    assert renglon["nombre_referencia_corto"] == "Amortiguador trasero reforzado"[:30]
    assert renglon["departamento"] == "GENERAL"

    from core.database import get_connection
    with get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM productos WHERE codigo = 'NUEVO-77'").fetchone()[0] == 0


@pytest.mark.parametrize("faltante", ["codigo", "descripcion_general"])
def test_el_alta_manual_exige_los_campos_que_la_importacion_necesita(db_temporal, faltante):
    datos = {
        "codigo": "NUEVO-77",
        "descripcion_general": "Amortiguador trasero",
        "cantidad": 1,
        "costo_usd_efectivo": 1, "costo_usd_bcv": 1,
        "precio_usd_efectivo": 2, "precio_usd_bcv": 2,
    }
    datos[faltante] = "   "

    with pytest.raises(ValueError, match="ERR_PEDIDO_MANUAL"):
        pedidos_service.agregar_renglon_manual("sesion-1", **datos)


# ── El pedido no altera la base de datos ─────────────────────────────────────

def _foto_del_inventario():
    from core.database import get_connection

    with get_connection() as conn:
        filas = conn.execute(
            "SELECT codigo, existencia, precio_dolares, precio_bcv, marca FROM productos ORDER BY codigo"
        ).fetchall()
        return [tuple(f) for f in filas]


def test_armar_el_pedido_no_crea_productos_ni_mueve_existencias(producto_banco, proveedor_registrado):
    antes = _foto_del_inventario()

    _agregar_item("sesion-1", producto_banco, cantidad=50)
    pedidos_service.agregar_renglon_manual(
        "sesion-1", codigo="NUEVO-88", descripcion_general="Pieza nueva", cantidad=10,
        costo_usd_efectivo=5, costo_usd_bcv=6, precio_usd_efectivo=9, precio_usd_bcv=10,
    )
    pedidos_service.editar_renglon("sesion-1", 0, cantidad=99, marca="Otra")
    pedidos_service.quitar_renglon("sesion-1", 1)

    assert _foto_del_inventario() == antes, "el borrador del pedido no debe tocar la base"
    assert len(antes) == 1


# ── Búsqueda en el banco de datos ────────────────────────────────────────────

def test_la_busqueda_de_items_no_expone_los_costos_del_negocio(producto_banco):
    """El vendedor ubica el item por código, descripción o referencia, pero los
    costos almacenados no deben salir de la base hacia este flujo."""
    resultados = pedidos_service.buscar_items_para_pedido("Tubo")

    assert [r["codigo"] for r in resultados] == ["TUB-001"]
    assert "costo_usd_efectivo" not in resultados[0]
    assert "costo_usd_bcv" not in resultados[0]


def test_se_puede_ubicar_el_item_por_codigo_referencia_o_descripcion(producto_banco):
    for termino in ("TUB-001", "REF-TUB-001", "escape universal"):
        assert [r["codigo"] for r in pedidos_service.buscar_items_para_pedido(termino)] == ["TUB-001"]


def test_un_vendedor_arma_el_pedido_completo_sin_permisos_de_costos(producto_banco):
    """El punto del requisito: el empleado registra la mercancía que llegó sin
    tener permiso para modificar el stock. Nada en el armado del pedido depende
    de un rol administrador."""
    renglon = pedidos_service.agregar_renglon_desde_banco(
        "sesion-vendedor", codigo=producto_banco, cantidad=3,
        costo_usd_efectivo=22, costo_usd_bcv=24,
        precio_usd_efectivo=40, precio_usd_bcv=44,
    )

    assert renglon["cantidad"] == 3
    # El costo del renglón es el de ESTA entrada de mercancía, no el almacenado.
    assert renglon["costo_usd_efectivo"] == 22
    assert pedidos_service.total_unidades("sesion-vendedor") == 3
    assert pedidos_service.total_costo_efectivo("sesion-vendedor") == 66.0
