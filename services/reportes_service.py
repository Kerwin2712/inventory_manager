import sqlite3
from core.database import get_connection, get_setting, set_setting

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


def obtener_alertas_stock(minimo: float | None = None) -> list[dict]:
    """
    Consulta la tabla productos y retorna los ítems donde existencia < minimo,
    haciendo un JOIN con proveedores para aislar y devolver el contacto del proveedor (ERS 3.6).
    Si `minimo` no se especifica, usa el valor parametrizado en app_settings.
    """
    if minimo is None:
        minimo = obtener_stock_minimo()

    conn = get_connection()
    cursor = conn.cursor()
    
    query = """
        SELECT 
            p.codigo,
            p.nombre_referencia_corto,
            p.existencia,
            p.descripcion_general,
            p.departamento,
            prov.empresa AS proveedor_nombre,
            prov.telefono AS proveedor_telefono,
            prov.contacto AS proveedor_contacto
        FROM productos p
        LEFT JOIN proveedores prov ON p.proveedor_id = prov.id
        WHERE p.existencia < ?
        ORDER BY p.existencia ASC
    """
    
    cursor.execute(query, (minimo,))
    rows = cursor.fetchall()
    conn.close()

    alertas = []
    for r in rows:
        alertas.append({
            "codigo": r["codigo"],
            "nombre_corto": r["nombre_referencia_corto"] or r["codigo"],
            "existencia": float(r["existencia"] or 0.0),
            "minimo": float(minimo),
            "departamento": r["departamento"] or "General",
            "proveedor_nombre": r["proveedor_nombre"] or "Sin Proveedor Asignado",
            "proveedor_telefono": r["proveedor_telefono"] or "N/A",
            "proveedor_contacto": r["proveedor_contacto"] or "N/A"
        })
    return alertas


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

    # 3. Alertas de Stock Bajo (usa el stock mínimo parametrizado — ERS 3.6)
    stock_minimo = obtener_stock_minimo()
    cursor.execute("""
        SELECT COUNT(*) AS total_criticos
        FROM productos
        WHERE existencia < ?
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
