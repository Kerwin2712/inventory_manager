"""Deudas por Cobrar: ventas cerradas con el método de pago "Crédito".

Una venta a crédito registra la mercancía entregada y el compromiso de pago,
no el cobro. Este servicio es la única puerta de entrada a las tablas
`deudas`, `deuda_items` y `deuda_abonos`.

Reglas del dominio:

- El **saldo es derivado**, nunca autoritativo: se recalcula siempre como
  `monto_total_usd - Σ abonos`, porque `deuda_abonos` es la fuente de verdad
  del historial de cobros. La columna `deudas.saldo_usd` existe solo como
  caché para poder ordenar y filtrar en SQL; `_refrescar_saldo` la sincroniza
  después de cada abono.
- El estado se deriva del saldo: `abierta` mientras quede saldo, `pagada` al
  llegar a cero. Nunca se escribe a mano desde la interfaz.
- Los montos se comparan con una tolerancia de un centavo (`_TOLERANCIA`): un
  saldo de 0,004 USD producto del redondeo es una deuda pagada, no una deuda
  abierta por cuatro milésimas que el cobrador nunca podría cerrar.
"""
import datetime
import sqlite3

from core.database import get_connection

# Un centavo: por debajo de esto, dos montos son el mismo monto.
_TOLERANCIA = 0.005

ESTADO_ABIERTA = "abierta"
ESTADO_PAGADA = "pagada"


def _hoy() -> str:
    return datetime.date.today().strftime("%Y-%m-%d")


def _ahora() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def normalizar_fecha(valor) -> str:
    """Normaliza una fecha a `YYYY-MM-DD`, que es el formato que ordena
    correctamente como texto en SQLite.

    Acepta `date`/`datetime`, el ISO `YYYY-MM-DD` y el formato que escribe el
    usuario en la ventana de crédito (`DD/MM/AAAA`, con `/` o `-`).
    """
    if isinstance(valor, datetime.datetime):
        return valor.date().strftime("%Y-%m-%d")
    if isinstance(valor, datetime.date):
        return valor.strftime("%Y-%m-%d")

    crudo = str(valor or "").strip()
    if not crudo:
        raise ValueError("ERR_DEUDA_FECHA: La fecha límite de pago es obligatoria.")

    for formato in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.datetime.strptime(crudo, formato).date().strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError(
        "ERR_DEUDA_FECHA: La fecha límite de pago debe tener el formato "
        "Día/Mes/Año (por ejemplo 31/12/2026)."
    )


def _monto(valor, etiqueta: str) -> float:
    """Normaliza un monto: acepta coma o punto decimal y rechaza negativos."""
    if isinstance(valor, bool) or valor is None or valor == "":
        raise ValueError(f"ERR_DEUDA_MONTO: El {etiqueta} es obligatorio.")
    if isinstance(valor, str):
        valor = valor.strip().replace(",", ".")
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        raise ValueError(f"ERR_DEUDA_MONTO: El {etiqueta} debe ser un número válido.")
    if numero < 0:
        raise ValueError(f"ERR_DEUDA_MONTO: El {etiqueta} no puede ser negativo.")
    return round(numero, 2)


def _fila_a_dict(fila: sqlite3.Row) -> dict:
    return {clave: fila[clave] for clave in fila.keys()}


# ─── Creación ────────────────────────────────────────────────────────────────

