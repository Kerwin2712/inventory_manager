"""La Carga Masiva lee los COSTOS y el SUB-DEPARTAMENTO.

Las tres columnas existen en `productos` desde la migración de octubre 2026,
pero la importación no las leía ni las escribía: los costos que el empleado
anotaba en el pedido de nueva mercancía llegaban al Administrador como
información meramente visual y alguien los retipeaba a mano en la ficha de cada
producto. El usuario del proyecto pidió expresamente agregarlos.

Lo delicado no es leer tres columnas más, es lo que pasa con los archivos que
ya existen. Un respaldo o una plantilla de catálogo armada antes de este cambio
NO menciona esas columnas, y `INSERT OR REPLACE` borra la fila entera y la
vuelve a insertar: sin cuidado, reimportar un archivo viejo borraría en
silencio los costos de todo el catálogo. De ahí que la mitad de este archivo
pruebe lo que el archivo NO trae.
"""
import pandas as pd
import pytest

from core.database import get_connection
from services.importacion_service import (
    CAMPOS_PRODUCTO_MAPEO,
    ejecutar_importacion_completa_mapeada,
    procesar_importacion_excel,
    sugerir_mapeo_columnas,
)
from services.inventario_service import crear_producto, obtener_producto

HOJA = "Productos"


def _escribir_excel(ruta, filas: list[dict], hoja: str = HOJA) -> str:
    """Un libro de una sola hoja con las columnas que traigan `filas`."""
    with pd.ExcelWriter(str(ruta), engine="openpyxl") as writer:
        pd.DataFrame(filas).to_excel(writer, sheet_name=hoja, index=False)
    return str(ruta)


def _costos(codigo: str) -> dict:
    """Los tres campos nuevos tal como quedaron en la base (sin pasar por el
    filtro de rol: acá se verifica la escritura, no los permisos)."""
    with get_connection() as conn:
        fila = conn.execute(
            "SELECT costo_usd_efectivo, costo_usd_bcv, sub_departamento, "
            "alerta_stock_minimo, existencia FROM productos WHERE codigo = ?",
            (codigo,),
        ).fetchone()
    return dict(fila) if fila is not None else {}


@pytest.fixture
def producto_con_costos(db_temporal):
    """Un producto ya registrado con sus costos puestos por un administrador."""
    crear_producto(
        codigo="TUB-001",
        referencia="REF-TUB-001",
        descripcion_general="Tubo de escape universal",
        departamento="Repuestos",
        sub_departamento="Escape",
        marca="Bosch",
        precio_dolares=30.0,
        precio_bcv=33.0,
        existencia=5.0,
        nombre_referencia_corto="Tubo escape",
        costo_usd_efectivo=20.0,
        costo_usd_bcv=21.0,
        alerta_stock_minimo=3,
        rol_usuario="administrador",
    )
    return "TUB-001"


# ─── Las tres columnas se importan ───────────────────────────────────────────

def test_las_tres_columnas_nuevas_quedan_en_la_base(db_temporal, tmp_path):
    ruta = _escribir_excel(tmp_path / "catalogo.xlsx", [{
        "Código": "P-1",
        "Descripción General": "Taladro percutor",
        "Departamento": "Ferretería",
        "Sub-Departamento": "Herramientas Eléctricas",
        "Precio USD (Efectivo)": 85.0,
        "Costo USD (Efectivo)": 55.0,
        "Costo USD (BCV)": 58.5,
        "Existencia": 7,
    }])

    resultado = procesar_importacion_excel(ruta)

    assert resultado["exito"] is True, resultado["mensaje"]
    fila = _costos("P-1")
    assert fila["costo_usd_efectivo"] == 55.0
    assert fila["costo_usd_bcv"] == 58.5
    assert fila["sub_departamento"] == "Herramientas Eléctricas"


def test_el_asistente_de_mapeo_reconoce_las_tres_columnas_nuevas(tmp_path):
    """El asistente pre-sugiere el mapeo: si no reconociera estos encabezados,
    el Administrador tendría que elegirlos a mano en cada importación."""
    ruta = _escribir_excel(tmp_path / "c.xlsx", [{
        "Código": "P-1", "Sub-Departamento": "Escape",
        "Costo USD (Efectivo)": 1.0, "Costo USD (BCV)": 2.0,
    }])
    columnas = [str(c) for c in pd.read_excel(ruta, sheet_name=HOJA).columns]

    sugerido = sugerir_mapeo_columnas(columnas)

    assert sugerido["sub_departamento"] == "Sub-Departamento"
    assert sugerido["costo_usd_efectivo"] == "Costo USD (Efectivo)"
    assert sugerido["costo_usd_bcv"] == "Costo USD (BCV)"


