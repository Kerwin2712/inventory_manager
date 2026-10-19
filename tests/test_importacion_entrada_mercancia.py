"""Una entrada de mercancía SUMA al stock; un catálogo o un respaldo lo FIJA.

El mismo apartado de Carga Masiva sirve para dos cosas que piden lo contrario, y
confundirlas tiene consecuencias caras en las dos direcciones:

  - Si el archivo del pedido de nueva mercancía FIJA la existencia (lo que hacía
    antes), un repuesto que tenía 5 unidades y recibe 10 queda en 10: las 5 que
    había se pierden sin aviso. El usuario del proyecto decidió expresamente
    "que sume al stock existente".

  - Si en cambio se convirtiera TODA la Carga Masiva en "sumar", reimportar un
    respaldo duplicaría las existencias de la base entera, cada vez, y sin forma
    de saber cuánto había antes para deshacerlo.

De ahí que las dos intenciones se distingan por un marcador explícito dentro
del archivo. La mitad de este archivo prueba la suma y la otra mitad prueba la
GUARDA: que un archivo sin ese marcador siga fijando.
"""
import pandas as pd
import pytest

from services import pedidos_service
from services.importacion_service import (
    MODO_FIJAR,
    MODO_SUMAR,
    detectar_modo_existencia,
    ejecutar_importacion_completa_mapeada,
    procesar_importacion_excel,
)
from services.inventario_service import crear_producto, obtener_producto

PROVEEDOR = "Distribuidora Andina"
FECHA = "17/10/2026"
CODIGO = "TUB-001"


@pytest.fixture(autouse=True)
def borradores_limpios():
    yield
    pedidos_service._sesiones.clear()


@pytest.fixture
def base(db_temporal):
    from services.cartera_service import crear_proveedor

    crear_proveedor(empresa=PROVEEDOR, telefono="0412-5550000", rif="J-123456789")
    return db_temporal


@pytest.fixture
def repuesto_con_cinco(base):
    """El escenario exacto de la decisión: un repuesto con 5 unidades en stock."""
    crear_producto(
        codigo=CODIGO,
        referencia="REF-TUB-001",
        descripcion_general="Tubo de escape universal",
        departamento="Repuestos",
        marca="Bosch",
        precio_dolares=30.0,
        existencia=5.0,
        nombre_referencia_corto="Tubo escape",
        costo_usd_efectivo=20.0,
        rol_usuario="administrador",
    )
    return CODIGO


def _archivo_de_pedido(tmp_path, codigo: str, cantidad, nombre="pedido.xlsx", **extra) -> str:
    """Un pedido de nueva mercancía ya exportado, con su hoja de resumen."""
    sesion = f"sesion-{nombre}"
    if obtener_producto(codigo) is not None:
        pedidos_service.agregar_renglon_desde_banco(
            sesion, codigo=codigo, cantidad=cantidad,
            costo_usd_efectivo=21.5, costo_usd_bcv=23.0,
            precio_usd_efectivo=35.5, precio_usd_bcv=38.25,
        )
    else:
        pedidos_service.agregar_renglon_manual(
            sesion, codigo=codigo,
            descripcion_general=extra.get("descripcion", "Pieza que todavía no existe"),
            cantidad=cantidad,
            costo_usd_efectivo=40.0, costo_usd_bcv=42.0,
            precio_usd_efectivo=70.0, precio_usd_bcv=75.0,
        )
    ruta = tmp_path / nombre
    pedidos_service.generar_archivo_pedido(sesion, str(ruta), PROVEEDOR, FECHA)
    return str(ruta)


def _archivo_de_catalogo(tmp_path, filas: list[dict], nombre="catalogo.xlsx") -> str:
    """Un archivo armado a mano: una hoja de productos y nada más."""
    ruta = tmp_path / nombre
    with pd.ExcelWriter(str(ruta), engine="openpyxl") as writer:
        pd.DataFrame(filas).to_excel(writer, sheet_name="Productos", index=False)
    return str(ruta)


# ─── La entrada de mercancía suma ────────────────────────────────────────────