def crear_deuda(
    cliente_id: str,
    monto_total_usd,
    fecha_limite_pago,
    items: list[dict] | None = None,
    venta_id: int | None = None,
    monto_total_bcv=0,
    usuario_nombre: str | None = None,
    fecha_creacion: str | None = None,
) -> dict:
    """Registra una deuda por una venta a crédito y devuelve la deuda creada.

    `items` son los renglones acreditados — el "repuesto fiado" que la lista
    de Deudas por Cobrar muestra junto a los datos del cliente. Cada uno
    acepta `producto_codigo`, `descripcion_corta`, `cantidad` y
    `subtotal_usd`; las claves que falten quedan vacías, de modo que una
    venta de mostrador sin código de producto también se puede acreditar.

    La deuda nace con el saldo completo: una venta a crédito no cobra nada en
    el momento, solo compromete el pago.
    """
    cliente = (cliente_id or "").strip()
    if not cliente:
        raise ValueError(
            "ERR_DEUDA_CLIENTE: Una venta a crédito debe estar asociada a un "
            "cliente de la cartera."
        )

    total_usd = _monto(monto_total_usd, "monto total de la deuda")
    if total_usd <= 0:
        raise ValueError("ERR_DEUDA_MONTO: El monto total de la deuda debe ser mayor que cero.")
    total_bcv = _monto(monto_total_bcv or 0, "monto total en bolívares")
    limite = normalizar_fecha(fecha_limite_pago)
    creacion = normalizar_fecha(fecha_creacion) if fecha_creacion else _hoy()

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.execute("SELECT 1 FROM clientes WHERE cedula_rif = ?", (cliente,))
        if not cursor.fetchone():
            raise ValueError(
                f"ERR_DEUDA_CLIENTE: No existe un cliente registrado con la "
                f"Cédula/RIF '{cliente}'."
            )

        cursor.execute(
            """
            INSERT INTO deudas (
                venta_id, cliente_id, monto_total_usd, monto_total_bcv,
                saldo_usd, fecha_creacion, fecha_limite_pago, usuario_nombre, estado
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                venta_id, cliente, total_usd, total_bcv,
                total_usd, creacion, limite, usuario_nombre, ESTADO_ABIERTA,
            ),
        )
        deuda_id = cursor.lastrowid

        for item in (items or []):
            cursor.execute(
                """
                INSERT INTO deuda_items
                    (deuda_id, producto_codigo, descripcion_corta, cantidad, subtotal_usd)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    deuda_id,
                    (item.get("producto_codigo") or item.get("codigo") or None),
                    (item.get("descripcion_corta") or item.get("nombre_referencia_corto") or ""),
                    float(item.get("cantidad") or 0),
                    float(item.get("subtotal_usd") or 0),
                ),
            )
        conn.commit()

    return obtener_deuda(deuda_id)


# ─── Lectura ─────────────────────────────────────────────────────────────────

def obtener_deuda(deuda_id: int) -> dict | None:
    """Una deuda con los datos del cliente, sus renglones y sus abonos."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT d.*,
                   c.nombre AS cliente_nombre,
                   c.telefono AS cliente_telefono,
                   c.direccion AS cliente_direccion,
                   c.correo AS cliente_correo,
                   c.contacto_secundario AS cliente_contacto_secundario
              FROM deudas d
              LEFT JOIN clientes c ON c.cedula_rif = d.cliente_id
             WHERE d.id = ?
            """,
            (deuda_id,),
        )
        fila = cursor.fetchone()
        if not fila:
            return None
        deuda = _fila_a_dict(fila)

        cursor.execute(
            "SELECT * FROM deuda_items WHERE deuda_id = ? ORDER BY id", (deuda_id,)
        )
        deuda["items"] = [_fila_a_dict(f) for f in cursor.fetchall()]

        cursor.execute(
            "SELECT * FROM deuda_abonos WHERE deuda_id = ? ORDER BY id", (deuda_id,)
        )
        deuda["abonos"] = [_fila_a_dict(f) for f in cursor.fetchall()]

    return _decorar(deuda)


def _decorar(deuda: dict) -> dict:
    """Agrega los campos que la lista de Deudas por Cobrar necesita mostrar y
    que no viven en ninguna columna: el ítem acreditado como texto y la marca
    de vencimiento."""
    descripciones = [
        (item.get("descripcion_corta") or item.get("producto_codigo") or "").strip()
        for item in deuda.get("items", [])
    ]
    deuda["items_descripcion"] = ", ".join([d for d in descripciones if d])
    deuda["cantidad_items"] = len(deuda.get("items", []))
    deuda["vencida"] = esta_vencida(deuda)
    deuda["total_abonado_usd"] = round(
        sum(float(a.get("monto_usd") or 0) for a in deuda.get("abonos", [])), 2
    )
    return deuda


def esta_vencida(deuda: dict, hoy: str | None = None) -> bool:
    """True si la deuda sigue abierta y ya pasó su fecha límite de pago. Es lo
    que enciende el signo de exclamación (!) en la lista."""
    if (deuda.get("estado") or ESTADO_ABIERTA) != ESTADO_ABIERTA:
        return False
    limite = (deuda.get("fecha_limite_pago") or "").strip()
    if not limite:
        return False
    return limite < (hoy or _hoy())


