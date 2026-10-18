"""Deudas por Cobrar: creación desde una venta a crédito y abonos parciales.

Lo que estas pruebas fijan es la regla que hace confiable al módulo: el saldo
y el estado de la deuda SIEMPRE se derivan de `deuda_abonos`, nunca se
escriben a mano. Si mañana alguien corrige o borra un abono, el saldo debe
seguirlo sin quedar desalineado.
"""
import datetime

import pytest

from services.cartera_service import crear_cliente
from services.deudas_service import (
    ESTADO_ABIERTA,
    ESTADO_PAGADA,
    actualizar_deuda,
    crear_deuda,
    eliminar_deuda,
    esta_vencida,
    listar_deudas,
    normalizar_fecha,
    obtener_deuda,
    registrar_abono,
    total_por_cobrar,
)


@pytest.fixture
def cliente(db_temporal):
    return crear_cliente(
        nombre="Fulano de Tal",
        cedula_rif="V-12345678",
        direccion="Calle 1",
        telefono="0414-1234567",
    )


ITEMS = [
    {"producto_codigo": "P-001", "descripcion_corta": "Filtro de aceite", "cantidad": 2, "subtotal_usd": 20.0},
    {"producto_codigo": "P-002", "descripcion_corta": "Bujía", "cantidad": 1, "subtotal_usd": 10.0},
]


# ─── Normalización de la fecha límite ────────────────────────────────────────

@pytest.mark.parametrize(
    "entrada,esperado",
    [
        ("31/12/2026", "2026-12-31"),
        ("2026-12-31", "2026-12-31"),
        ("31-12-2026", "2026-12-31"),
        (datetime.date(2026, 12, 31), "2026-12-31"),
    ],
)
def test_normalizar_fecha_acepta_los_formatos_del_usuario(entrada, esperado):
    """La ventana de crédito pide Día/Mes/Año, pero SQLite solo ordena bien el
    ISO: todo entra por el normalizador."""
    assert normalizar_fecha(entrada) == esperado


def test_normalizar_fecha_rechaza_basura():
    with pytest.raises(ValueError, match="ERR_DEUDA_FECHA"):
        normalizar_fecha("el mes que viene")


def test_fecha_limite_vacia_es_error():
    with pytest.raises(ValueError, match="ERR_DEUDA_FECHA"):
        normalizar_fecha("")


# ─── Creación ────────────────────────────────────────────────────────────────

def test_crear_deuda_nace_con_el_saldo_completo(cliente):
    """Una venta a crédito no cobra nada en el momento: compromete el pago."""
    deuda = crear_deuda(
        cliente_id="V-12345678",
        monto_total_usd=30.0,
        fecha_limite_pago="15/12/2026",
        items=ITEMS,
        usuario_nombre="vendedor1",
    )
    assert deuda["monto_total_usd"] == 30.0
    assert deuda["saldo_usd"] == 30.0
    assert deuda["estado"] == ESTADO_ABIERTA
    assert deuda["fecha_limite_pago"] == "2026-12-15"
    assert deuda["usuario_nombre"] == "vendedor1"
    assert deuda["total_abonado_usd"] == 0.0


def test_crear_deuda_guarda_los_items_acreditados(cliente):
    """El "repuesto fiado" que la lista muestra junto a los datos del cliente."""
    deuda = crear_deuda("V-12345678", 30.0, "15/12/2026", items=ITEMS)
    assert len(deuda["items"]) == 2
    assert deuda["items_descripcion"] == "Filtro de aceite, Bujía"
    assert deuda["cantidad_items"] == 2


def test_crear_deuda_exige_cliente_de_la_cartera(db_temporal):
    """Sin cliente no hay a quién cobrarle: una deuda anónima es incobrable."""
    with pytest.raises(ValueError, match="ERR_DEUDA_CLIENTE"):
        crear_deuda("", 30.0, "15/12/2026")
    with pytest.raises(ValueError, match="ERR_DEUDA_CLIENTE"):
        crear_deuda("V-99999999", 30.0, "15/12/2026")


def test_crear_deuda_rechaza_monto_cero(cliente):
    with pytest.raises(ValueError, match="ERR_DEUDA_MONTO"):
        crear_deuda("V-12345678", 0, "15/12/2026")


def test_crear_deuda_acepta_coma_decimal(cliente):
    """El usuario venezolano escribe 30,50 — no 30.50."""
    deuda = crear_deuda("V-12345678", "30,50", "15/12/2026")
    assert deuda["monto_total_usd"] == 30.5


