"""
Administrador de carritos de compra y estado de venta para la aplicación.
Permite gestionar múltiples carritos en simultáneo (guardar/recuperar),
asociar clientes desde Cartera y agregar productos desde Inventario o Ventas.

Aislamiento por sesión (importante): el servidor Flet atiende a varios
usuarios/pestañas conectados al MISMO proceso. Todo el estado de carritos se
guarda en `_sesiones`, un diccionario indexado por `session_id`
(`page.session.id`, único por cada conexión de navegador) — así el carrito
activo, la lista de carritos y sus renglones nunca se comparten entre dos
vendedores distintos, ni se pisan entre sí al operar "al mismo tiempo".
Cada función pública recibe `session_id` como primer parámetro obligatorio
para forzar a quien la llama a pasar siempre la sesión correcta.
"""

import datetime
from services.bcv_service import obtener_estado_tasa

# Métodos de pago soportados (contexto Venezuela): Efectivo/Binance cobran al
# Precio USD Efectivo; Pago Móvil/Transferencia cobran el equivalente en
# Bolívares calculado con el Precio USD BCV x tasa vigente.
METODOS_PAGO_USD = ("Efectivo", "Binance")
METODOS_PAGO_BS = ("Pago Móvil", "Transferencia", "Punto")
METODOS_PAGO = METODOS_PAGO_USD + METODOS_PAGO_BS

# session_id -> {"carritos": {...}, "activo": str, "contador": int}
_sesiones: dict[str, dict] = {}


def _carrito_vacio(id_carrito: str, nombre: str) -> dict:
    return {
        "id": id_carrito,
        "nombre": nombre,
        "cliente": None,
        "tipo_venta": "Formal",
        "metodo_pago": "Efectivo",
        "items": [],
        "creado_en": datetime.datetime.now().strftime("%H:%M:%S"),
    }


def _estado_sesion(session_id: str) -> dict:
    """Devuelve (creando si hace falta) el namespace de carritos aislado
    para una sesión de Flet. Cada sesión arranca con un único "Carrito 1"."""
    estado = _sesiones.get(session_id)
    if estado is None:
        estado = {
            "carritos": {"Carrito 1": _carrito_vacio("Carrito 1", "Carrito 1 (Principal)")},
            "activo": "Carrito 1",
            "contador": 1,
        }
        _sesiones[session_id] = estado
    return estado


def limpiar_sesion(session_id: str) -> None:
    """Libera el estado de carritos de una sesión (llamado al desconectarse
    el navegador) para no acumular memoria indefinidamente en el servidor."""
    _sesiones.pop(session_id, None)


def obtener_todos_los_carritos(session_id: str) -> dict:
    """Devuelve el diccionario de carritos de la sesión indicada."""
    return _estado_sesion(session_id)["carritos"]


def obtener_id_carrito_activo(session_id: str) -> str:
    """Devuelve la clave del carrito activo actual de la sesión."""
    estado = _estado_sesion(session_id)
    if estado["activo"] not in estado["carritos"] and estado["carritos"]:
        estado["activo"] = list(estado["carritos"].keys())[0]
    return estado["activo"]


def obtener_carrito_activo(session_id: str) -> dict:
    """Devuelve la estructura de datos del carrito activo de la sesión."""
    estado = _estado_sesion(session_id)
    cid = obtener_id_carrito_activo(session_id)
    if cid not in estado["carritos"]:
        estado["carritos"][cid] = _carrito_vacio(cid, f"Carrito {cid}")
    return estado["carritos"][cid]


def cambiar_carrito_activo(session_id: str, id_carrito: str) -> dict:
    """Conmuta el carrito activo de la sesión hacia un ID existente."""
    estado = _estado_sesion(session_id)
    if id_carrito in estado["carritos"]:
        estado["activo"] = id_carrito
    return obtener_carrito_activo(session_id)