def listar_deudas(
    solo_abiertas: bool = False,
    busqueda: str = "",
    cliente_id: str | None = None,
) -> list[dict]:
    """Deudas ordenadas por fecha límite ascendente — las más urgentes
    primero, que es el orden en que hay que salir a cobrar.

    `busqueda` filtra por Cédula/RIF, nombre del cliente o descripción del
    ítem acreditado.
    """
    condiciones = []
    parametros: list = []

    if solo_abiertas:
        condiciones.append("d.estado = ?")
        parametros.append(ESTADO_ABIERTA)
    if cliente_id:
        condiciones.append("d.cliente_id = ?")
        parametros.append(cliente_id.strip())

    termino = (busqueda or "").strip()
    if termino:
        patron = f"%{termino}%"
        condiciones.append(
            "(d.cliente_id LIKE ? COLLATE NOCASE"
            " OR c.nombre LIKE ? COLLATE NOCASE"
            " OR EXISTS (SELECT 1 FROM deuda_items i"
            "            WHERE i.deuda_id = d.id"
            "              AND (i.descripcion_corta LIKE ? COLLATE NOCASE"
            "                   OR i.producto_codigo LIKE ? COLLATE NOCASE)))"
        )
        parametros.extend([patron, patron, patron, patron])

    where = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT d.*,
                   c.nombre AS cliente_nombre,
                   c.telefono AS cliente_telefono,
                   c.direccion AS cliente_direccion,
                   c.correo AS cliente_correo,
                   c.contacto_secundario AS cliente_contacto_secundario
              FROM deudas d
              LEFT JOIN clientes c ON c.cedula_rif = d.cliente_id
              {where}
             ORDER BY d.fecha_limite_pago ASC, d.id ASC
            """,
            parametros,
        )
        deudas = [_fila_a_dict(f) for f in cursor.fetchall()]

        for deuda in deudas:
            cursor.execute(
                "SELECT * FROM deuda_items WHERE deuda_id = ? ORDER BY id", (deuda["id"],)
            )
            deuda["items"] = [_fila_a_dict(f) for f in cursor.fetchall()]
            cursor.execute(
                "SELECT * FROM deuda_abonos WHERE deuda_id = ? ORDER BY id", (deuda["id"],)
            )
            deuda["abonos"] = [_fila_a_dict(f) for f in cursor.fetchall()]

    return [_decorar(d) for d in deudas]


def total_por_cobrar() -> float:
    """Suma de los saldos de todas las deudas abiertas."""
    with get_connection() as conn:
        fila = conn.execute(
            "SELECT COALESCE(SUM(saldo_usd), 0) FROM deudas WHERE estado = ?",
            (ESTADO_ABIERTA,),
        ).fetchone()
    return round(float(fila[0] or 0), 2)


# ─── Abonos ──────────────────────────────────────────────────────────────────

def _refrescar_saldo(cursor, deuda_id: int) -> float:
    """Recalcula el saldo desde los abonos y sincroniza la caché y el estado.

    El saldo nunca se decrementa "en sitio": se vuelve a derivar de la suma de
    abonos, de modo que eliminar o corregir un abono no deja la caché
    desalineada con el historial.
    """
    fila = cursor.execute(
        "SELECT monto_total_usd FROM deudas WHERE id = ?", (deuda_id,)
    ).fetchone()
    if not fila:
        raise ValueError(f"ERR_DEUDA_NO_EXISTE: No existe la deuda {deuda_id}.")
    total = float(fila[0] or 0)

    abonado = cursor.execute(
        "SELECT COALESCE(SUM(monto_usd), 0) FROM deuda_abonos WHERE deuda_id = ?",
        (deuda_id,),
    ).fetchone()[0]

    saldo = round(total - float(abonado or 0), 2)
    if saldo < _TOLERANCIA:
        saldo = 0.0
    estado = ESTADO_PAGADA if saldo <= 0 else ESTADO_ABIERTA

    cursor.execute(
        "UPDATE deudas SET saldo_usd = ?, estado = ?, updated_at = ? WHERE id = ?",
        (saldo, estado, _ahora(), deuda_id),
    )
    return saldo


def registrar_abono(
    deuda_id: int,
    monto_usd,
    metodo_pago: str = "Efectivo",
    referencia_pago: str | None = None,
    monto_bcv=0,
    usuario_nombre: str | None = None,
    fecha: str | None = None,
) -> dict:
    """Registra un abono parcial (o el pago final) contra una deuda.

    Rechaza abonos por encima del saldo vivo: un cobro de más no es un abono,
    es un error de tipeo, y aceptarlo dejaría la deuda en saldo negativo.
    """
    monto = _monto(monto_usd, "monto del abono")
    if monto <= 0:
        raise ValueError("ERR_DEUDA_ABONO: El monto del abono debe ser mayor que cero.")

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        fila = cursor.execute(
            "SELECT saldo_usd, estado FROM deudas WHERE id = ?", (deuda_id,)
        ).fetchone()
        if not fila:
            raise ValueError(f"ERR_DEUDA_NO_EXISTE: No existe la deuda {deuda_id}.")
        if (fila["estado"] or ESTADO_ABIERTA) == ESTADO_PAGADA:
            raise ValueError("ERR_DEUDA_PAGADA: Esta deuda ya está pagada por completo.")

        saldo = float(fila["saldo_usd"] or 0)
        if monto - saldo > _TOLERANCIA:
            raise ValueError(
                f"ERR_DEUDA_ABONO: El abono (${monto:.2f}) supera el saldo "
                f"pendiente de la deuda (${saldo:.2f})."
            )

        cursor.execute(
            """
            INSERT INTO deuda_abonos
                (deuda_id, monto_usd, monto_bcv, metodo_pago, referencia_pago, fecha, usuario_nombre)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                deuda_id, monto, _monto(monto_bcv or 0, "monto del abono en bolívares"),
                (metodo_pago or "Efectivo").strip(),
                (referencia_pago or "").strip() or None,
                normalizar_fecha(fecha) if fecha else _hoy(),
                usuario_nombre,
            ),
        )
        _refrescar_saldo(cursor, deuda_id)
        conn.commit()

    return obtener_deuda(deuda_id)


