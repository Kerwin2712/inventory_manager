import sqlite3
from datetime import datetime
from core.database import get_connection
from services.bcv_service import obtener_estado_tasa


def _row_to_dict(row) -> dict:
    """Convierte una sqlite3.Row en diccionario estándar."""
    return dict(row) if row else {}


def calcular_monto_bolivares(precio_bcv_usd: float) -> float:
    """Monto en Bolívares que paga el cliente por la vía BCV: SIEMPRE
    calculado en tiempo de ejecución como Precio BCV ($) × tasa BCV vigente.

    El sistema venezolano maneja DOS precios en dólares por producto,
    distintos entre sí:
    - `precio_dolares` (Precio USD Efectivo): lo que se paga si el cliente
      entrega dólares físicos en efectivo.
    - `precio_bcv` (Precio USD BCV): el monto en dólares de referencia que se
      cobra en Bolívares, convertido a la tasa BCV vigente. Es un valor
      independiente y manual — NO se deriva del Precio Efectivo.

    Solo el monto en Bolívares que resulta de ese Precio USD BCV es lo que se
    calcula dinámicamente; el propio Precio USD BCV es un input del usuario.
    """
    estado = obtener_estado_tasa()
    tasa = estado.get("tasa", 0.0)
    if tasa <= 0 or precio_bcv_usd <= 0:
        return 0.0
    return round(precio_bcv_usd * tasa, 2)


def crear_producto(
    codigo: str,
    referencia: str,
    descripcion_general: str,
    departamento: str,
    marca: str = "",
    precio_dolares: float = 0.0,
    precio_bcv: float = 0.0,
    proveedor_id=None,
    existencia: float = 0.0,
    codigo_barras: str = "",
    nombre_referencia_corto: str = "",
) -> dict:
    """Crea un nuevo producto en inventario. Aplica reglas ERS 3.1.

    `precio_dolares` = Precio USD Efectivo (pago en dólares físicos).
    `precio_bcv` = Precio USD BCV (referencia en dólares para pago en
    Bolívares a la tasa vigente) — ambos son valores manuales independientes.
    """
    # ── Validaciones de campos obligatorios ──────────────────────────────────
    codigo = (codigo or "").strip()
    referencia = (referencia or "").strip()
    descripcion_general = (descripcion_general or "").strip()
    departamento = (departamento or "").strip()

    if not codigo:
        raise ValueError("ERR_PROD_REQ: El código de producto es obligatorio.")
    if not referencia:
        raise ValueError("ERR_PROD_REQ: La referencia del producto es obligatoria.")
    if not descripcion_general:
        raise ValueError("ERR_PROD_REQ: La descripción general es obligatoria.")
    if not departamento:
        raise ValueError("ERR_PROD_REQ: El departamento es obligatorio.")

    # ── Validación de lógica de existencia y precio (ERS 3.1) ────────────────
    # "al menos una de las casillas de Precios Dólares o BCV": ambos precios
    # son independientes y cualquiera de los dos satisface la exigencia.
    if existencia > 0 and precio_dolares <= 0 and precio_bcv <= 0:
        raise ValueError(
            "ERR_PROD_PRICE: Si el producto tiene existencia, al menos el "
            "Precio USD Efectivo o el Precio USD BCV debe ser mayor a cero."
        )

    # ── Nombre corto auto-generado si no se provee ───────────────────────────
    nombre_referencia_corto = (nombre_referencia_corto or "").strip()
    if not nombre_referencia_corto:
        nombre_referencia_corto = descripcion_general[:30].strip()
    elif len(nombre_referencia_corto) > 30:
        nombre_referencia_corto = nombre_referencia_corto[:30].strip()

    marca = (marca or "").strip()
    codigo_barras = (codigo_barras or "").strip() or None
    fecha_mod = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        with get_connection() as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO productos (
                    codigo, referencia, departamento, descripcion_general,
                    marca, precio_dolares, precio_bcv, proveedor_id,
                    existencia, codigo_barras, nombre_referencia_corto,
                    fecha_ultima_modificacion
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    codigo, referencia, departamento, descripcion_general,
                    marca, precio_dolares, precio_bcv, proveedor_id,
                    existencia, codigo_barras, nombre_referencia_corto, fecha_mod,
                ),
            )
            conn.commit()
    except sqlite3.IntegrityError as ex:
        msg = str(ex).lower()
        if "unique" in msg or "primary key" in msg:
            raise ValueError(f"ERR_PROD_DUPLICADO: Ya existe un producto con el código '{codigo}'.")
        raise ValueError(f"ERR_PROD_DB: Error de integridad al guardar el producto: {ex}")

    return obtener_producto(codigo) or {}