def crear_nuevo_carrito(session_id: str, nombre_personalizado: str = None) -> dict:
    """Crea un nuevo carrito independiente en la sesión y lo activa."""
    estado = _estado_sesion(session_id)
    estado["contador"] += 1
    nuevo_id = f"Carrito {estado['contador']}"
    nombre = nombre_personalizado or nuevo_id

    estado["carritos"][nuevo_id] = _carrito_vacio(nuevo_id, nombre)
    estado["activo"] = nuevo_id
    return estado["carritos"][nuevo_id]


def eliminar_carrito(session_id: str, id_carrito: str) -> bool:
    """Elimina un carrito de la sesión por su ID (siempre deja al menos uno)."""
    estado = _estado_sesion(session_id)
    carritos = estado["carritos"]
    if id_carrito not in carritos:
        return False

    if len(carritos) == 1:
        # Si es el único, solo vaciarlo en vez de dejar la sesión sin carritos.
        c = carritos[id_carrito]
        c["cliente"] = None
        c["tipo_venta"] = "Formal"
        c["metodo_pago"] = "Efectivo"
        c["items"] = []
        return True

    del carritos[id_carrito]
    if estado["activo"] == id_carrito:
        estado["activo"] = list(carritos.keys())[0]
    return True


def vincular_cliente_a_carrito(session_id: str, cliente: dict, id_carrito: str = None) -> dict:
    """Asocia un cliente a un carrito específico o al activo de la sesión."""
    estado = _estado_sesion(session_id)
    c = estado["carritos"][id_carrito] if id_carrito and id_carrito in estado["carritos"] else obtener_carrito_activo(session_id)
    c["cliente"] = cliente
    c["tipo_venta"] = "Formal"
    return c


def desvincular_cliente(session_id: str, id_carrito: str = None) -> dict:
    """Elimina la asociación de cliente del carrito especificado o activo."""
    estado = _estado_sesion(session_id)
    c = estado["carritos"][id_carrito] if id_carrito and id_carrito in estado["carritos"] else obtener_carrito_activo(session_id)
    c["cliente"] = None
    return c


def establecer_metodo_pago(session_id: str, metodo: str, id_carrito: str = None) -> dict:
    """Fija el método de pago elegido por el cliente en un carrito específico
    o en el activo de la sesión. Determina qué total se cobra: Efectivo/Binance
    cobran en dólares (Precio USD Efectivo); Pago Móvil/Transferencia cobran el
    equivalente en Bolívares (Precio USD BCV x tasa vigente)."""
    if metodo not in METODOS_PAGO:
        raise ValueError(f"Método de pago inválido: {metodo}")
    estado = _estado_sesion(session_id)
    c = estado["carritos"][id_carrito] if id_carrito and id_carrito in estado["carritos"] else obtener_carrito_activo(session_id)
    c["metodo_pago"] = metodo
    return c


def agregar_o_actualizar_producto(
    session_id: str, producto: dict, cantidad: float = 1.0,
    tasa_bcv: float | None = None, id_carrito: str = None,
) -> tuple[dict, bool]:
    """
    Añade un producto al carrito especificado o activo de la sesión.
    Retorna (carrito_actualizado, fue_agregado_nuevo).

    Venezuela maneja dos precios en dólares por producto: el Precio USD
    Efectivo (`precio_dolares`, lo que se paga en dólares físicos) y el
    Precio USD BCV (`precio_bcv`, referencia independiente en dólares para
    pago en Bolívares). El monto en Bolívares del renglón SIEMPRE se
    recalcula en vivo como Precio USD BCV x tasa BCV vigente — nunca se
    confía en un monto ya convertido y potencialmente desactualizado. Si el
    producto no tiene un Precio USD BCV propio configurado, se usa el
    Precio USD Efectivo como referencia de conversión.
    """
    estado = _estado_sesion(session_id)
    c = estado["carritos"][id_carrito] if id_carrito and id_carrito in estado["carritos"] else obtener_carrito_activo(session_id)
    items = c["items"]

    codigo = producto["codigo"]
    precio_usd = float(producto.get("precio_dolares", 0.0))
    precio_usd_bcv_ref = float(producto.get("precio_bcv", 0.0)) or precio_usd
    tasa_actual = tasa_bcv if tasa_bcv else obtener_estado_tasa().get("tasa", 0.0)
    precio_bcv = round(precio_usd_bcv_ref * tasa_actual, 2)
    nombre_corto = producto.get("nombre_referencia_corto") or producto.get("referencia") or producto.get("descripcion_general", "")

    existente = next((i for i in items if i["codigo"] == codigo), None)

    if existente:
        existente["cantidad"] += cantidad
        existente["subtotal_usd"] = existente["cantidad"] * existente["precio_usd"]
        existente["subtotal_bcv"] = existente["cantidad"] * existente["precio_bcv"]
        fue_nuevo = False
    else:
        items.append({
            "codigo": codigo,
            "nombre_corto": nombre_corto,
            "cantidad": cantidad,
            "precio_usd": precio_usd,
            # Referencia USD BCV del producto, conservada en el renglón para
            # poder recalcular el monto en Bolívares si la tasa cambia
            # a mitad de la venta (ver VentasView.on_tasa_actualizada).
            "precio_usd_bcv_ref": precio_usd_bcv_ref,
            "precio_bcv": precio_bcv,
            "subtotal_usd": cantidad * precio_usd,
            "subtotal_bcv": cantidad * precio_bcv,
        })
        fue_nuevo = True

    return c, fue_nuevo