# ─── Abonos parciales ────────────────────────────────────────────────────────

def test_abono_parcial_baja_el_saldo_y_deja_la_deuda_abierta(cliente):
    deuda = crear_deuda("V-12345678", 30.0, "15/12/2026", items=ITEMS)
    deuda = registrar_abono(deuda["id"], 10.0, metodo_pago="Efectivo")
    assert deuda["saldo_usd"] == 20.0
    assert deuda["total_abonado_usd"] == 10.0
    assert deuda["estado"] == ESTADO_ABIERTA


def test_abono_final_cierra_la_deuda(cliente):
    deuda = crear_deuda("V-12345678", 30.0, "15/12/2026")
    registrar_abono(deuda["id"], 10.0)
    deuda = registrar_abono(deuda["id"], 20.0)
    assert deuda["saldo_usd"] == 0.0
    assert deuda["estado"] == ESTADO_PAGADA
    assert len(deuda["abonos"]) == 2


def test_no_se_puede_abonar_mas_que_el_saldo(cliente):
    """Un cobro de más no es un abono, es un error de tipeo: aceptarlo dejaría
    la deuda en saldo negativo."""
    deuda = crear_deuda("V-12345678", 30.0, "15/12/2026")
    with pytest.raises(ValueError, match="ERR_DEUDA_ABONO"):
        registrar_abono(deuda["id"], 31.0)
    assert obtener_deuda(deuda["id"])["saldo_usd"] == 30.0


def test_no_se_puede_abonar_a_una_deuda_pagada(cliente):
    deuda = crear_deuda("V-12345678", 30.0, "15/12/2026")
    registrar_abono(deuda["id"], 30.0)
    with pytest.raises(ValueError, match="ERR_DEUDA_PAGADA"):
        registrar_abono(deuda["id"], 1.0)


def test_abono_cero_o_negativo_es_error(cliente):
    deuda = crear_deuda("V-12345678", 30.0, "15/12/2026")
    with pytest.raises(ValueError, match="ERR_DEUDA_ABONO"):
        registrar_abono(deuda["id"], 0)
    with pytest.raises(ValueError, match="ERR_DEUDA_MONTO"):
        registrar_abono(deuda["id"], -5)


def test_abono_guarda_metodo_y_referencia(cliente):
    deuda = crear_deuda("V-12345678", 30.0, "15/12/2026")
    deuda = registrar_abono(
        deuda["id"], 10.0, metodo_pago="Pago Móvil", referencia_pago="0099887766",
        usuario_nombre="cajera2",
    )
    abono = deuda["abonos"][0]
    assert abono["metodo_pago"] == "Pago Móvil"
    assert abono["referencia_pago"] == "0099887766"
    assert abono["usuario_nombre"] == "cajera2"


def test_tres_centavos_de_redondeo_cierran_la_deuda(cliente):
    """Un saldo de milésimas por redondeo es una deuda pagada, no una deuda
    abierta que el cobrador nunca podría cerrar."""
    deuda = crear_deuda("V-12345678", 10.0, "15/12/2026")
    deuda = registrar_abono(deuda["id"], 9.999)
    assert deuda["saldo_usd"] == 0.0
    assert deuda["estado"] == ESTADO_PAGADA


# ─── Vencimiento (el signo de exclamación de la lista) ───────────────────────

def test_deuda_pasada_de_fecha_esta_vencida(cliente):
    deuda = crear_deuda("V-12345678", 30.0, "10/10/2026")
    assert esta_vencida(deuda, hoy="2026-10-18") is True


def test_deuda_dentro_del_plazo_no_esta_vencida(cliente):
    deuda = crear_deuda("V-12345678", 30.0, "10/12/2026")
    assert esta_vencida(deuda, hoy="2026-10-18") is False


def test_deuda_pagada_nunca_esta_vencida(cliente):
    """Ya se cobró: la fecha límite dejó de importar."""
    deuda = crear_deuda("V-12345678", 30.0, "10/10/2026")
    deuda = registrar_abono(deuda["id"], 30.0)
    assert esta_vencida(deuda, hoy="2026-12-31") is False


# ─── Listado ─────────────────────────────────────────────────────────────────

