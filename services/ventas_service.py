"""Registro de ventas: cabecera, detalle, descuento del stock y cobro.

Actualización de octubre 2026 — el COBRO de la venta deja de ser implícito:

- La referencia del pago es obligatoria para todo método distinto de Efectivo
  (incluido Crédito, donde hace de documento del compromiso), con una vía
  explícita de omisión que queda registrada en `ventas.referencia_omitida`.
- El monto realmente cobrado puede diferir del precio de lista (descuento).
  `total_usd`/`total_bcv` siguen siendo la suma a precio de lista — el
  "predeterminado" —, `monto_cobrado` es lo que entró en caja y
  `porcentaje_descuento` guarda la diferencia con signo.
- El método "Crédito" no cobra: genera una deuda por cobrar
  (`services/deudas_service.py`) y solo existe en Venta Formal.
"""
import sqlite3

from core.database import get_connection
from services import deudas_service
from services.cart_manager import (
    METODOS_PAGO,
    METODOS_PAGO_BS,
    METODOS_PAGO_CREDITO,
    TIPO_VENTA_FORMAL,
    calcular_suma_costos,
)
from services.permisos_service import puede_ver_costos

# Un centavo: por debajo de esto dos montos son el mismo monto (mismo criterio
# que `services/deudas_service._TOLERANCIA`). Evita rechazar un cobro por una
# diferencia de redondeo que el vendedor no puede corregir.
_TOLERANCIA = 0.005

# Único método que no exige número de referencia: el efectivo no deja rastro
# bancario que anotar.
METODO_SIN_REFERENCIA = "Efectivo"

# "El descuento mediante el método de pago a crédito tiene un límite del -5%
# OFF, solo se puede aplicar hacia arriba": el monto a crédito no puede bajar
# del 95% del precio de lista. Hacia arriba no hay tope propio del crédito.
FACTOR_MINIMO_CREDITO = 0.95


def _a_numero(valor, etiqueta: str) -> float:
    """Normaliza un monto escrito por el usuario (acepta coma decimal, que es
    el separador que usa el operador venezolano)."""
    if isinstance(valor, bool) or valor is None or valor == "":
        raise ValueError(f"ERR_VENTA_MONTO: El {etiqueta} es obligatorio.")
    if isinstance(valor, str):
        valor = valor.strip().replace(",", ".")
    try:
        return round(float(valor), 2)
    except (TypeError, ValueError):
        raise ValueError(f"ERR_VENTA_MONTO: El {etiqueta} debe ser un número válido.")


def calcular_porcentaje_descuento(monto_cobrado, monto_predeterminado) -> float:
    """Porcentaje con signo del monto cobrado respecto del precio de lista.

    `pct = (monto_manual / monto_predeterminado - 1) * 100`: negativo cuando se
    cobró por debajo de la lista (descuento, "OFF") y positivo cuando se cobró
    por encima ("ON"). Sin precio de lista no hay porcentaje posible: se
    devuelve 0 en vez de dividir por cero.
    """
    try:
        predeterminado = float(monto_predeterminado or 0.0)
    except (TypeError, ValueError):
        return 0.0
    if predeterminado <= 0:
        return 0.0
    return round((float(monto_cobrado) / predeterminado - 1.0) * 100.0, 2)


def formatear_porcentaje_descuento(porcentaje) -> str:
    """Formato que ve el usuario: `-33,75% OFF` / `+11,23% ON`.

    Coma decimal (formato del usuario) y signo siempre visible, porque el signo
    es justamente lo que distingue un descuento de un recargo. El color lo
    decide la vista (rojo para OFF, verde para ON); aquí solo se arma el texto.
    """
    pct = round(float(porcentaje or 0.0), 2)
    sufijo = "OFF" if pct < 0 else "ON"
    return f"{pct:+.2f}".replace(".", ",") + f"% {sufijo}"


