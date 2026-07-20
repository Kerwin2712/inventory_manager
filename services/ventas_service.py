import sqlite3
from core.database import get_connection

def procesar_venta(tipo_venta: str, cliente_id: str = None, lineas: list = None) -> dict:
    """Procesa una transacción de venta registrando cabecera, detalles y descontando stock."""
    if not lineas or len(lineas) == 0:
        raise ValueError("La venta debe contener al menos un producto.")

    tipo_venta_clean = tipo_venta.strip().capitalize() if tipo_venta else ""
    if tipo_venta_clean not in ["Formal", "Informal"]:
        raise ValueError("El tipo de venta debe ser 'Formal' o 'Informal'.")

    conn = get_connection()
    conn.isolation_level = None  # Control transaccional explícito
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()

        # Validar tipo de venta y cliente según ERS 3.4
        if tipo_venta_clean == "Formal":
            if not cliente_id or not str(cliente_id).strip():
                raise ValueError("El cliente es obligatorio para ventas formales.")
            cliente_id = str(cliente_id).strip()
            cursor.execute("SELECT cedula_rif FROM clientes WHERE cedula_rif = ?", (cliente_id,))
            if not cursor.fetchone():
                raise ValueError(f"El cliente con Cédula/RIF '{cliente_id}' no está registrado.")
        else:
            cliente_id = None

        conn.execute("BEGIN TRANSACTION")

        # Procesar líneas y pre-calcular subtotales
        total_usd = 0.0
        total_bcv = 0.0
        items_procesados = []

        for item in lineas:
            codigo = item.get("producto_codigo") or item.get("codigo")
            if not codigo:
                raise ValueError("Cada línea debe especificar el código del producto.")

            cantidad = float(item.get("cantidad", 0))
            if cantidad <= 0:
                raise ValueError(f"La cantidad para el producto {codigo} debe ser mayor a cero.")

            # Verificar existencia del producto y stock suficiente
            cursor.execute(
                "SELECT existencia, precio_dolares, precio_bcv FROM productos WHERE codigo = ?",
                (codigo,)
            )
            prod = cursor.fetchone()
            if not prod:
                raise ValueError(f"El producto con código {codigo} no existe.")

            existencia_actual = prod["existencia"]
            if existencia_actual < cantidad:
                raise ValueError(f"Stock insuficiente para el producto {codigo}")

            precio_usd = float(item.get("precio_unitario_usd", prod["precio_dolares"]))
            precio_bcv = float(item.get("precio_unitario_bcv", prod["precio_bcv"]))
            subtotal_usd = float(item.get("subtotal_usd", cantidad * precio_usd))
            subtotal_bcv = float(item.get("subtotal_bcv", cantidad * precio_bcv))

            total_usd += subtotal_usd
            total_bcv += subtotal_bcv

            items_procesados.append({
                "codigo": codigo,
                "cantidad": cantidad,
                "precio_usd": precio_usd,
                "precio_bcv": precio_bcv,
                "subtotal_usd": subtotal_usd,
                "subtotal_bcv": subtotal_bcv
            })

        # Insertar cabecera de la venta
        cursor.execute(
            """
            INSERT INTO ventas (tipo_venta, cliente_id, total_usd, total_bcv)
            VALUES (?, ?, ?, ?)
            """,
            (tipo_venta_clean, cliente_id, total_usd, total_bcv)
        )
        venta_id = cursor.lastrowid

        # Insertar detalle y actualizar existencias
        for item in items_procesados:
            cursor.execute(
                """
                INSERT INTO ventas_detalle (
                    venta_id, producto_codigo, cantidad,
                    precio_unitario_usd, precio_unitario_bcv,
                    subtotal_usd, subtotal_bcv
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    venta_id, item["codigo"], item["cantidad"],
                    item["precio_usd"], item["precio_bcv"],
                    item["subtotal_usd"], item["subtotal_bcv"]
                )
            )
            cursor.execute(
                """
                UPDATE productos
                SET existencia = existencia - ?,
                    fecha_ultima_modificacion = CURRENT_TIMESTAMP
                WHERE codigo = ?
                """,
                (item["cantidad"], item["codigo"])
            )

        conn.execute("COMMIT")
        return {
            "venta_id": venta_id,
            "tipo_venta": tipo_venta_clean,
            "cliente_id": cliente_id,
            "total_usd": total_usd,
            "total_bcv": total_bcv,
            "lineas_count": len(items_procesados)
        }

    except Exception as e:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise e
    finally:
        conn.close()
