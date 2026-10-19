"""El Excel del pedido tiene que volver a entrar por la Carga Masiva de Datos.

Requisito duro de la Nueva Función 6: el archivo que genera el empleado lo
ingresa después el Administrador por el apartado de Carga Masiva ya existente,
*sin mapear columnas a mano*. Estos tests cierran el círculo de verdad —generan
el archivo y lo pasan por el lector real de la importación— porque es la única
forma de detectar que el formato se bifurcó: un encabezado renombrado en
`importacion_service` que acá quedó viejo no rompe ninguna otra prueba, el
archivo simplemente se importa vacío o con columnas ignoradas.
"""
import pytest

from services import pedidos_service
from services.importacion_service import (
    CAMPOS_PRODUCTO_MAPEO,
    _ALIAS_CAMPO_PRODUCTO,
    detectar_hoja_productos,
    limpiar_clave,
    listar_hojas_excel,
    obtener_columnas_y_muestra,
    procesar_importacion_excel,
    sugerir_mapeo_columnas,
)

PROVEEDOR = "Distribuidora Andina"
FECHA = "17/10/2026"


@pytest.fixture(autouse=True)
def borradores_limpios():
    yield
    pedidos_service._sesiones.clear()


@pytest.fixture
def banco_de_datos(db_temporal):
    """Un proveedor registrado y un item en el banco de datos, el escenario del
    PDF: el empleado ubica la pieza ya registrada y solo completa sus casillas."""
    from services.cartera_service import crear_proveedor
    from services.inventario_service import crear_producto

    prov = crear_proveedor(empresa=PROVEEDOR, telefono="0412-5550000", rif="J-123456789")
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
    return prov


@pytest.fixture
def pedido_armado(banco_de_datos):
    """Pedido con un item del banco (marca cambiada, como permite el PDF) y una
    pieza nueva dada de alta a mano."""
    pedidos_service.agregar_renglon_desde_banco(
        "sesion-1", codigo="TUB-001", cantidad=6,
        costo_usd_efectivo=21.5, costo_usd_bcv=23.0,
        precio_usd_efectivo=35.5, precio_usd_bcv=38.25,
        marca="Monroe",
    )
    pedidos_service.agregar_renglon_manual(
        "sesion-1", codigo="AMO-NUEVO-77",
        descripcion_general="Amortiguador trasero reforzado",
        referencia="REF-AMO-77",
        departamento="Suspensión",
        codigo_barras="7599999999999",
        cantidad=2,
        costo_usd_efectivo=40.0, costo_usd_bcv=42.0,
        precio_usd_efectivo=70.0, precio_usd_bcv=75.0,
        marca="Monroe",
    )
    return "sesion-1"


@pytest.fixture
def archivo_pedido(pedido_armado, tmp_path):
    ruta = tmp_path / "pedido.xlsx"
    pedidos_service.generar_archivo_pedido(pedido_armado, str(ruta), PROVEEDOR, FECHA)
    return str(ruta)


# ── El formato se deriva de la importación, no se repite ─────────────────────

def test_cada_encabezado_generado_es_un_alias_que_la_importacion_reconoce():
    """Si alguien renombra una columna en `importacion_service`, este test cae
    acá en vez de dejar un archivo que se importa con columnas ignoradas."""
    for campo, _etiqueta, _obligatorio in CAMPOS_PRODUCTO_MAPEO:
        encabezado = pedidos_service.ENCABEZADO_POR_CAMPO[campo]
        assert limpiar_clave(encabezado) in _ALIAS_CAMPO_PRODUCTO[campo], (
            f"el encabezado '{encabezado}' no es un alias reconocido para '{campo}'"
        )


def test_las_columnas_informativas_no_colisionan_con_ningun_campo_de_la_importacion():
    """Lo que queda informativo (hoy solo la Fecha de Recepción) viaja para que
    el Administrador supervise el pedido; no debe ser leído como otro campo."""
    alias_conocidos = {a for alias in _ALIAS_CAMPO_PRODUCTO.values() for a in alias}

    for encabezado in pedidos_service.ENCABEZADOS_INFORMATIVOS:
        assert limpiar_clave(encabezado) not in alias_conocidos


