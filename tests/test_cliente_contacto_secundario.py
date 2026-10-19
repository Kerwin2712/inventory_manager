"""Contacto secundario del cliente: el campo que estrena el método Crédito.

No era un campo del registro original de la cartera, así que todo cliente
cargado antes de la actualización de octubre llega sin él y la ventana del
método de pago "Crédito" es la primera oportunidad de capturarlo. Si el
servicio no lo escribe, el vendedor lo teclea, ve que se guarda la venta y el
dato se pierde en silencio: el teléfono de respaldo nunca aparece en la ficha
cuando hay que salir a cobrar.
"""
import pytest

from services.cartera_service import (
    actualizar_cliente,
    crear_cliente,
    obtener_cliente,
)


@pytest.fixture
def cliente(db_temporal):
    return crear_cliente(
        nombre="Fulano de Tal",
        cedula_rif="V-12345678",
        direccion="Calle 1",
        telefono="0414-1234567",
        correo="fulano@example.com",
    )


def test_un_cliente_nuevo_puede_traer_contacto_secundario(db_temporal):
    """Existe por simetría con la edición: un campo que solo se puede escribir
    al editar obliga a guardar dos veces un dato que ya estaba en pantalla."""
    creado = crear_cliente(
        nombre="Maria Fulana",
        cedula_rif="V-87654321",
        telefono="0412-7654321",
        contacto_secundario="0426-1112233",
    )
    assert creado["contacto_secundario"] == "0426-1112233"


def test_un_cliente_sin_contacto_secundario_lo_guarda_en_nulo(cliente):
    """Vacío no es cadena vacía: la ficha debe poder decir "no lo tengo"."""
    assert cliente["contacto_secundario"] is None


def test_editar_registra_el_contacto_secundario(cliente):
    actualizado = actualizar_cliente(
        cedula_rif="V-12345678", contacto_secundario="0426-1112233"
    )
    assert actualizado["contacto_secundario"] == "0426-1112233"
    assert obtener_cliente("V-12345678")["contacto_secundario"] == "0426-1112233"


def test_editar_sin_mencionarlo_lo_conserva(cliente):
    """`None` sigue significando "no modificar": cambiar el teléfono no puede
    borrar el contacto de respaldo."""
    actualizar_cliente(cedula_rif="V-12345678", contacto_secundario="0426-1112233")
    actualizado = actualizar_cliente(cedula_rif="V-12345678", telefono="0414-9999999")

    assert actualizado["telefono"] == "0414-9999999"
    assert actualizado["contacto_secundario"] == "0426-1112233"


def test_la_cadena_vacia_lo_borra(cliente):
    """Es la única forma de vaciar un campo opcional, porque `None` está
    reservado para "no modificar"."""
    actualizar_cliente(cedula_rif="V-12345678", contacto_secundario="0426-1112233")
    actualizado = actualizar_cliente(cedula_rif="V-12345678", contacto_secundario="")

    assert actualizado["contacto_secundario"] is None


def test_se_recortan_los_espacios(cliente):
    actualizado = actualizar_cliente(
        cedula_rif="V-12345678", contacto_secundario="  0426-1112233  "
    )
    assert actualizado["contacto_secundario"] == "0426-1112233"


def test_editar_el_resto_de_los_campos_sigue_funcionando(cliente):
    """Guarda de regresión: la consulta UPDATE cambió para sumar la columna."""
    actualizado = actualizar_cliente(
        cedula_rif="V-12345678",
        nombre="Fulano de Tal e Hijos",
        direccion="Avenida 2",
        telefono="0414-0000000",
        correo="nuevo@example.com",
    )
    assert actualizado["nombre"] == "Fulano de Tal e Hijos"
    assert actualizado["direccion"] == "Avenida 2"
    assert actualizado["telefono"] == "0414-0000000"
    assert actualizado["correo"] == "nuevo@example.com"


def test_la_deuda_lee_el_contacto_secundario_del_cliente(cliente):
    """El recorrido que motivó el campo: se captura al vender a crédito y la
    lista de Deudas por Cobrar lo muestra junto al resto del directorio."""
    from services.deudas_service import crear_deuda

    actualizar_cliente(cedula_rif="V-12345678", contacto_secundario="0426-1112233")
    deuda = crear_deuda("V-12345678", 30.0, "15/12/2026")

    assert deuda["cliente_contacto_secundario"] == "0426-1112233"


def test_editar_un_cliente_inexistente_sigue_siendo_error(db_temporal):
    with pytest.raises(ValueError, match="no existe"):
        actualizar_cliente(cedula_rif="V-00000000", contacto_secundario="0426-1112233")