def _revertir_venta(venta_id: int, items: list) -> None:
    """Transacción compensatoria: borra una venta ya confirmada y devuelve el
    stock que había descontado.

    Existe por el crédito: `deudas_service.crear_deuda` necesita el `venta_id`
    (solo existe tras insertar la cabecera) y abre su propia conexión, y SQLite
    no admite dos transacciones de escritura sobre el mismo archivo, así que la
    deuda no puede crearse dentro de la transacción de la venta. Si la deuda
    falla después del COMMIT, lo que queda es peor que no vender: una venta a
    crédito sin deuda, mercancía entregada que nadie va a cobrar. Por eso se
    deshace la venta y se propaga el error original.
    """
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA foreign_keys = ON")
            for item in items:
                cursor.execute(
                    """
                    UPDATE productos
                    SET existencia = existencia + ?,
                        fecha_ultima_modificacion = CURRENT_TIMESTAMP
                    WHERE codigo = ?
                    """,
                    (item["cantidad"], item["codigo"]),
                )
            # El detalle cae por ON DELETE CASCADE (ver `core/database.py`).
            cursor.execute("DELETE FROM ventas WHERE id = ?", (venta_id,))
            conn.commit()
    except Exception as ex:
        # Si hasta la compensación falla, el error de la deuda sigue siendo el
        # que debe ver el usuario; este queda en consola para el diagnóstico.
        print(f"[ERROR] No se pudo revertir la venta {venta_id} tras fallar la deuda: {ex}")


