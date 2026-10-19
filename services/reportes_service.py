import sqlite3
from datetime import datetime

from core.database import get_connection, get_setting, set_setting
# El listado de Ventas Diarias necesita saber en qué moneda se cobró cada
# método para elegir el monto correcto; se reutiliza la tupla que ya define el
# carrito en vez de duplicar la lista (si mañana entra un método nuevo, el
# reporte lo hereda sin tocar este módulo).
from services.cart_manager import METODOS_PAGO_BS

# ERS 3.6: "Auditoría preventiva ... cuando la Existencia cae por debajo del
# stock mínimo PARAMETRIZADO". Se persiste en app_settings en vez de un
# literal fijo en el código.
_KEY_STOCK_MINIMO = "stock_minimo"
_STOCK_MINIMO_DEFAULT = 5.0


def obtener_stock_minimo() -> float:
    """Recupera el stock mínimo parametrizado (ERS 3.6), con valor por defecto."""
    try:
        return float(get_setting(_KEY_STOCK_MINIMO, str(_STOCK_MINIMO_DEFAULT)))
    except (TypeError, ValueError):
        return _STOCK_MINIMO_DEFAULT


def actualizar_stock_minimo(valor: float) -> float:
    """Actualiza el stock mínimo parametrizado usado por la auditoría preventiva."""
    valor = float(valor)
    if valor <= 0:
        raise ValueError("El stock mínimo debe ser un valor positivo mayor a cero.")
    set_setting(_KEY_STOCK_MINIMO, str(valor))
    return valor


# Consulta base de la auditoría preventiva. El JOIN con proveedores aísla el
# contacto de reposición (ERS 3.6); el WHERE lo inyecta cada criterio.
_SQL_ALERTAS = """
    SELECT
        p.codigo,
        p.referencia,
        p.nombre_referencia_corto,
        p.existencia,
        p.descripcion_general,
        p.departamento,
        p.marca,
        p.alerta_stock_minimo,
        prov.empresa AS proveedor_nombre,
        prov.telefono AS proveedor_telefono,
        prov.contacto AS proveedor_contacto
    FROM productos p
    LEFT JOIN proveedores prov ON p.proveedor_id = prov.id
    WHERE {condicion}
"""


def _fila_a_alerta(r, minimo: float, origen: str) -> dict:
    """Arma el diccionario de alerta con las claves que consume el Dashboard
    (`ui/views/dashboard_view.py`), más `alerta_stock_minimo` y `origen`.

    `referencia`, `descripcion_general` y `marca` se agregaron para la
    Auditoría Preventiva a ancho completo (especificación 17/10/2026): con la
    tarjeta ocupando media pantalla solo cabía el nombre corto, y el cliente
    pedía "la información completa del item"."""
    propio = r["alerta_stock_minimo"]
    return {
        "codigo": r["codigo"],
        "referencia": r["referencia"] or "",
        "nombre_corto": r["nombre_referencia_corto"] or r["codigo"],
        "descripcion_general": r["descripcion_general"] or "",
        "existencia": float(r["existencia"] or 0.0),
        "minimo": float(minimo),
        "departamento": r["departamento"] or "General",
        "marca": r["marca"] or "",
        "proveedor_nombre": r["proveedor_nombre"] or "Sin Proveedor Asignado",
        "proveedor_telefono": r["proveedor_telefono"] or "N/A",
        "proveedor_contacto": r["proveedor_contacto"] or "N/A",
        "alerta_stock_minimo": int(propio) if propio is not None else None,
        "origen": origen,
    }


