"""Pruebas de regresión de la SECUENCIA DE IDs de carritos (`services.cart_manager`).

El bug original: el ID salía de un contador monótono por sesión, así que al
eliminar un carrito su número quedaba huérfano para siempre (con {1,2,3},
borrar el 2 y crear uno nuevo daba "Carrito 4"). Ahora el ID se deriva del
conjunto de carritos vivos: siempre el menor número libre.

El estado vive en memoria (`cart_manager._sesiones`), por eso cada test usa
IDs de sesión propios y los libera con `limpiar_sesion`.
"""
import pytest

from services import cart_manager as cm


@pytest.fixture
def sid():
    """ID de sesión aislado, con el estado global limpio antes y después."""
    session_id = "sesion-test-A"
    cm.limpiar_sesion(session_id)
    yield session_id
    cm.limpiar_sesion(session_id)


def _ids(session_id) -> list[str]:
    return list(cm.obtener_todos_los_carritos(session_id).keys())


def _numeros(session_id) -> list[int]:
    return sorted(int(cid.split()[1]) for cid in _ids(session_id))


# ─────────────────────────────────────────────────────────────────────────────
# Numeración consecutiva
# ─────────────────────────────────────────────────────────────────────────────
def test_sesion_nueva_arranca_con_un_solo_carrito_uno(sid):
    assert _ids(sid) == ["Carrito 1"]
    assert cm.obtener_id_carrito_activo(sid) == "Carrito 1"


def test_creaciones_consecutivas_no_dejan_huecos(sid):
    assert cm.crear_nuevo_carrito(sid)["id"] == "Carrito 2"
    assert cm.crear_nuevo_carrito(sid)["id"] == "Carrito 3"
    assert cm.crear_nuevo_carrito(sid)["id"] == "Carrito 4"
    assert _numeros(sid) == [1, 2, 3, 4]


def test_el_carrito_creado_queda_activo(sid):
    nuevo = cm.crear_nuevo_carrito(sid)
    assert cm.obtener_id_carrito_activo(sid) == nuevo["id"]
    assert cm.obtener_carrito_activo(sid)["id"] == nuevo["id"]


# ─────────────────────────────────────────────────────────────────────────────
# Reutilización del número liberado (bug original)
# ─────────────────────────────────────────────────────────────────────────────
def test_al_eliminar_un_carrito_intermedio_el_siguiente_reutiliza_su_numero(sid):
    cm.crear_nuevo_carrito(sid)  # Carrito 2
    cm.crear_nuevo_carrito(sid)  # Carrito 3
    assert cm.eliminar_carrito(sid, "Carrito 2") is True

    assert cm.crear_nuevo_carrito(sid)["id"] == "Carrito 2"
    assert _numeros(sid) == [1, 2, 3]


def test_al_eliminar_varios_se_reutiliza_siempre_el_menor_libre(sid):
    for _ in range(4):
        cm.crear_nuevo_carrito(sid)  # 2, 3, 4, 5
    cm.eliminar_carrito(sid, "Carrito 4")
    cm.eliminar_carrito(sid, "Carrito 2")

    assert cm.crear_nuevo_carrito(sid)["id"] == "Carrito 2"
    assert cm.crear_nuevo_carrito(sid)["id"] == "Carrito 4"
    assert cm.crear_nuevo_carrito(sid)["id"] == "Carrito 6"
    assert _numeros(sid) == [1, 2, 3, 4, 5, 6]


def test_nunca_se_duplica_un_id_existente(sid):
    for _ in range(6):
        cm.crear_nuevo_carrito(sid)
    ids = _ids(sid)
    assert len(ids) == len(set(ids))

    # Aunque un carrito tenga nombre visible personalizado, el ID sigue
    # siendo único y derivado de la secuencia (nombre != id).
    personalizado = cm.crear_nuevo_carrito(sid, nombre_personalizado="Cliente Ferretería")
    assert personalizado["id"] == "Carrito 8"
    assert personalizado["nombre"] == "Cliente Ferretería"
    ids = _ids(sid)
    assert len(ids) == len(set(ids))


def test_nombre_personalizado_no_altera_la_numeracion(sid):
    cm.crear_nuevo_carrito(sid, nombre_personalizado="Mostrador")
    assert _ids(sid) == ["Carrito 1", "Carrito 2"]
    cm.eliminar_carrito(sid, "Carrito 2")
    assert cm.crear_nuevo_carrito(sid, nombre_personalizado="Otro")["id"] == "Carrito 2"


# ─────────────────────────────────────────────────────────────────────────────
# Coherencia del carrito activo tras eliminaciones
# ─────────────────────────────────────────────────────────────────────────────
def test_eliminar_el_carrito_activo_reengancha_a_uno_existente(sid):
    cm.crear_nuevo_carrito(sid)  # Carrito 2 (queda activo)
    cm.eliminar_carrito(sid, "Carrito 2")

    activo = cm.obtener_id_carrito_activo(sid)
    assert activo in _ids(sid)
    assert cm.obtener_carrito_activo(sid)["id"] == activo


def test_cambiar_carrito_activo_a_id_inexistente_no_deja_estado_roto(sid):
    cm.crear_nuevo_carrito(sid)  # Carrito 2
    cm.eliminar_carrito(sid, "Carrito 2")

    devuelto = cm.cambiar_carrito_activo(sid, "Carrito 99")
    assert devuelto["id"] in _ids(sid)
    assert cm.obtener_id_carrito_activo(sid) in _ids(sid)
    # No se debe inventar el carrito inexistente.
    assert "Carrito 99" not in _ids(sid)