def test_listar_ordena_por_fecha_limite_ascendente(cliente):
    """Las más urgentes primero: es el orden en que hay que salir a cobrar."""
    crear_deuda("V-12345678", 50.0, "15/12/2026")
    crear_deuda("V-12345678", 30.0, "10/10/2026")
    limites = [d["fecha_limite_pago"] for d in listar_deudas()]
    assert limites == ["2026-10-10", "2026-12-15"]


def test_listar_trae_los_datos_del_cliente(cliente):
    crear_deuda("V-12345678", 30.0, "15/12/2026")
    deuda = listar_deudas()[0]
    assert deuda["cliente_nombre"] == "Fulano de Tal"
    assert deuda["cliente_telefono"] == "0414-1234567"
    assert deuda["cliente_id"] == "V-12345678"


def test_listar_solo_abiertas_oculta_las_pagadas(cliente):
    pagada = crear_deuda("V-12345678", 30.0, "15/12/2026")
    registrar_abono(pagada["id"], 30.0)
    crear_deuda("V-12345678", 40.0, "20/12/2026")

    assert len(listar_deudas()) == 2
    abiertas = listar_deudas(solo_abiertas=True)
    assert len(abiertas) == 1
    assert abiertas[0]["monto_total_usd"] == 40.0


def test_busqueda_por_nombre_cedula_e_item(cliente):
    crear_deuda("V-12345678", 30.0, "15/12/2026", items=ITEMS)
    assert len(listar_deudas(busqueda="fulano")) == 1
    assert len(listar_deudas(busqueda="12345678")) == 1
    assert len(listar_deudas(busqueda="Bujía")) == 1
    assert len(listar_deudas(busqueda="no existe")) == 0


def test_total_por_cobrar_suma_solo_los_saldos_abiertos(cliente):
    d1 = crear_deuda("V-12345678", 30.0, "15/12/2026")
    registrar_abono(d1["id"], 10.0)
    d2 = crear_deuda("V-12345678", 40.0, "20/12/2026")
    registrar_abono(d2["id"], 40.0)  # queda pagada
    assert total_por_cobrar() == 20.0


# ─── Edición y borrado ───────────────────────────────────────────────────────

def test_editar_prorroga_la_fecha_limite(cliente):
    deuda = crear_deuda("V-12345678", 30.0, "10/10/2026")
    deuda = actualizar_deuda(deuda["id"], fecha_limite_pago="30/11/2026")
    assert deuda["fecha_limite_pago"] == "2026-11-30"
    assert deuda["vencida"] is False


def test_editar_el_monto_total_rederiva_el_saldo(cliente):
    """El saldo no es editable: se vuelve a derivar de los abonos."""
    deuda = crear_deuda("V-12345678", 30.0, "15/12/2026")
    registrar_abono(deuda["id"], 10.0)
    deuda = actualizar_deuda(deuda["id"], monto_total_usd=25.0)
    assert deuda["saldo_usd"] == 15.0
    assert deuda["estado"] == ESTADO_ABIERTA


def test_editar_a_un_monto_menor_que_lo_abonado_es_error(cliente):
    deuda = crear_deuda("V-12345678", 30.0, "15/12/2026")
    registrar_abono(deuda["id"], 20.0)
    with pytest.raises(ValueError, match="ERR_DEUDA_MONTO"):
        actualizar_deuda(deuda["id"], monto_total_usd=10.0)


def test_editar_el_monto_hasta_lo_abonado_cierra_la_deuda(cliente):
    deuda = crear_deuda("V-12345678", 30.0, "15/12/2026")
    registrar_abono(deuda["id"], 20.0)
    deuda = actualizar_deuda(deuda["id"], monto_total_usd=20.0)
    assert deuda["saldo_usd"] == 0.0
    assert deuda["estado"] == ESTADO_PAGADA


def test_editar_una_deuda_inexistente_es_error(db_temporal):
    with pytest.raises(ValueError, match="ERR_DEUDA_NO_EXISTE"):
        actualizar_deuda(999, fecha_limite_pago="30/11/2026")


def test_borrar_arrastra_items_y_abonos(cliente):
    deuda = crear_deuda("V-12345678", 30.0, "15/12/2026", items=ITEMS)
    registrar_abono(deuda["id"], 10.0)

    assert eliminar_deuda(deuda["id"]) is True
    assert obtener_deuda(deuda["id"]) is None

    from core.database import get_connection
    with get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM deuda_items").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM deuda_abonos").fetchone()[0] == 0


def test_borrar_una_deuda_inexistente_devuelve_false(db_temporal):
    assert eliminar_deuda(999) is False
