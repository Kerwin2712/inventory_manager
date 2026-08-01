"""
Administrador global de carritos de compra y estado de venta para la aplicación.
Permite gestionar múltiples carritos en simultáneo (guardar/recuperar),
asociar clientes desde Cartera y agregar productos desde Inventario o Ventas.
"""

import datetime

_carritos = {
    "Carrito 1": {
        "id": "Carrito 1",
        "nombre": "Carrito 1 (Principal)",
        "cliente": None,
        "tipo_venta": "Formal",
        "items": [],
        "creado_en": datetime.datetime.now().strftime("%H:%M:%S")
    }
}

_id_carrito_activo = "Carrito 1"
_contador_carritos = 1


def obtener_todos_los_carritos() -> dict:
    """Devuelve el diccionario completo de carritos."""
    return _carritos


def obtener_id_carrito_activo() -> str:
    """Devuelve la clave del carrito activo actual."""
    global _id_carrito_activo
    if _id_carrito_activo not in _carritos and _carritos:
        _id_carrito_activo = list(_carritos.keys())[0]
    return _id_carrito_activo


def obtener_carrito_activo() -> dict:
    """Devuelve la estructura de datos del carrito activo."""
    cid = obtener_id_carrito_activo()
    if cid not in _carritos:
        _carritos[cid] = {
            "id": cid,
            "nombre": f"Carrito {cid}",
            "cliente": None,
            "tipo_venta": "Formal",
            "items": [],
            "creado_en": datetime.datetime.now().strftime("%H:%M:%S")
        }
    return _carritos[cid]


def cambiar_carrito_activo(id_carrito: str) -> dict:
    """Conmuta el carrito activo hacia un ID existente."""
    global _id_carrito_activo
    if id_carrito in _carritos:
        _id_carrito_activo = id_carrito
    return obtener_carrito_activo()


def crear_nuevo_carrito(nombre_personalizado: str = None) -> dict:
    """Crea un nuevo carrito independiente y lo establece como activo."""
    global _id_carrito_activo, _contador_carritos
    _contador_carritos += 1
    nuevo_id = f"Carrito {_contador_carritos}"
    nombre = nombre_personalizado or f"Carrito {_contador_carritos}"

    _carritos[nuevo_id] = {
        "id": nuevo_id,
        "nombre": nombre,
        "cliente": None,
        "tipo_venta": "Formal",
        "items": [],
        "creado_en": datetime.datetime.now().strftime("%H:%M:%S")
    }
    _id_carrito_activo = nuevo_id
    return _carritos[nuevo_id]


def eliminar_carrito(id_carrito: str) -> bool:
    """Elimina un carrito por su ID (siempre deja al menos uno activo)."""
    global _id_carrito_activo
    if id_carrito in _carritos:
        del _carritos[id_carrito]
        if not _carritos:
            crear_nuevo_carrito()
        elif _id_carrito_activo == id_carrito:
            _id_carrito_activo = list(_carritos.keys())[0]
        return True
    return False


def vincular_cliente_a_carrito(cliente: dict, id_carrito: str = None) -> dict:
    """Asocia un cliente a un carrito específico o al carrito activo."""
    c = _carritos[id_carrito] if id_carrito and id_carrito in _carritos else obtener_carrito_activo()
    c["cliente"] = cliente
    c["tipo_venta"] = "Formal"
    return c


def desvincular_cliente(id_carrito: str = None) -> dict:
    """Elimina la asociación de cliente del carrito especificado o activo."""
    c = _carritos[id_carrito] if id_carrito and id_carrito in _carritos else obtener_carrito_activo()
    c["cliente"] = None
    return c


def agregar_o_actualizar_producto(producto: dict, cantidad: float = 1.0, tasa_bcv: float = 1.0, id_carrito: str = None) -> tuple[dict, bool]:
    """
    Añade un producto al carrito especificado o activo.
    Retorna (carrito_actualizado, fue_agregado_nuevo).
    """
    c = _carritos[id_carrito] if id_carrito and id_carrito in _carritos else obtener_carrito_activo()
    items = c["items"]

    codigo = producto["codigo"]
    precio_usd = float(producto.get("precio_dolares", 0.0))
    precio_bcv = float(producto.get("precio_bcv", 0.0)) if producto.get("precio_bcv") else round(precio_usd * tasa_bcv, 2)
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
            "precio_bcv": precio_bcv,
            "subtotal_usd": cantidad * precio_usd,
            "subtotal_bcv": cantidad * precio_bcv,
        })
        fue_nuevo = True

    return c, fue_nuevo


def editar_item_en_carrito(codigo: str, nueva_cantidad: float, nuevo_precio_usd: float, tasa_bcv: float = 1.0, id_carrito: str = None) -> bool:
    """Modifica la cantidad y/o el precio unitario de un renglón del carrito."""
    c = _carritos[id_carrito] if id_carrito and id_carrito in _carritos else obtener_carrito_activo()
    for item in c["items"]:
        if item["codigo"] == codigo:
            item["cantidad"] = nueva_cantidad
            item["precio_usd"] = nuevo_precio_usd
            item["precio_bcv"] = round(nuevo_precio_usd * tasa_bcv, 2)
            item["subtotal_usd"] = nueva_cantidad * item["precio_usd"]
            item["subtotal_bcv"] = nueva_cantidad * item["precio_bcv"]
            return True
    return False


def remover_item_de_carrito(codigo: str, id_carrito: str = None) -> bool:
    """Remueve un renglón del carrito."""
    c = _carritos[id_carrito] if id_carrito and id_carrito in _carritos else obtener_carrito_activo()
    inicial = len(c["items"])
    c["items"] = [i for i in c["items"] if i["codigo"] != codigo]
    return len(c["items"]) < inicial


def vaciar_carrito_activo() -> None:
    """Limpia todos los renglones y cliente del carrito activo."""
    c = obtener_carrito_activo()
    c["items"] = []
    c["cliente"] = None