def obtener_producto(codigo: str) -> dict | None:
    """Obtiene un producto por su código primario. Agrega `monto_bcv_bolivares`
    (Precio USD BCV convertido a Bolívares con la tasa vigente, en vivo)."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM productos WHERE codigo = ?", (codigo.strip(),))
        row = cursor.fetchone()
        if not row:
            return None
        prod = _row_to_dict(row)
        prod["monto_bcv_bolivares"] = calcular_monto_bolivares(prod.get("precio_bcv", 0.0))
        return prod


def actualizar_producto(
    codigo: str,
    referencia: str,
    descripcion_general: str,
    departamento: str,
    marca: str = "",
    precio_dolares: float = 0.0,
    precio_bcv: float = 0.0,
    proveedor_id=None,
    existencia: float = 0.0,
    codigo_barras: str = "",
    nombre_referencia_corto: str = "",
) -> dict:
    """Actualiza un producto existente. Aplica las mismas reglas ERS 3.1."""
    codigo = (codigo or "").strip()
    referencia = (referencia or "").strip()
    descripcion_general = (descripcion_general or "").strip()
    departamento = (departamento or "").strip()

    if not codigo:
        raise ValueError("ERR_PROD_REQ: El código de producto es obligatorio.")
    if not referencia:
        raise ValueError("ERR_PROD_REQ: La referencia del producto es obligatoria.")
    if not descripcion_general:
        raise ValueError("ERR_PROD_REQ: La descripción general es obligatoria.")
    if not departamento:
        raise ValueError("ERR_PROD_REQ: El departamento es obligatorio.")

    # Precio USD Efectivo y Precio USD BCV son independientes (ERS 3.1).
    if existencia > 0 and precio_dolares <= 0 and precio_bcv <= 0:
        raise ValueError(
            "ERR_PROD_PRICE: Si el producto tiene existencia, al menos el "
            "Precio USD Efectivo o el Precio USD BCV debe ser mayor a cero."
        )

    nombre_referencia_corto = (nombre_referencia_corto or "").strip()
    if not nombre_referencia_corto:
        nombre_referencia_corto = descripcion_general[:30].strip()
    elif len(nombre_referencia_corto) > 30:
        nombre_referencia_corto = nombre_referencia_corto[:30].strip()

    marca = (marca or "").strip()
    codigo_barras = (codigo_barras or "").strip() or None
    fecha_mod = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with get_connection() as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE productos SET
                referencia = ?, departamento = ?, descripcion_general = ?,
                marca = ?, precio_dolares = ?, precio_bcv = ?,
                proveedor_id = ?, existencia = ?, codigo_barras = ?,
                nombre_referencia_corto = ?, fecha_ultima_modificacion = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE codigo = ?
            """,
            (
                referencia, departamento, descripcion_general,
                marca, precio_dolares, precio_bcv,
                proveedor_id, existencia, codigo_barras,
                nombre_referencia_corto, fecha_mod, codigo,
            ),
        )
        conn.commit()

    resultado = obtener_producto(codigo)
    if not resultado:
        raise ValueError(f"ERR_PROD_NOT_FOUND: No se encontró el producto con código '{codigo}'.")
    return resultado


