"""La Copia de Seguridad incluye los costos y se puede volver a importar.

Un respaldo que no se puede reimportar no es un respaldo, y uno que pierde
datos por el camino es peor: da la tranquilidad sin el respaldo. Antes de esta
actualización el backup exportaba doce columnas y ninguna era de costo, así
que restaurarlo en una base vacía perdía los costos de todo el catálogo — el
dato que nadie puede reconstruir de memoria.

El círculo se cierra de verdad: se exporta, se vacía la base y se importa el
propio archivo exportado por el camino real de la Carga Masiva.
"""
import pandas as pd
import pytest

from core.database import get_connection
from services.cartera_service import crear_proveedor
from services.importacion_service import procesar_importacion_excel
from services.inventario_service import crear_producto, obtener_producto
from ui.views.gestion_datos_view import GestionDatosView


class PaginaFalsa:
    def __init__(self):
        self.on_keyboard_event = None
        self.overlay = []

    def update(self):
        pass


@pytest.fixture
def base_con_costos(db_temporal):
    """Un producto con costos y sub-departamento registrados."""
    proveedor = crear_proveedor(
        empresa="Distribuidora Andina",
        telefono="0212-1234567",
        rif="J-123456789",
    )
    crear_producto(
        codigo="P-001",
        referencia="REF-001",
        departamento="Motor",
        sub_departamento="Lubricación",
        descripcion_general="Filtro de aceite para motor diésel",
        marca="Bosch",
        precio_dolares=12.50,
        precio_bcv=13.00,
        existencia=5,
        costo_usd_efectivo=7.25,
        costo_usd_bcv=7.80,
        nombre_referencia_corto="Filtro de aceite",
        proveedor_id=proveedor["id"],
        rol_usuario="administrador",
    )
    return proveedor


def _exportar(tmp_path, monkeypatch) -> str:
    """Corre el respaldo real con un rol administrador, guardando en tmp."""
    GestionDatosView.ensure_settings_loaded()
    vista = GestionDatosView(user_data={"username": "admin", "role": "superadmin"})
    pagina = PaginaFalsa()
    vista.get_current_page = lambda e=None: pagina

    destino = str(tmp_path / "respaldo.xlsx")
    monkeypatch.setattr(vista, "abrir_dialogo_guardado", lambda d, s: destino)
    monkeypatch.setattr(vista, "show_alert_success", lambda *a, **k: None)
    monkeypatch.setattr(vista, "show_alert_error", lambda *a, **k: None)

    vista.handle_exportar_excel(None)
    return destino


# ─── Contenido del archivo ───────────────────────────────────────────────────

def test_el_respaldo_trae_las_columnas_de_costo(base_con_costos, tmp_path, monkeypatch):
    ruta = _exportar(tmp_path, monkeypatch)
    columnas = pd.read_excel(ruta, sheet_name="Productos").columns.tolist()

    for columna in ("Costo USD (Efectivo)", "Costo USD (BCV)", "Sub-Departamento"):
        assert columna in columnas, f"el respaldo no exporta `{columna}`"


def test_los_valores_de_costo_viajan_en_el_archivo(base_con_costos, tmp_path, monkeypatch):
    ruta = _exportar(tmp_path, monkeypatch)
    fila = pd.read_excel(ruta, sheet_name="Productos").iloc[0]

    assert fila["Costo USD (Efectivo)"] == pytest.approx(7.25)
    assert fila["Costo USD (BCV)"] == pytest.approx(7.80)
    assert fila["Sub-Departamento"] == "Lubricación"


def test_las_columnas_son_las_que_la_carga_masiva_reconoce(base_con_costos, tmp_path, monkeypatch):
    """Los encabezados del respaldo tienen que normalizar a un alias conocido
    de la importación; si no, el archivo solo se puede leer a mano."""
    from services.importacion_service import _ALIAS_CAMPO_PRODUCTO, limpiar_clave

    ruta = _exportar(tmp_path, monkeypatch)
    columnas = pd.read_excel(ruta, sheet_name="Productos").columns.tolist()

    alias_conocidos = {
        limpiar_clave(alias)
        for alias_campo in _ALIAS_CAMPO_PRODUCTO.values()
        for alias in alias_campo
    }
    for columna in ("Costo USD (Efectivo)", "Costo USD (BCV)", "Sub-Departamento"):
        assert limpiar_clave(columna) in alias_conocidos, (
            f"la importación no reconocería el encabezado `{columna}`"
        )


# ─── El círculo completo ─────────────────────────────────────────────────────

def test_restaurar_el_respaldo_en_una_base_vacia_conserva_los_costos(
    base_con_costos, tmp_path, monkeypatch
):
    """Es el caso que motivó el cambio: antes, restaurar perdía los costos de
    todo el catálogo en silencio."""
    ruta = _exportar(tmp_path, monkeypatch)

    with get_connection() as conn:
        conn.execute("DELETE FROM productos")
        conn.commit()
    assert obtener_producto("P-001", rol_usuario="administrador") is None

    resultado = procesar_importacion_excel(ruta)
    assert resultado.get("exito") is True, resultado
    assert resultado["detalles"]["productos"] == 1, resultado

    producto = obtener_producto("P-001", rol_usuario="administrador")
    assert producto is not None
    assert producto["costo_usd_efectivo"] == pytest.approx(7.25)
    assert producto["costo_usd_bcv"] == pytest.approx(7.80)
    assert producto["sub_departamento"] == "Lubricación"


def test_restaurar_un_respaldo_no_suma_la_existencia(
    base_con_costos, tmp_path, monkeypatch
):
    """La guarda contra el desastre: un respaldo FIJA la existencia. Si sumara,
    reimportarlo duplicaría el stock de toda la base."""
    ruta = _exportar(tmp_path, monkeypatch)

    procesar_importacion_excel(ruta)
    procesar_importacion_excel(ruta)

    producto = obtener_producto("P-001", rol_usuario="administrador")
    assert producto["existencia"] == pytest.approx(5)


def test_un_producto_sin_costos_no_rompe_el_respaldo(db_temporal, tmp_path, monkeypatch):
    """Los costos son opcionales mientras no haya existencia: una celda vacía
    tiene que ir y volver sin inventar un cero."""
    crear_producto(
        codigo="P-002",
        referencia="REF-002",
        departamento="Carrocería",
        descripcion_general="Pieza sin costo registrado",
        marca="Generico",
        precio_dolares=5.0,
        precio_bcv=5.2,
        existencia=0,
        nombre_referencia_corto="Pieza",
        rol_usuario="administrador",
    )

    ruta = _exportar(tmp_path, monkeypatch)
    with get_connection() as conn:
        conn.execute("DELETE FROM productos")
        conn.commit()
    procesar_importacion_excel(ruta)

    producto = obtener_producto("P-002", rol_usuario="administrador")
    assert producto is not None
    assert producto["costo_usd_efectivo"] is None