def test_los_costos_y_el_sub_departamento_viajan_como_columnas_derivadas():
    """Dejaron de ser informativas: la Carga Masiva ya declara esos tres campos,
    así que el encabezado se deriva de ella y el dato entra en la ficha del
    producto en vez de quedar como información para retipear a mano."""
    for campo in ("sub_departamento", "costo_usd_efectivo", "costo_usd_bcv"):
        assert campo in pedidos_service.ENCABEZADO_POR_CAMPO
        assert pedidos_service.ENCABEZADO_POR_CAMPO[campo] in pedidos_service.ENCABEZADOS_PEDIDO
        assert pedidos_service.ENCABEZADO_POR_CAMPO[campo] not in pedidos_service.ENCABEZADOS_INFORMATIVOS


def test_el_encabezado_de_las_tres_columnas_nuevas_no_cambio():
    """Los archivos de pedido ya generados y guardados por ahí tienen que
    seguir entrando —y ahora además con sus costos—, así que el encabezado
    derivado debe ser el mismo texto que se emitía cuando era informativo."""
    assert pedidos_service.ENCABEZADO_POR_CAMPO["sub_departamento"] == "Sub-Departamento"
    assert pedidos_service.ENCABEZADO_POR_CAMPO["costo_usd_efectivo"] == "Costo USD (Efectivo)"
    assert pedidos_service.ENCABEZADO_POR_CAMPO["costo_usd_bcv"] == "Costo USD (BCV)"


def test_el_pedido_no_duplica_ninguna_columna():
    """Un encabezado repetido haría que pandas escribiera dos columnas con el
    mismo nombre y la importación leyera una sola, perdiendo datos en silencio."""
    encabezados = list(pedidos_service.ENCABEZADOS_PEDIDO)
    assert len(encabezados) == len(set(encabezados))


def test_la_hoja_del_pedido_es_la_que_detecta_la_importacion(archivo_pedido):
    assert detectar_hoja_productos(archivo_pedido) == pedidos_service.NOMBRE_HOJA_PEDIDO


def test_el_resumen_viaja_en_una_hoja_aparte_con_el_proveedor_y_la_fecha(archivo_pedido):
    import pandas as pd

    assert pedidos_service.NOMBRE_HOJA_RESUMEN in listar_hojas_excel(archivo_pedido)

    resumen = pd.read_excel(archivo_pedido, sheet_name=pedidos_service.NOMBRE_HOJA_RESUMEN)
    datos = dict(zip(resumen["Dato"], resumen["Valor"]))
    assert datos["Proveedor"] == PROVEEDOR
    assert datos["Fecha de Recepción"] == FECHA
    assert datos["Unidades totales"] == 8


def test_el_asistente_de_mapeo_prerrellena_todos_los_campos_sin_ayuda(archivo_pedido):
    """"Sin mapeo manual" quiere decir esto: el asistente de la Carga Masiva
    reconoce por sí solo a qué campo va cada columna del archivo."""
    columnas = obtener_columnas_y_muestra(archivo_pedido, pedidos_service.NOMBRE_HOJA_PEDIDO)["columnas"]
    sugerido = sugerir_mapeo_columnas(columnas)

    for campo, _etiqueta, _obligatorio in CAMPOS_PRODUCTO_MAPEO:
        assert campo in sugerido, f"el asistente no reconoció la columna del campo '{campo}'"


# ── Círculo cerrado: generar → importar ──────────────────────────────────────

def test_el_archivo_generado_entra_por_la_carga_masiva_con_los_valores_intactos(archivo_pedido):
    from services.inventario_service import obtener_producto

    resultado = procesar_importacion_excel(archivo_pedido)

    assert resultado["exito"] is True, resultado["mensaje"]
    assert resultado["detalles"]["productos"] == 2

    tubo = obtener_producto("TUB-001", rol_usuario="administrador")
    assert tubo["precio_dolares"] == 35.5
    assert tubo["precio_bcv"] == 38.25
    assert tubo["existencia"] == 6
    assert tubo["marca"] == "Monroe"
    assert tubo["referencia"] == "REF-TUB-001"
    assert tubo["departamento"] == "Repuestos"
    assert tubo["descripcion_general"] == "Tubo de escape universal"
    assert tubo["nombre_referencia_corto"] == "Tubo escape"
    assert tubo["codigo_barras"] == "7591234567890"
    # Los costos del pedido ya no son informativos: quedan en la ficha, que es
    # lo que evita que el Administrador los retipee uno por uno.
    assert tubo["costo_usd_efectivo"] == 21.5
    assert tubo["costo_usd_bcv"] == 23.0
    assert tubo["sub_departamento"] == "Escape"