# Columnas de texto directo del inventario (ERS 3.2) filtrables por LIKE independiente.
_FILTROS_TEXTO = (
    "codigo", "referencia", "departamento", "descripcion_general", "marca",
    "fecha_ultima_modificacion", "codigo_barras", "nombre_referencia_corto",
)
# Columnas numéricas, filtrables como texto parcial sobre su representación.
_FILTROS_NUMERICOS = ("precio_dolares", "precio_bcv", "existencia")


def listar_productos(
    departamento: str = "",
    busqueda: str = "",
    proveedor_id: int | None = None,
    filtros: dict | None = None,
    page: int = 1,
    per_page: int = 20,
) -> list[dict]:
    """Lista productos con filtros opcionales.

    - `busqueda`: texto libre combinado con OR sobre varias columnas (búsqueda
      rápida tipo escáner, usada por el módulo de Ventas).
    - `filtros`: diccionario con una clave por cada una de las 12 columnas del
      inventario (ERS 3.2 — Filtros en Cascada). Cada filtro no vacío se
      combina con los demás mediante AND independientes (coincidencia parcial
      LIKE '%texto%'), nunca concatenados en un solo término de búsqueda.
      Claves soportadas: codigo, referencia, departamento, descripcion_general,
      marca, precio_dolares, precio_bcv, proveedor, fecha_ultima_modificacion,
      existencia, codigo_barras, nombre_referencia_corto.
    """
    query = "SELECT * FROM productos WHERE 1=1"
    params: list = []

    if departamento:
        query += " AND departamento = ?"
        params.append(departamento.strip())

    if busqueda:
        # Búsqueda por palabras independientes (AND de ORs)
        palabras = busqueda.strip().split()
        for pal in palabras:
            termino = f"%{pal}%"
            query += (
                " AND (codigo LIKE ? OR referencia LIKE ? OR descripcion_general LIKE ?"
                " OR marca LIKE ? OR codigo_barras LIKE ? OR nombre_referencia_corto LIKE ?)"
            )
            params.extend([termino] * 6)

    if proveedor_id is not None:
        query += " AND proveedor_id = ?"
        params.append(proveedor_id)

    # ── Filtros en cascada por columna (ERS 3.2): AND independientes ────────
    filtros = filtros or {}

    for columna in _FILTROS_TEXTO:
        valor = (filtros.get(columna) or "").strip()
        if valor:
            query += f" AND {columna} LIKE ?"
            params.append(f"%{valor}%")

    for columna in _FILTROS_NUMERICOS:
        valor = (filtros.get(columna) or "").strip()
        if valor:
            query += f" AND CAST({columna} AS TEXT) LIKE ?"
            params.append(f"%{valor}%")

    proveedor_texto = (filtros.get("proveedor") or "").strip()
    if proveedor_texto:
        query += (
            " AND proveedor_id IN "
            "(SELECT id FROM proveedores WHERE empresa LIKE ? OR contacto LIKE ?)"
        )
        params.extend([f"%{proveedor_texto}%", f"%{proveedor_texto}%"])

    query += " ORDER BY departamento, codigo"
    offset = (max(1, page) - 1) * per_page
    query += f" LIMIT {per_page} OFFSET {offset}"

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        productos = [_row_to_dict(r) for r in cursor.fetchall()]

    # Monto en Bolívares (Precio USD BCV x tasa vigente) recalculado en vivo;
    # `precio_bcv` en sí queda intacto — es el input manual almacenado.
    tasa = obtener_estado_tasa().get("tasa", 0.0)
    for p in productos:
        p["monto_bcv_bolivares"] = round(p.get("precio_bcv", 0.0) * tasa, 2) if tasa > 0 else 0.0
    return productos


def eliminar_producto(codigo: str) -> None:
    """Elimina un producto por su código. Lanza ValueError si no existe."""
    codigo = (codigo or "").strip()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT codigo FROM productos WHERE codigo = ?", (codigo,))
        if not cursor.fetchone():
            raise ValueError(f"ERR_PROD_NOT_FOUND: No existe un producto con el código '{codigo}'.")
        cursor.execute("DELETE FROM productos WHERE codigo = ?", (codigo,))
        conn.commit()