def test_cinco_en_stock_mas_un_pedido_de_diez_quedan_en_quince(repuesto_con_cinco, tmp_path):
    ruta = _archivo_de_pedido(tmp_path, repuesto_con_cinco, 10)

    assert procesar_importacion_excel(ruta)["exito"] is True

    assert obtener_producto(repuesto_con_cinco)["existencia"] == 15


def test_un_producto_que_no_existia_entra_con_la_cantidad_recibida(base, tmp_path):
    """No tiene existencia previa a la que sumar: no debe fallar ni inventar
    nada, simplemente queda con las 10 unidades que llegaron."""
    ruta = _archivo_de_pedido(tmp_path, "AMO-NUEVO-77", 10)

    assert procesar_importacion_excel(ruta)["exito"] is True

    nuevo = obtener_producto("AMO-NUEVO-77")
    assert nuevo is not None
    assert nuevo["existencia"] == 10


def test_el_mismo_pedido_importado_dos_veces_suma_dos_veces(repuesto_con_cinco, tmp_path):
    """Decisión consciente: cada importación de un pedido es una entrada de
    mercancía real. Hacerlo idempotente exigiría identificar el pedido y
    recordar cuáles ya entraron —estado nuevo en la base— y además mentiría
    cuando el mismo proveedor manda dos veces la misma remesa."""
    ruta = _archivo_de_pedido(tmp_path, repuesto_con_cinco, 10)

    procesar_importacion_excel(ruta)
    procesar_importacion_excel(ruta)

    assert obtener_producto(repuesto_con_cinco)["existencia"] == 25


def test_el_camino_del_asistente_de_mapeo_tambien_suma(repuesto_con_cinco, tmp_path):
    """Es el camino que usa de verdad el botón de la interfaz: si la suma solo
    valiera para la heurística, el Administrador seguiría perdiendo el stock."""
    ruta = _archivo_de_pedido(tmp_path, repuesto_con_cinco, 10)
    mapeo = {"codigo": "Código", "existencia": "Existencia",
             "costo_usd_efectivo": "Costo USD (Efectivo)"}

    resultado = ejecutar_importacion_completa_mapeada(ruta, "Productos", mapeo)

    assert resultado["exito"] is True, resultado["mensaje"]
    assert obtener_producto(repuesto_con_cinco)["existencia"] == 15


# ─── La guarda: sin marcador se fija, como siempre ───────────────────────────

def test_un_archivo_armado_a_mano_sigue_fijando_la_existencia(repuesto_con_cinco, tmp_path):
    """La guarda contra el desastre del respaldo reimportado: un archivo sin el
    marcador entra por el camino de siempre y FIJA el número que declara."""
    ruta = _archivo_de_catalogo(tmp_path, [{
        "Código": repuesto_con_cinco,
        "Descripción General": "Tubo de escape universal",
        "Existencia": 2,
    }])

    assert procesar_importacion_excel(ruta)["exito"] is True

    assert obtener_producto(repuesto_con_cinco)["existencia"] == 2


def test_reimportar_un_respaldo_dos_veces_no_duplica_las_existencias(repuesto_con_cinco, tmp_path):
    """El desastre silencioso que esta distinción evita: con "sumar" aplicado a
    toda la Carga Masiva, cada restauración de respaldo multiplicaría el
    inventario entero."""
    ruta = _archivo_de_catalogo(tmp_path, [{
        "Código": repuesto_con_cinco,
        "Descripción General": "Tubo de escape universal",
        "Existencia": 5,
    }], nombre="respaldo.xlsx")

    procesar_importacion_excel(ruta)
    procesar_importacion_excel(ruta)
    procesar_importacion_excel(ruta)

    assert obtener_producto(repuesto_con_cinco)["existencia"] == 5