def test_los_tres_campos_nuevos_estan_declarados_en_el_mapeo():
    campos = {campo for campo, _etiqueta, _obligatorio in CAMPOS_PRODUCTO_MAPEO}
    assert {"sub_departamento", "costo_usd_efectivo", "costo_usd_bcv"} <= campos


def test_el_mapeo_explicito_tambien_escribe_los_costos(db_temporal, tmp_path):
    """El camino que usa de verdad la interfaz es el del asistente de mapeo; si
    los costos solo entraran por la heurística, el botón de la vista no los
    cargaría."""
    ruta = _escribir_excel(tmp_path / "raro.xlsx", [{
        "clave": "P-9", "detalle": "Pieza con encabezados raros",
        "lo que cuesta": 12.75, "lo que cuesta en bcv": 13.5,
        "subrubro": "Frenos", "cuantos": 4,
    }])
    mapeo = {
        "codigo": "clave",
        "descripcion_general": "detalle",
        "costo_usd_efectivo": "lo que cuesta",
        "costo_usd_bcv": "lo que cuesta en bcv",
        "sub_departamento": "subrubro",
        "existencia": "cuantos",
    }

    resultado = ejecutar_importacion_completa_mapeada(ruta, HOJA, mapeo)

    assert resultado["exito"] is True, resultado["mensaje"]
    fila = _costos("P-9")
    assert fila["costo_usd_efectivo"] == 12.75
    assert fila["costo_usd_bcv"] == 13.5
    assert fila["sub_departamento"] == "Frenos"


# ─── Qué es un costo válido lo define el dominio ─────────────────────────────

@pytest.mark.parametrize("celda,esperado", [("20,50", 20.5), ("20.50", 20.5), ("$ 18,25", 18.25)])
def test_un_costo_con_coma_decimal_entra_bien(db_temporal, tmp_path, celda, esperado):
    """La coma decimal es la que escribe el usuario venezolano. La regla no se
    reimplementa acá: la define `core.models.normalizar_costo`, la misma que
    valida el formulario de Inventario."""
    ruta = _escribir_excel(tmp_path / "coma.xlsx", [{
        "Código": "P-COMA", "Descripción General": "Costo con coma",
        "Costo USD (Efectivo)": celda, "Existencia": 2,
    }])

    resultado = procesar_importacion_excel(ruta)

    assert resultado["exito"] is True, resultado["mensaje"]
    assert _costos("P-COMA")["costo_usd_efectivo"] == esperado


@pytest.mark.parametrize("celda", [-5, "-5", "abc"])
def test_un_costo_invalido_rechaza_el_archivo_completo(db_temporal, tmp_path, celda):
    """Transaccional: una sola fila con costo inválido deja la base intacta."""
    ruta = _escribir_excel(tmp_path / "malo.xlsx", [{
        "Código": "P-MALO", "Descripción General": "Costo inválido",
        "Costo USD (Efectivo)": celda, "Existencia": 1,
    }])

    resultado = procesar_importacion_excel(ruta)

    assert resultado["exito"] is False
    assert "Costo USD Efectivo" in resultado["mensaje"]
    assert obtener_producto("P-MALO") is None


def test_una_fila_con_existencia_y_el_costo_en_blanco_se_rechaza(db_temporal, tmp_path):
    """Decisión documentada: cuando el archivo SÍ trae la columna de costo, una
    fila con existencia y el costo en blanco se rechaza con un mensaje claro en
    vez de importar un producto que el dominio considera inválido (regla
    `core.models.validar_costo_obligatorio`) y que después ningún formulario
    dejaría volver a guardar."""
    ruta = _escribir_excel(tmp_path / "blanco.xlsx", [{
        "Código": "P-BLANCO", "Descripción General": "Con stock y sin costo",
        "Costo USD (Efectivo)": "", "Existencia": 9,
    }])

    resultado = procesar_importacion_excel(ruta)

    assert resultado["exito"] is False
    assert "P-BLANCO" in resultado["mensaje"]
    assert "Costo USD Efectivo" in resultado["mensaje"]
    assert obtener_producto("P-BLANCO") is None


def test_sin_existencia_el_costo_en_blanco_se_acepta(db_temporal, tmp_path):
    """La regla del dominio solo exige el costo a partir de 1 unidad: un
    producto agotado puede entrar sin costo registrado."""
    ruta = _escribir_excel(tmp_path / "agotado.xlsx", [{
        "Código": "P-AGOTADO", "Descripción General": "Agotado",
        "Costo USD (Efectivo)": "", "Existencia": 0,
    }])

    resultado = procesar_importacion_excel(ruta)

    assert resultado["exito"] is True, resultado["mensaje"]
    assert _costos("P-AGOTADO")["costo_usd_efectivo"] is None


# ─── Los archivos que NO traen las columnas nuevas ───────────────────────────