def test_eliminar_el_unico_carrito_lo_reinicia_al_primero_de_la_secuencia(sid):
    cm.crear_nuevo_carrito(sid)  # Carrito 2
    cm.eliminar_carrito(sid, "Carrito 1")
    assert _ids(sid) == ["Carrito 2"]

    # Al borrar el único que queda, la sesión vuelve a su estado inicial:
    # siempre queda un carrito y la numeración no arranca con un hueco.
    assert cm.eliminar_carrito(sid, "Carrito 2") is True
    assert _ids(sid) == ["Carrito 1"]
    assert cm.obtener_id_carrito_activo(sid) == "Carrito 1"
    assert cm.obtener_carrito_activo(sid)["items"] == []
    assert cm.crear_nuevo_carrito(sid)["id"] == "Carrito 2"


def test_eliminar_un_id_inexistente_devuelve_false_y_no_toca_la_secuencia(sid):
    cm.crear_nuevo_carrito(sid)
    antes = _ids(sid)
    assert cm.eliminar_carrito(sid, "Carrito 77") is False
    assert _ids(sid) == antes


def test_vaciar_carrito_activo_no_altera_la_numeracion(sid):
    cm.crear_nuevo_carrito(sid)  # Carrito 2
    cm.crear_nuevo_carrito(sid)  # Carrito 3
    producto = {"codigo": "P-1", "precio_dolares": 10.0, "precio_bcv": 12.0, "referencia": "Ref"}
    cm.agregar_o_actualizar_producto(sid, producto, cantidad=2.0, tasa_bcv=40.0)

    cm.vaciar_carrito_activo(sid)

    assert _ids(sid) == ["Carrito 1", "Carrito 2", "Carrito 3"]
    assert cm.obtener_id_carrito_activo(sid) == "Carrito 3"
    assert cm.obtener_carrito_activo(sid)["items"] == []
    assert cm.crear_nuevo_carrito(sid)["id"] == "Carrito 4"


# ─────────────────────────────────────────────────────────────────────────────
# Aislamiento entre sesiones
# ─────────────────────────────────────────────────────────────────────────────
def test_dos_sesiones_numeran_de_forma_independiente():
    a, b = "sesion-test-X", "sesion-test-Y"
    cm.limpiar_sesion(a)
    cm.limpiar_sesion(b)
    try:
        cm.crear_nuevo_carrito(a)  # A: Carrito 2
        cm.crear_nuevo_carrito(a)  # A: Carrito 3
        assert cm.crear_nuevo_carrito(b)["id"] == "Carrito 2"  # B parte de su propio 1

        cm.eliminar_carrito(a, "Carrito 2")
        assert cm.crear_nuevo_carrito(a)["id"] == "Carrito 2"
        # Borrar en A no libera ni ocupa nada en B.
        assert cm.crear_nuevo_carrito(b)["id"] == "Carrito 3"
        assert list(cm.obtener_todos_los_carritos(a).keys()) == ["Carrito 1", "Carrito 3", "Carrito 2"]
        assert list(cm.obtener_todos_los_carritos(b).keys()) == ["Carrito 1", "Carrito 2", "Carrito 3"]
    finally:
        cm.limpiar_sesion(a)
        cm.limpiar_sesion(b)


def test_limpiar_sesion_reinicia_la_secuencia_de_esa_sesion(sid):
    cm.crear_nuevo_carrito(sid)
    cm.crear_nuevo_carrito(sid)
    cm.limpiar_sesion(sid)
    assert _ids(sid) == ["Carrito 1"]


# ─────────────────────────────────────────────────────────────────────────────
# Invariante bajo mucha operación intercalada
# ─────────────────────────────────────────────────────────────────────────────
def test_invariante_de_secuencia_con_muchas_operaciones_intercaladas(sid):
    """Simula carga alta de forma SECUENCIAL (el estado de `cart_manager` vive
    en memoria del proceso y no se pretende thread-safe): tras cada operación
    los IDs deben ser un conjunto sin duplicados, y en todo momento el próximo
    ID asignado debe ser el menor número libre."""
    import random

    aleatorio = random.Random(1712)
    for _ in range(300):
        vivos = _ids(sid)
        if len(vivos) > 1 and aleatorio.random() < 0.45:
            cm.eliminar_carrito(sid, aleatorio.choice(vivos))
        else:
            esperado = min(set(range(1, len(vivos) + 2)) - set(_numeros(sid)))
            creado = cm.crear_nuevo_carrito(sid)
            assert creado["id"] == f"Carrito {esperado}"

        ids = _ids(sid)
        assert len(ids) == len(set(ids)), "IDs duplicados en la sesión"
        assert len(ids) >= 1, "la sesión debe conservar al menos un carrito"
        assert cm.obtener_id_carrito_activo(sid) in ids
        for cid, carrito in cm.obtener_todos_los_carritos(sid).items():
            assert carrito["id"] == cid, "la clave del dict y el id del carrito deben coincidir"

    # Al rellenar los huecos hasta completar, la numeración queda contigua.
    while len(_ids(sid)) < max(_numeros(sid)):
        cm.crear_nuevo_carrito(sid)
    assert _numeros(sid) == list(range(1, len(_ids(sid)) + 1))


def test_el_estado_de_sesion_ya_no_depende_de_un_contador(sid):
    """El campo "contador" era la raíz del bug; no debe volver a aparecer."""
    cm.crear_nuevo_carrito(sid)
    assert "contador" not in cm._sesiones[sid]
