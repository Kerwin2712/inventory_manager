"""El Dashboard le pasa el usuario de la sesión a la vista de Cartera.

Sin ese dato los abonos de "Deudas por Cobrar" se guardan con
`deuda_abonos.usuario_nombre` en NULL y se pierde la constancia de quién
cobró — justo el dato que el requisito pide mostrar en la lista. Es una
regresión silenciosa: la interfaz se ve y funciona igual, y solo se nota
semanas después, auditando una deuda sin firma. De ahí que valga un test
propio.

La vista de Cartera se construye dentro de `get_body()` y no se guarda en
ningún atributo, así que el test intercepta la clase en el espacio de nombres
del Dashboard para capturar con qué argumentos se la instancia. Es menos
elegante que leer un atributo, pero no obliga a abrir la vista solo para
poder observarla desde las pruebas.
"""
import pytest

from services.cartera_service import crear_cliente
from services.deudas_service import crear_deuda, registrar_abono
from ui.views import dashboard_view as modulo_dashboard
from ui.views.cartera_view import CarteraView


@pytest.fixture
def cartera_construida(db_temporal, monkeypatch):
    """Construye el Dashboard en la sección de Cartera y devuelve la
    `CarteraView` que creó, con los argumentos que recibió."""

    def construir(user_info: dict) -> CarteraView:
        capturadas = []

        class CarteraEspia(CarteraView):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                capturadas.append(self)

        monkeypatch.setattr(modulo_dashboard, "CarteraView", CarteraEspia)

        modulo_dashboard.DashboardView.ensure_settings_loaded()
        dashboard = modulo_dashboard.DashboardView(user_info=user_info)
        dashboard.current_section = "Cartera"
        dashboard.get_body()

        assert capturadas, "el Dashboard no construyó la vista de Cartera"
        return capturadas[-1]

    return construir


def test_la_cartera_recibe_el_usuario_de_la_sesion(cartera_construida):
    cartera = cartera_construida({"username": "cajera2", "role": "vendedor"})
    assert cartera.usuario_nombre == "cajera2"


def test_tambien_con_rol_administrador(cartera_construida):
    cartera = cartera_construida({"username": "admin", "role": "superadmin"})
    assert cartera.usuario_nombre == "admin"


def test_el_nombre_llega_hasta_el_abono(cartera_construida):
    """El recorrido completo: sesión -> Dashboard -> Cartera -> abono."""
    crear_cliente(nombre="Fulano de Tal", cedula_rif="V-12345678", telefono="0414-1234567")
    deuda = crear_deuda("V-12345678", 30.0, "15/12/2026")

    cartera = cartera_construida({"username": "cajera2", "role": "vendedor"})
    actualizada = registrar_abono(deuda["id"], 10.0, usuario_nombre=cartera.usuario_nombre)

    assert actualizada["abonos"][0]["usuario_nombre"] == "cajera2"


def test_una_cartera_aislada_sigue_permitiendo_cobrar_sin_firma(db_temporal):
    """Decisión deliberada de la vista: si se instancia sin `user_data`, el
    abono se registra sin firma antes que impedir el cobro. Un cobrador no
    debería quedarse sin poder cobrar por un dato de auditoría."""
    assert CarteraView().usuario_nombre is None