def test_el_proveedor_del_pedido_queda_enlazado_al_importar(archivo_pedido, banco_de_datos):
    from services.inventario_service import obtener_producto

    procesar_importacion_excel(archivo_pedido)

    assert obtener_producto("TUB-001")["proveedor_id"] == banco_de_datos["id"]


def test_la_pieza_dada_de_alta_a_mano_tambien_entra_por_la_carga_masiva(archivo_pedido):
    from services.inventario_service import obtener_producto

    procesar_importacion_excel(archivo_pedido)

    nuevo = obtener_producto("AMO-NUEVO-77")
    assert nuevo is not None
    assert nuevo["descripcion_general"] == "Amortiguador trasero reforzado"
    assert nuevo["existencia"] == 2
    assert nuevo["precio_dolares"] == 70.0
    assert nuevo["departamento"] == "Suspensión"


def test_la_hoja_de_resumen_no_se_importa_como_productos_ni_como_proveedores(archivo_pedido):
    """El libro trae dos hojas; la Carga Masiva solo debe procesar la de
    productos (si leyera el resumen, aparecerían filas basura)."""
    resultado = procesar_importacion_excel(archivo_pedido)

    assert resultado["detalles"] == {"productos": 2, "clientes": 0, "proveedores": 0}


# ── Validaciones al cerrar el pedido ─────────────────────────────────────────

def test_un_pedido_vacio_no_genera_archivo(db_temporal, tmp_path):
    ruta = tmp_path / "vacio.xlsx"

    with pytest.raises(ValueError, match="ERR_PEDIDO_VACIO"):
        pedidos_service.generar_archivo_pedido("sesion-vacia", str(ruta), PROVEEDOR, FECHA)

    assert not ruta.exists()


def test_cerrar_sin_proveedor_no_genera_archivo(pedido_armado, tmp_path):
    ruta = tmp_path / "sin_proveedor.xlsx"

    with pytest.raises(ValueError, match="ERR_PEDIDO_PROV"):
        pedidos_service.generar_archivo_pedido(pedido_armado, str(ruta), "", FECHA)

    assert not ruta.exists()


def test_cerrar_sin_fecha_valida_no_genera_archivo(pedido_armado, tmp_path):
    ruta = tmp_path / "sin_fecha.xlsx"

    with pytest.raises(ValueError, match="ERR_PEDIDO_FECHA"):
        pedidos_service.generar_archivo_pedido(pedido_armado, str(ruta), PROVEEDOR, "31/02/2026")

    assert not ruta.exists()


def test_generar_el_archivo_no_altera_la_base_de_datos(pedido_armado, tmp_path):
    """La garantía del módulo: el pedido es un documento para el Administrador.
    Hasta que él lo importe, el inventario queda exactamente como estaba."""
    from core.database import get_connection

    def foto():
        with get_connection() as conn:
            return [
                tuple(f) for f in conn.execute(
                    "SELECT codigo, existencia, precio_dolares, precio_bcv, marca FROM productos ORDER BY codigo"
                ).fetchall()
            ]

    antes = foto()

    pedidos_service.generar_archivo_pedido(pedido_armado, str(tmp_path / "p.xlsx"), PROVEEDOR, FECHA)

    assert foto() == antes
    assert antes == [("TUB-001", 4.0, 30.0, 33.0, "Bosch")]


def test_el_borrador_sobrevive_a_la_exportacion_para_poder_corregir(pedido_armado, tmp_path):
    pedidos_service.generar_archivo_pedido(pedido_armado, str(tmp_path / "p.xlsx"), PROVEEDOR, FECHA)

    assert len(pedidos_service.obtener_renglones(pedido_armado)) == 2


def test_el_nombre_sugerido_identifica_al_proveedor_y_el_momento():
    nombre = pedidos_service.nombre_archivo_sugerido("Distribuidora Andina")

    assert nombre.startswith("Pedido_Nueva_Mercancia_Distribuidora_Andina_")
    assert nombre.endswith(".xlsx")