# ─── Edición y borrado ───────────────────────────────────────────────────────

def actualizar_deuda(
    deuda_id: int,
    fecha_limite_pago=None,
    monto_total_usd=None,
    usuario_nombre: str | None = None,
) -> dict:
    """Corrige los datos editables de una deuda (botón Editar de la lista).

    El saldo y el estado NO son editables: se vuelven a derivar de los abonos
    después de cambiar el monto total. Un monto total por debajo de lo ya
    abonado se rechaza, porque dejaría la deuda con saldo negativo.
    """
    campos: list[str] = []
    parametros: list = []

    if fecha_limite_pago is not None:
        campos.append("fecha_limite_pago = ?")
        parametros.append(normalizar_fecha(fecha_limite_pago))
    if usuario_nombre is not None:
        campos.append("usuario_nombre = ?")
        parametros.append(usuario_nombre)

    nuevo_total = None
    if monto_total_usd is not None:
        nuevo_total = _monto(monto_total_usd, "monto total de la deuda")
        if nuevo_total <= 0:
            raise ValueError("ERR_DEUDA_MONTO: El monto total de la deuda debe ser mayor que cero.")
        campos.append("monto_total_usd = ?")
        parametros.append(nuevo_total)

    if not campos:
        deuda = obtener_deuda(deuda_id)
        if deuda is None:
            raise ValueError(f"ERR_DEUDA_NO_EXISTE: No existe la deuda {deuda_id}.")
        return deuda

    with get_connection() as conn:
        cursor = conn.cursor()
        if not cursor.execute("SELECT 1 FROM deudas WHERE id = ?", (deuda_id,)).fetchone():
            raise ValueError(f"ERR_DEUDA_NO_EXISTE: No existe la deuda {deuda_id}.")

        if nuevo_total is not None:
            abonado = cursor.execute(
                "SELECT COALESCE(SUM(monto_usd), 0) FROM deuda_abonos WHERE deuda_id = ?",
                (deuda_id,),
            ).fetchone()[0]
            if float(abonado or 0) - nuevo_total > _TOLERANCIA:
                raise ValueError(
                    f"ERR_DEUDA_MONTO: El nuevo monto total (${nuevo_total:.2f}) es "
                    f"menor que lo ya abonado (${float(abonado or 0):.2f})."
                )

        campos.append("updated_at = ?")
        parametros.append(_ahora())
        parametros.append(deuda_id)
        cursor.execute(f"UPDATE deudas SET {', '.join(campos)} WHERE id = ?", parametros)
        _refrescar_saldo(cursor, deuda_id)
        conn.commit()

    return obtener_deuda(deuda_id)


def eliminar_deuda(deuda_id: int) -> bool:
    """Borra una deuda con sus renglones y abonos (ON DELETE CASCADE)."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.execute("DELETE FROM deudas WHERE id = ?", (deuda_id,))
        borradas = cursor.rowcount
        conn.commit()
    return borradas > 0