def obtener_alertas_stock_por_producto() -> list[dict]:
    """Alertas generadas por el umbral PROPIO de cada producto: se dispara
    cuando `alerta_stock_minimo >= existencia` (el comparador acordado con el
    cliente, la igualdad SÍ alerta). `minimo` es el umbral propio y `origen`
    vale `"producto"`."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        _SQL_ALERTAS.format(
            condicion="p.alerta_stock_minimo IS NOT NULL AND p.alerta_stock_minimo >= p.existencia"
        )
        + " ORDER BY p.existencia ASC"
    )
    rows = cursor.fetchall()
    conn.close()
    return [_fila_a_alerta(r, float(r["alerta_stock_minimo"]), "producto") for r in rows]


def obtener_alertas_stock(minimo: float | None = None) -> list[dict]:
    """
    Auditoría preventiva (ERS 3.6): une los dos criterios de alerta sin
    duplicar productos.

    - Umbral GLOBAL parametrizado en `app_settings`: `existencia < minimo`
      → `origen == "global"` y `minimo` es ese umbral global.
    - Umbral PROPIO del producto: `alerta_stock_minimo >= existencia`
      → `origen == "producto"` y `minimo` es el umbral propio.

    Si un producto califica por ambos criterios prevalece `origen == "producto"`.
    Si `minimo` no se especifica, usa el valor parametrizado en app_settings.
    """
    if minimo is None:
        minimo = obtener_stock_minimo()

    # El umbral propio tiene precedencia: se indexa primero por código.
    alertas: dict[str, dict] = {a["codigo"]: a for a in obtener_alertas_stock_por_producto()}

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(_SQL_ALERTAS.format(condicion="p.existencia < ?"), (minimo,))
    rows = cursor.fetchall()
    conn.close()

    for r in rows:
        if r["codigo"] in alertas:
            continue
        alertas[r["codigo"]] = _fila_a_alerta(r, float(minimo), "global")

    return sorted(alertas.values(), key=lambda a: (a["existencia"], a["codigo"]))


def obtener_top_ventas(rango_temporal: str = "Hoy", limite: int = 10) -> list[dict]:
    """
    Consulta ventas y ventas_detalle agrupando por producto_codigo,
    sumando las cantidades vendidas y ordenando de mayor a menor.
    rango_temporal: 'Hoy', 'Semana', 'Mes', 'Año'.
    limite: 10 o 100.
    """
    conn = get_connection()
    cursor = conn.cursor()

    # Determinar la condición de fecha según el rango temporal
    rango = (rango_temporal or "Hoy").strip().capitalize()
    if rango == "Hoy":
        where_fecha = "DATE(v.fecha) = DATE('now', 'localtime')"
    elif rango == "Semana":
        where_fecha = "v.fecha >= DATETIME('now', '-7 days', 'localtime')"
    elif rango == "Mes":
        where_fecha = "v.fecha >= DATETIME('now', '-30 days', 'localtime')"
    elif rango == "Año":
        where_fecha = "v.fecha >= DATETIME('now', '-365 days', 'localtime')"
    else:
        where_fecha = "1=1"

    limite_val = int(limite) if int(limite) > 0 else 10

    query = f"""
        SELECT 
            vd.producto_codigo,
            p.nombre_referencia_corto,
            p.departamento AS categoria,
            SUM(vd.cantidad) AS total_vendido,
            SUM(vd.subtotal_usd) AS total_usd
        FROM ventas_detalle vd
        INNER JOIN ventas v ON vd.venta_id = v.id
        LEFT JOIN productos p ON vd.producto_codigo = p.codigo
        WHERE {where_fecha}
        GROUP BY vd.producto_codigo, p.nombre_referencia_corto, p.departamento
        ORDER BY total_vendido DESC
        LIMIT ?
    """

    cursor.execute(query, (limite_val,))
    rows = cursor.fetchall()
    conn.close()

    top_list = []
    for idx, r in enumerate(rows, start=1):
        top_list.append({
            "posicion": str(idx),
            "codigo": r["producto_codigo"],
            "nombre_corto": r["nombre_referencia_corto"] or r["producto_codigo"],
            "categoria": r["categoria"] or "General",
            "total_vendido": float(r["total_vendido"] or 0.0),
            "total_usd": float(r["total_usd"] or 0.0)
        })

    return top_list


def obtener_metricas_dashboard() -> dict:
    """
    Calcula las métricas analíticas reales para las tarjetas superiores del Dashboard:
    - Ventas del día (Total USD y variación aproximada vs ayer).
    - Productos en Stock (Total unidades y departamentos distintos).
    - Alertas de Stock Bajo (Cantidad de productos con existencia < 5).
    """
    conn = get_connection()
    cursor = conn.cursor()

    # 1. Ventas del día
    cursor.execute("""
        SELECT COALESCE(SUM(total_usd), 0.0) AS ventas_hoy
        FROM ventas
        WHERE DATE(fecha) = DATE('now', 'localtime')
    """)
    ventas_hoy = float(cursor.fetchone()["ventas_hoy"] or 0.0)

    cursor.execute("""
        SELECT COALESCE(SUM(total_usd), 0.0) AS ventas_ayer
        FROM ventas
        WHERE DATE(fecha) = DATE('now', '-1 day', 'localtime')
    """)
    ventas_ayer = float(cursor.fetchone()["ventas_ayer"] or 0.0)

    variacion_pct = 0.0
    if ventas_ayer > 0:
        variacion_pct = ((ventas_hoy - ventas_ayer) / ventas_ayer) * 100.0
    elif ventas_hoy > 0:
        variacion_pct = 100.0

    # 2. Productos en Stock
    cursor.execute("""
        SELECT 
            COALESCE(SUM(existencia), 0.0) AS total_unidades,
            COUNT(DISTINCT departamento) AS total_categorias
        FROM productos
    """)
    row_stock = cursor.fetchone()
    total_unidades = float(row_stock["total_unidades"] or 0.0)
    total_categorias = int(row_stock["total_categorias"] or 0)

    # 3. Alertas de Stock Bajo: mismo criterio combinado que
    #    `obtener_alertas_stock` (umbral global parametrizado + umbral propio
    #    del producto), para que la tarjeta y la tabla nunca discrepen.
    stock_minimo = obtener_stock_minimo()
    cursor.execute("""
        SELECT COUNT(*) AS total_criticos
        FROM productos
        WHERE existencia < ?
           OR (alerta_stock_minimo IS NOT NULL AND alerta_stock_minimo >= existencia)
    """, (stock_minimo,))
    total_criticos = int(cursor.fetchone()["total_criticos"] or 0)

    conn.close()

    return {
        "ventas_hoy_usd": ventas_hoy,
        "ventas_ayer_usd": ventas_ayer,
        "variacion_pct": variacion_pct,
        "total_unidades": total_unidades,
        "total_categorias": total_categorias,
        "total_criticos": total_criticos
    }


# Criterio de "venta de hoy". Se repite textualmente el que ya usan
# `obtener_metricas_dashboard` y `obtener_top_ventas` para que la tarjeta
# "Ventas del Día" y el listado "Ventas Diarias" del Inicio nunca discrepen:
# si uno cuenta una venta, el otro también. Limitación conocida y heredada:
# `ventas.fecha` se escribe con el `CURRENT_TIMESTAMP` de SQLite (UTC) y aquí
# se compara contra la fecha LOCAL, así que las ventas hechas de noche
# (después de las 20:00 en Venezuela, UTC-4) ya cargan la fecha UTC del día
# siguiente y quedan fuera del "hoy" de ambos reportes. Corregirlo exige
# normalizar la escritura de `ventas.fecha` a hora local (como se hizo con
# `productos.created_at`), que es un cambio de datos fuera de este módulo.
_SQL_VENTA_ES_DE_HOY = "DATE(v.fecha) = DATE('now', 'localtime')"

# Formato de "Fecha y hora" que espera la lista de Ventas Diarias. Se arma en
# el servicio y no en la vista para que la vista no tenga que conocer los dos
# formatos en que SQLite puede devolver un DATETIME.
_FORMATOS_FECHA = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f")


def _formatear_fecha_hora(valor) -> str:
    """Convierte el DATETIME crudo de SQLite a `dd/mm/aaaa hh:mm`.

    Si el valor no respeta ninguno de los formatos conocidos se devuelve tal
    cual: en una lista de auditoría es preferible mostrar el dato crudo antes
    que esconder la fila o reventar la vista por un timestamp atípico.
    """
    if not valor:
        return "-"
    texto = str(valor)
    for formato in _FORMATOS_FECHA:
        try:
            return datetime.strptime(texto, formato).strftime("%d/%m/%Y %H:%M")
        except ValueError:
            continue
    return texto


def obtener_ventas_del_dia() -> list[dict]:
    """
    Listado de las ventas del día de hoy para la ventana "Ventas Diarias" del
    área de Inicio: la más reciente primero y la más vieja al final.

    Devuelve, por cada venta (no por renglón), las casillas que pide la
    especificación del 17/10/2026:

    - `fecha_hora`: `dd/mm/aaaa hh:mm` ya formateado.
    - `descripcion_corta`: los nombres cortos de TODOS los artículos del
      carrito concatenados con ", ". Se arma en Python recorriendo el detalle
      ordenado por `vd.id` en vez de con `GROUP_CONCAT`, porque SQLite no
      garantiza el orden de agregación y el texto saldría distinto entre
      ejecuciones (una lista que se reordena sola se lee como un error).
    - `metodo_pago` y `referencia_pago`: la referencia solo viaja cuando el
      método NO es Efectivo (en Efectivo no existe comprobante que mostrar).
    - `cantidad_articulos`: unidades vendidas en el carrito (suma de
      `vd.cantidad`), y `total_lineas` como dato auxiliar.
    - `monto_total` y `moneda`: el monto REALMENTE cobrado
      (`ventas.monto_cobrado`, que ya descuenta el descuento aplicado). Las
      ventas anteriores a la actualización de octubre 2026 lo tienen en NULL,
      así que cae con elegancia al total a precio de lista de la moneda del
      método: `total_bcv` para los métodos en bolívares y `total_usd` para el
      resto.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(f"""
        SELECT
            v.id,
            v.fecha,
            v.tipo_venta,
            v.cliente_id,
            v.metodo_pago,
            v.referencia_pago,
            v.total_usd,
            v.total_bcv,
            v.monto_cobrado
        FROM ventas v
        WHERE {_SQL_VENTA_ES_DE_HOY}
        ORDER BY v.fecha DESC, v.id DESC
    """)
    ventas = cursor.fetchall()

    # Un solo SELECT para el detalle de todas las ventas del día (en lugar de
    # una consulta por venta): el día puede traer decenas de notas y la lista
    # se reconstruye en cada `rebuild_ui()` del Dashboard.
    detalle_por_venta: dict[int, list[sqlite3.Row]] = {}
    if ventas:
        marcadores = ",".join("?" for _ in ventas)
        cursor.execute(f"""
            SELECT
                vd.venta_id,
                vd.producto_codigo,
                vd.cantidad,
                p.nombre_referencia_corto
            FROM ventas_detalle vd
            LEFT JOIN productos p ON vd.producto_codigo = p.codigo
            WHERE vd.venta_id IN ({marcadores})
            ORDER BY vd.venta_id ASC, vd.id ASC
        """, tuple(v["id"] for v in ventas))
        for r in cursor.fetchall():
            detalle_por_venta.setdefault(r["venta_id"], []).append(r)

    conn.close()

    listado = []
    for v in ventas:
        lineas = detalle_por_venta.get(v["id"], [])
        # El nombre corto puede faltar (producto eliminado o sin referencia
        # corta): el código es el único identificador que siempre existe.
        nombres = [
            (r["nombre_referencia_corto"] or r["producto_codigo"] or "-")
            for r in lineas
        ]
        metodo = (v["metodo_pago"] or "Efectivo").strip()
        en_bolivares = metodo in METODOS_PAGO_BS

        monto_cobrado = v["monto_cobrado"]
        if monto_cobrado is None:
            monto_cobrado = v["total_bcv"] if en_bolivares else v["total_usd"]

        listado.append({
            "venta_id": v["id"],
            "fecha": v["fecha"],
            "fecha_hora": _formatear_fecha_hora(v["fecha"]),
            "tipo_venta": v["tipo_venta"] or "",
            "cliente_id": v["cliente_id"],
            "descripcion_corta": ", ".join(nombres) if nombres else "-",
            "metodo_pago": metodo,
            # Cadena vacía (y no None) para que la vista pueda pintarla sin
            # comprobar el tipo; el guion decorativo lo pone la vista.
            "referencia_pago": (v["referencia_pago"] or "") if metodo != "Efectivo" else "",
            "cantidad_articulos": float(sum(float(r["cantidad"] or 0.0) for r in lineas)),
            "total_lineas": len(lineas),
            "monto_total": float(monto_cobrado or 0.0),
            "moneda": "Bs" if en_bolivares else "USD",
        })

    return listado