def test_una_hoja_llamada_igual_pero_sin_el_literal_no_alcanza(repuesto_con_cinco, tmp_path):
    """El nombre de una hoja es un indicio débil: cualquiera puede llamar así a
    una hoja de su propio archivo. Por eso se exige además el literal del
    marcador, que nadie escribe por accidente."""
    ruta = tmp_path / "parecido.xlsx"
    with pd.ExcelWriter(str(ruta), engine="openpyxl") as writer:
        pd.DataFrame([{
            "Código": repuesto_con_cinco,
            "Descripción General": "Tubo de escape universal",
            "Existencia": 3,
        }]).to_excel(writer, sheet_name="Productos", index=False)
        pd.DataFrame([{"Dato": "Proveedor", "Valor": PROVEEDOR}]).to_excel(
            writer, sheet_name=pedidos_service.NOMBRE_HOJA_RESUMEN, index=False
        )

    assert detectar_modo_existencia(str(ruta)) == MODO_FIJAR
    assert procesar_importacion_excel(str(ruta))["exito"] is True
    assert obtener_producto(repuesto_con_cinco)["existencia"] == 3


# ─── Detección del modo ──────────────────────────────────────────────────────

def test_el_archivo_del_pedido_se_detecta_como_entrada_de_mercancia(repuesto_con_cinco, tmp_path):
    ruta = _archivo_de_pedido(tmp_path, repuesto_con_cinco, 1)

    assert detectar_modo_existencia(ruta) == MODO_SUMAR


def test_un_archivo_cualquiera_se_detecta_como_carga_normal(base, tmp_path):
    ruta = _archivo_de_catalogo(tmp_path, [{"Código": "P-1", "Existencia": 1}])

    assert detectar_modo_existencia(ruta) == MODO_FIJAR


def test_un_archivo_ilegible_se_detecta_como_carga_normal(tmp_path):
    """Fail-closed: ante la duda se fija, que es lo que no multiplica stock."""
    roto = tmp_path / "roto.xlsx"
    roto.write_bytes(b"esto no es un libro de Excel")

    assert detectar_modo_existencia(str(roto)) == MODO_FIJAR
    assert detectar_modo_existencia(str(tmp_path / "no-existe.xlsx")) == MODO_FIJAR


def test_el_marcador_viaja_en_la_hoja_de_resumen_del_pedido(repuesto_con_cinco, tmp_path):
    """Verificable abriendo el archivo: el marcador está a la vista, y debajo la
    explicación en castellano para el Administrador que lo revisa en Excel."""
    from services.importacion_service import (
        ETIQUETA_TIPO_ARCHIVO,
        MARCADOR_ENTRADA_MERCANCIA,
    )

    ruta = _archivo_de_pedido(tmp_path, repuesto_con_cinco, 4)

    resumen = pd.read_excel(ruta, sheet_name=pedidos_service.NOMBRE_HOJA_RESUMEN)
    datos = dict(zip(resumen["Dato"], resumen["Valor"]))
    assert datos[ETIQUETA_TIPO_ARCHIVO] == MARCADOR_ENTRADA_MERCANCIA
    assert "SUMA" in datos["Efecto al importar"]


def test_el_nombre_de_la_hoja_y_el_marcador_no_se_duplican_entre_modulos():
    """`pedidos_service` escribe el marcador que `importacion_service` lee: si
    cada uno tuviera su propio literal, el día que uno cambie los archivos
    dejarían de sumar y no habría ningún error que lo delatara."""
    from services import importacion_service

    assert pedidos_service.NOMBRE_HOJA_RESUMEN is importacion_service.NOMBRE_HOJA_ENTRADA_MERCANCIA


# ─── La suma no pisa lo demás ────────────────────────────────────────────────

def test_al_sumar_se_conservan_los_demas_datos_del_producto(repuesto_con_cinco, tmp_path):
    """La suma es solo sobre la existencia: el resto de la ficha se actualiza
    con lo que trae el pedido, como en cualquier importación."""
    ruta = _archivo_de_pedido(tmp_path, repuesto_con_cinco, 10)

    procesar_importacion_excel(ruta)

    prod = obtener_producto(repuesto_con_cinco, rol_usuario="administrador")
    assert prod["existencia"] == 15
    assert prod["precio_dolares"] == 35.5
    assert prod["costo_usd_efectivo"] == 21.5
    assert prod["referencia"] == "REF-TUB-001"