def procesar_venta(
    tipo_venta: str,
    cliente_id: str = None,
    lineas: list = None,
    metodo_pago: str = "Efectivo",
    referencia_pago: str = None,
    referencia_omitida: bool = False,
    monto_cobrado=None,
    porcentaje_descuento=None,
    usuario_nombre: str = None,
    fecha_limite_pago=None,
    rol_usuario: str = None,
) -> dict:
    """Procesa una transacción de venta registrando cabecera, detalles y descontando stock.

    `monto_cobrado` es lo que realmente se cobra tras el descuento, en la
    moneda del método de pago; `None` significa "se cobró el precio de lista".
    `porcentaje_descuento` se ignora como entrada (se recalcula siempre desde
    los montos) y se acepta solo para que la vista pueda pasarlo sin romper.
    `fecha_limite_pago` solo se usa con Crédito, donde es obligatoria.
    `rol_usuario` no autoriza nada: únicamente decide si el mensaje de rechazo
    por piso de costo puede nombrar el costo (ver abajo).
    """
    if not lineas or len(lineas) == 0:
        raise ValueError("La venta debe contener al menos un producto.")

    tipo_venta_clean = tipo_venta.strip().capitalize() if tipo_venta else ""
    if tipo_venta_clean not in ["Formal", "Informal"]:
        raise ValueError("El tipo de venta debe ser 'Formal' o 'Informal'.")

    metodo_pago_clean = (metodo_pago or "Efectivo").strip()
    if metodo_pago_clean not in METODOS_PAGO:
        raise ValueError(f"El método de pago debe ser uno de: {', '.join(METODOS_PAGO)}.")
    moneda_cobro = "BCV" if metodo_pago_clean in METODOS_PAGO_BS else "USD"
    es_credito = metodo_pago_clean in METODOS_PAGO_CREDITO

    # ── Crédito: validaciones que no dependen de la base ─────────────────────
    if es_credito and tipo_venta_clean != TIPO_VENTA_FORMAL:
        raise ValueError(
            "ERR_VENTA_CREDITO_TIPO: El método de pago Crédito solo está "
            "disponible en Venta Formal, no en Venta Mostrador."
        )
    # La fecha límite se normaliza ANTES de tocar la base: si está mal escrita,
    # mejor que falle sin haber registrado nada que dejar una venta a crédito
    # huérfana que después haya que compensar.
    fecha_limite = deudas_service.normalizar_fecha(fecha_limite_pago) if es_credito else None

    # ── Referencia del pago ──────────────────────────────────────────────────
    referencia_limpia = (referencia_pago or "").strip() or None
    omitida = bool(referencia_omitida)
    if metodo_pago_clean == METODO_SIN_REFERENCIA:
        # Efectivo no pide referencia, así que no hay nada que "omitir": dejar
        # la bandera encendida mentiría en el historial.
        omitida = False
    elif referencia_limpia is not None:
        # Si el vendedor escribió la referencia, no la omitió.
        omitida = False
    elif not omitida:
        raise ValueError(
            "ERR_VENTA_REFERENCIA: El método de pago "
            f"'{metodo_pago_clean}' exige el número de referencia del pago "
            "(o confirmar explícitamente su omisión)."
        )

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

        # Redundante con la regla de Venta Formal, pero explícito: la deuda se
        # registra contra una Cédula/RIF, sin cliente no hay a quién cobrarle.
        if es_credito and not cliente_id:
            raise ValueError(
                "ERR_VENTA_CREDITO_CLIENTE: Una venta a crédito debe estar "
                "asociada a un cliente de la cartera."
            )

        conn.execute("BEGIN TRANSACTION")

        # Procesar líneas y pre-calcular subtotales
        total_usd = 0.0
        total_bcv = 0.0
        items_procesados = []
        # Costos leídos con ESTE cursor (dentro de la transacción) para no
        # abrir una segunda conexión al mismo archivo SQLite solo para el piso.
        costos_por_codigo: dict = {}

        for item in lineas:
            codigo = item.get("producto_codigo") or item.get("codigo")
            if not codigo:
                raise ValueError("Cada línea debe especificar el código del producto.")

            cantidad = float(item.get("cantidad", 0))
            if cantidad <= 0:
                raise ValueError(f"La cantidad para el producto {codigo} debe ser mayor a cero.")

            # Verificar existencia del producto y stock suficiente
            cursor.execute(
                "SELECT existencia, precio_dolares, precio_bcv, costo_usd_efectivo "
                "FROM productos WHERE codigo = ?",
                (codigo,)
            )
            prod = cursor.fetchone()
            if not prod:
                raise ValueError(f"El producto con código {codigo} no existe.")

            existencia_actual = prod["existencia"]
            if existencia_actual < cantidad:
                raise ValueError(f"Stock insuficiente para el producto {codigo}")

            costos_por_codigo[codigo] = prod["costo_usd_efectivo"]

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
                "subtotal_bcv": subtotal_bcv,
                # Solo viaja a los renglones de la deuda ("el repuesto fiado").
                "descripcion_corta": (
                    item.get("descripcion_corta") or item.get("nombre_corto") or ""
                ),
            })

        # ── Monto cobrado y descuento ────────────────────────────────────────
        monto_predeterminado = round(total_bcv if moneda_cobro == "BCV" else total_usd, 2)
        monto_final, porcentaje = _resolver_monto_cobrado(
            monto_cobrado=monto_cobrado,
            monto_predeterminado=monto_predeterminado,
            total_usd=total_usd,
            items_procesados=items_procesados,
            costos_por_codigo=costos_por_codigo,
            moneda_cobro=moneda_cobro,
            es_credito=es_credito,
            rol_usuario=rol_usuario,
        )

        # Insertar cabecera de la venta
        cursor.execute(
            """
            INSERT INTO ventas (
                tipo_venta, cliente_id, total_usd, total_bcv, metodo_pago,
                referencia_pago, referencia_omitida, monto_cobrado,
                porcentaje_descuento, usuario_nombre
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tipo_venta_clean, cliente_id, total_usd, total_bcv, metodo_pago_clean,
                referencia_limpia, 1 if omitida else 0, monto_final,
                porcentaje, usuario_nombre,
            )
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
        resultado = {
            "venta_id": venta_id,
            "tipo_venta": tipo_venta_clean,
            "cliente_id": cliente_id,
            "total_usd": total_usd,
            "total_bcv": total_bcv,
            "metodo_pago": metodo_pago_clean,
            "moneda_cobro": moneda_cobro,
            "monto_predeterminado": monto_predeterminado,
            "monto_cobrado": monto_final,
            "monto_a_pagar": monto_final,
            "porcentaje_descuento": porcentaje,
            "referencia_pago": referencia_limpia,
            "referencia_omitida": omitida,
            "usuario_nombre": usuario_nombre,
            "deuda_id": None,
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

    # ── Crédito: la deuda por cobrar ─────────────────────────────────────────
    # Fuera de la transacción de la venta por obligación (ver `_revertir_venta`
    # para el porqué y para la compensación si esto falla).
    if es_credito:
        try:
            deuda = deudas_service.crear_deuda(
                cliente_id=cliente_id,
                monto_total_usd=resultado["monto_cobrado"],
                fecha_limite_pago=fecha_limite,
                items=[
                    {
                        "producto_codigo": item["codigo"],
                        "descripcion_corta": item["descripcion_corta"],
                        "cantidad": item["cantidad"],
                        "subtotal_usd": item["subtotal_usd"],
                    }
                    for item in items_procesados
                ],
                venta_id=resultado["venta_id"],
                usuario_nombre=usuario_nombre,
            )
        except Exception:
            _revertir_venta(resultado["venta_id"], items_procesados)
            raise
        resultado["deuda_id"] = deuda["id"]

    return resultado


def _resolver_monto_cobrado(
    monto_cobrado,
    monto_predeterminado: float,
    total_usd: float,
    items_procesados: list,
    costos_por_codigo: dict,
    moneda_cobro: str,
    es_credito: bool,
    rol_usuario: str | None,
) -> tuple[float, float]:
    """Valida el monto que se va a cobrar y devuelve `(monto, porcentaje)`.

    Sin monto manual no hay descuento: se cobra el precio de lista y el
    porcentaje es 0. Con monto manual se aplican tres reglas:

    1. Piso de costo — el monto debe quedar ESTRICTAMENTE por encima de la
       suma de costos del carrito; por debajo o igual se vendería a pérdida.
    2. Límite del crédito — a crédito el monto no puede bajar del 95% de la
       lista ("-5% OFF, solo se puede aplicar hacia arriba").
    3. Montos no positivos — una venta de 0 no es una venta.
    """
    if monto_cobrado is None or monto_cobrado == "":
        return monto_predeterminado, 0.0

    monto_final = _a_numero(monto_cobrado, "monto a cobrar")
    if monto_final <= 0:
        raise ValueError("ERR_VENTA_MONTO: El monto a cobrar debe ser mayor que cero.")

    resumen_costos = calcular_suma_costos(items_procesados, costos_por_codigo)

    # El piso se calcula en dólares (los costos son dólares efectivo) y se
    # lleva a la MONEDA DEL COBRO con la misma proporción que relaciona el
    # total de lista en esa moneda con el total en dólares efectivo. Así un
    # cobro en Bolívares se compara contra su propio piso en Bolívares, sin
    # mezclar monedas ni depender de la tasa BCV del momento.
    factor_moneda = (monto_predeterminado / total_usd) if total_usd else 1.0
    piso = round(resumen_costos["suma"] * factor_moneda, 2)

    if monto_final - piso <= _TOLERANCIA:
        # Los costos son información reservada a la administración (ver
        # `services/permisos_service.puede_ver_costos`). El piso se valida
        # igual para todos, pero solo a quien puede ver costos se le dice
        # cuál es el número: al vendedor se le niega el cobro sin revelarlo.
        if puede_ver_costos(rol_usuario):
            simbolo = "Bs." if moneda_cobro == "BCV" else "$"
            detalle = (
                " (el piso es parcial: hay productos sin costo registrado)"
                if resumen_costos["parcial"] else ""
            )
            raise ValueError(
                f"ERR_VENTA_DESCUENTO_PISO: El monto a cobrar debe quedar por "
                f"encima del costo del carrito ({simbolo} {piso:,.2f}){detalle}."
            )
        raise ValueError(
            "ERR_VENTA_DESCUENTO_PISO: El monto es demasiado bajo; consulte "
            "con un administrador."
        )

    if es_credito:
        minimo_credito = round(monto_predeterminado * FACTOR_MINIMO_CREDITO, 2)
        if minimo_credito - monto_final > _TOLERANCIA:
            raise ValueError(
                "ERR_VENTA_CREDITO_DESCUENTO: A crédito el descuento no puede "
                f"pasar del -5% (mínimo ${minimo_credito:,.2f}); por encima del "
                "precio de lista sí se puede cobrar."
            )

    return monto_final, calcular_porcentaje_descuento(monto_final, monto_predeterminado)