def editar_item_en_carrito(
    session_id: str, codigo: str, nueva_cantidad: float, nuevo_precio_usd: float,
    nuevo_precio_usd_bcv: float | None = None,
    tasa_bcv: float | None = None, id_carrito: str = None,
) -> bool:
    """Modifica la cantidad y/o los precios unitarios de un renglón del
    carrito, manteniendo el Precio USD Efectivo y el Precio USD BCV como los
    dos valores independientes que son (ver regla de negocio Venezuela): el
    BCV es el que se usa para calcular el monto en Bolívares, y normalmente
    es distinto (mayor) al Efectivo.

    `nuevo_precio_usd_bcv` es opcional únicamente por compatibilidad con
    llamadores antiguos que no lo pasen — si se omite, se conserva el valor
    de referencia BCV que ya tenía el renglón (NUNCA se colapsa al precio
    Efectivo editado, que fue el bug original: guardar solo la cantidad ya
    igualaba silenciosamente ambos precios)."""
    estado = _estado_sesion(session_id)
    c = estado["carritos"][id_carrito] if id_carrito and id_carrito in estado["carritos"] else obtener_carrito_activo(session_id)
    tasa_actual = tasa_bcv if tasa_bcv else obtener_estado_tasa().get("tasa", 0.0)
    for item in c["items"]:
        if item["codigo"] == codigo:
            precio_bcv_ref = (
                nuevo_precio_usd_bcv if nuevo_precio_usd_bcv is not None
                else item.get("precio_usd_bcv_ref", item["precio_usd"])
            )
            item["cantidad"] = nueva_cantidad
            item["precio_usd"] = nuevo_precio_usd
            item["precio_usd_bcv_ref"] = precio_bcv_ref
            item["precio_bcv"] = round(precio_bcv_ref * tasa_actual, 2)
            item["subtotal_usd"] = nueva_cantidad * item["precio_usd"]
            item["subtotal_bcv"] = nueva_cantidad * item["precio_bcv"]
            return True
    return False


def remover_item_de_carrito(session_id: str, codigo: str, id_carrito: str = None) -> bool:
    """Remueve un renglón del carrito especificado o activo de la sesión."""
    estado = _estado_sesion(session_id)
    c = estado["carritos"][id_carrito] if id_carrito and id_carrito in estado["carritos"] else obtener_carrito_activo(session_id)
    inicial = len(c["items"])
    c["items"] = [i for i in c["items"] if i["codigo"] != codigo]
    return len(c["items"]) < inicial


def vaciar_carrito_activo(session_id: str) -> None:
    """Limpia todos los renglones y cliente del carrito activo de la sesión."""
    c = obtener_carrito_activo(session_id)
    c["items"] = []
    c["cliente"] = None