def obtener_historial_producto(codigo: str) -> dict:
    """Historial clínico de un producto (ERS 3.6): movimientos cronológicos
    de venta (cuándo, cantidad, tipo de venta y cliente) y el proveedor
    actualmente asociado.

    NOTA / limitación conocida: el esquema actual no registra un historial de
    COMPRAS/reposición por proveedor (solo el `proveedor_id` vigente en
    `productos`) — el ERS pide también "cuándo se compró, a qué proveedor",
    lo cual requeriría una tabla de órdenes de compra que no existe todavía.
    Esta función documenta y expone el proveedor vigente como aproximación.
    """
    codigo = (codigo or "").strip()
    if not codigo:
        raise ValueError("Debe especificar un código de producto.")

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM productos WHERE codigo = ?", (codigo,))
        row_prod = cursor.fetchone()
        if not row_prod:
            raise ValueError(f"El producto con código '{codigo}' no existe.")
        producto = dict(row_prod)

        cursor.execute("""
            SELECT v.id AS venta_id, v.fecha, v.tipo_venta, v.cliente_id,
                   vd.cantidad, vd.precio_unitario_usd, vd.precio_unitario_bcv, vd.subtotal_usd
            FROM ventas_detalle vd
            INNER JOIN ventas v ON vd.venta_id = v.id
            WHERE vd.producto_codigo = ?
            ORDER BY v.fecha DESC
        """, (codigo,))
        movimientos_venta = [dict(r) for r in cursor.fetchall()]

        proveedor_actual = None
        if producto.get("proveedor_id"):
            cursor.execute(
                "SELECT empresa, contacto, telefono, correo FROM proveedores WHERE id = ?",
                (producto["proveedor_id"],)
            )
            row_prov = cursor.fetchone()
            if row_prov:
                proveedor_actual = dict(row_prov)

    return {
        "producto": producto,
        "proveedor_actual": proveedor_actual,
        "movimientos_venta": movimientos_venta,
        "total_vendido": sum(float(m["cantidad"]) for m in movimientos_venta),
    }