def test_un_archivo_sin_las_columnas_nuevas_sigue_importando(db_temporal, tmp_path):
    """No se pueden volver obligatorias para los archivos viejos: una plantilla
    de catálogo anterior a este cambio tiene que seguir entrando igual."""
    ruta = _escribir_excel(tmp_path / "viejo.xlsx", [{
        "Código": "P-VIEJO", "Descripción General": "Plantilla anterior",
        "Departamento": "Ferretería", "Precio USD (Efectivo)": 10.0, "Existencia": 4,
    }])

    resultado = procesar_importacion_excel(ruta)

    assert resultado["exito"] is True, resultado["mensaje"]
    assert obtener_producto("P-VIEJO")["existencia"] == 4.0


def test_un_archivo_sin_columnas_de_costo_no_borra_los_costos_almacenados(
    producto_con_costos, tmp_path
):
    """El desastre silencioso que evita `_CAMPOS_CONSERVABLES`: `INSERT OR
    REPLACE` borra la fila y la vuelve a insertar, así que una columna que el
    archivo no menciona pondría el costo en NULL en todo el catálogo."""
    ruta = _escribir_excel(tmp_path / "sin_costos.xlsx", [{
        "Código": producto_con_costos, "Descripción General": "Tubo de escape universal",
        "Departamento": "Repuestos", "Precio USD (Efectivo)": 31.0, "Existencia": 5,
    }])

    assert procesar_importacion_excel(ruta)["exito"] is True

    fila = _costos(producto_con_costos)
    assert fila["costo_usd_efectivo"] == 20.0
    assert fila["costo_usd_bcv"] == 21.0
    assert fila["sub_departamento"] == "Escape"
    # El precio de venta sí se actualiza: esa columna el archivo la trae.
    assert obtener_producto(producto_con_costos)["precio_dolares"] == 31.0


def test_una_celda_de_costo_en_blanco_conserva_el_costo_almacenado(
    producto_con_costos, tmp_path
):
    """Una celda vacía es "no tengo dato", nunca "borrá el que había"."""
    ruta = _escribir_excel(tmp_path / "blanco_existente.xlsx", [{
        "Código": producto_con_costos, "Descripción General": "Tubo de escape universal",
        "Costo USD (Efectivo)": "", "Costo USD (BCV)": "", "Existencia": 5,
    }])

    assert procesar_importacion_excel(ruta)["exito"] is True

    fila = _costos(producto_con_costos)
    assert fila["costo_usd_efectivo"] == 20.0
    assert fila["costo_usd_bcv"] == 21.0


def test_la_alerta_de_stock_minimo_sobrevive_a_una_reimportacion(
    producto_con_costos, tmp_path
):
    """Mismo razonamiento que los costos: el umbral propio del producto no
    viaja en ningún archivo, así que una carga masiva no puede borrarlo."""
    ruta = _escribir_excel(tmp_path / "re.xlsx", [{
        "Código": producto_con_costos, "Descripción General": "Tubo de escape universal",
        "Existencia": 5,
    }])

    assert procesar_importacion_excel(ruta)["exito"] is True

    assert _costos(producto_con_costos)["alerta_stock_minimo"] == 3


# ─── Círculo cerrado: el pedido lleva los costos hasta la ficha ──────────────

def test_el_pedido_generado_lleva_los_costos_y_el_sub_departamento_hasta_la_ficha(
    db_temporal, tmp_path
):
    """El punto de toda la corrección: lo que el empleado anotó en el pedido
    tiene que quedar en la ficha del producto sin que nadie lo retipee."""
    from services import pedidos_service
    from services.cartera_service import crear_proveedor

    crear_proveedor(empresa="Distribuidora Andina", telefono="0412-5550000", rif="J-1")
    pedidos_service.agregar_renglon_manual(
        "sesion-costos",
        codigo="AMO-77",
        descripcion_general="Amortiguador trasero reforzado",
        departamento="Suspensión",
        sub_departamento="Amortiguadores",
        cantidad=3,
        costo_usd_efectivo="40,25",
        costo_usd_bcv="42,50",
        precio_usd_efectivo=70.0,
        precio_usd_bcv=75.0,
        marca="Monroe",
    )
    ruta = tmp_path / "pedido.xlsx"
    try:
        pedidos_service.generar_archivo_pedido(
            "sesion-costos", str(ruta), "Distribuidora Andina", "17/10/2026"
        )

        assert procesar_importacion_excel(str(ruta))["exito"] is True

        fila = _costos("AMO-77")
        assert fila["costo_usd_efectivo"] == 40.25
        assert fila["costo_usd_bcv"] == 42.5
        assert fila["sub_departamento"] == "Amortiguadores"
    finally:
        pedidos_service._sesiones.clear()
