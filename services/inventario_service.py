import sqlite3
from datetime import datetime
from core.database import get_connection
from core.models import (
    normalizar_alerta_stock_minimo,
    normalizar_costo,
    validar_costo_obligatorio,
)
from services.bcv_service import obtener_estado_tasa
from services.departamentos_service import registrar_desde_producto
from services.permisos_service import filtrar_campos_costo, puede_editar_costos


def _row_to_dict(row) -> dict:
    """Convierte una sqlite3.Row en diccionario estándar."""
    return dict(row) if row else {}


def _validar_permiso_costos(costo_usd_efectivo, costo_usd_bcv, rol_usuario) -> None:
    """Fail-closed: solo un administrador puede enviar valores de costo. Un rol
    no administrador (incluido `None`) que intente mutarlos es rechazado."""
    if puede_editar_costos(rol_usuario):
        return
    if costo_usd_efectivo is not None or costo_usd_bcv is not None:
        raise PermissionError(
            "ERR_PROD_ROL: Su rol no tiene permiso para ver ni modificar los "
            "costos del inventario. Solicítelo a un administrador."
        )


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
    costo_usd_efectivo=None,
    costo_usd_bcv=None,
    alerta_stock_minimo=None,
    sub_departamento: str = "",
    rol_usuario: str | None = None,
) -> dict:
    """Crea un nuevo producto en inventario. Aplica reglas ERS 3.1.

    `precio_dolares` = Precio USD Efectivo (pago en dólares físicos).
    `precio_bcv` = Precio USD BCV (referencia en dólares para pago en
    Bolívares a la tasa vigente) — ambos son valores manuales independientes.

    `costo_usd_efectivo` / `costo_usd_bcv` son los COSTOS del negocio, campos
    distintos de los precios anteriores y restringidos a roles administrativos
    (`rol_usuario`). El criterio es fail-closed: sin rol admin no se pueden
    enviar ni se devuelven en el diccionario resultante.
    """
    # ── Validaciones de campos obligatorios ──────────────────────────────────
    codigo = (codigo or "").strip()
    referencia = (referencia or "").strip()
    descripcion_general = (descripcion_general or "").strip()
    departamento = (departamento or "").strip()
    sub_departamento = (sub_departamento or "").strip()

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

    # ── Costos (rol admin) y umbral de alerta propio ─────────────────────────
    _validar_permiso_costos(costo_usd_efectivo, costo_usd_bcv, rol_usuario)
    costo_usd_efectivo = normalizar_costo(costo_usd_efectivo, "Costo USD Efectivo")
    costo_usd_bcv = normalizar_costo(costo_usd_bcv, "Costo USD BCV")
    alerta_stock_minimo = normalizar_alerta_stock_minimo(alerta_stock_minimo)
    validar_costo_obligatorio(existencia, costo_usd_efectivo)

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
                    fecha_ultima_modificacion, sub_departamento,
                    costo_usd_efectivo, costo_usd_bcv, alerta_stock_minimo
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    codigo, referencia, departamento, descripcion_general,
                    marca, precio_dolares, precio_bcv, proveedor_id,
                    existencia, codigo_barras, nombre_referencia_corto, fecha_mod,
                    sub_departamento or None,
                    costo_usd_efectivo, costo_usd_bcv, alerta_stock_minimo,
                ),
            )
            conn.commit()
    except sqlite3.IntegrityError as ex:
        msg = str(ex).lower()
        if "unique" in msg or "primary key" in msg:
            raise ValueError(f"ERR_PROD_DUPLICADO: Ya existe un producto con el código '{codigo}'.")
        raise ValueError(f"ERR_PROD_DB: Error de integridad al guardar el producto: {ex}")

    # El catálogo jerárquico aprende los valores nuevos que use el usuario.
    registrar_desde_producto(departamento, sub_departamento)

    return obtener_producto(codigo, rol_usuario=rol_usuario) or {}


def obtener_producto(codigo: str, rol_usuario: str | None = None) -> dict | None:
    """Obtiene un producto por su código primario. Agrega `monto_bcv_bolivares`
    (Precio USD BCV convertido a Bolívares con la tasa vigente, en vivo).

    Los campos de costo solo se incluyen si `rol_usuario` es administrativo
    (fail-closed: el valor por defecto `None` NO es administrador)."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM productos WHERE codigo = ?", (codigo.strip(),))
        row = cursor.fetchone()
        if not row:
            return None
        prod = _row_to_dict(row)
        prod["monto_bcv_bolivares"] = calcular_monto_bolivares(prod.get("precio_bcv", 0.0))
        return filtrar_campos_costo(prod, rol_usuario)


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
    costo_usd_efectivo=None,
    costo_usd_bcv=None,
    alerta_stock_minimo=None,
    sub_departamento: str = "",
    rol_usuario: str | None = None,
) -> dict:
    """Actualiza un producto existente. Aplica las mismas reglas ERS 3.1.

    Costos: un rol no administrativo no puede enviarlos (`PermissionError`) y
    los valores almacenados se PRESERVAN intactos en su actualización. Para
    cualquier rol, `None` en un costo significa "no modificar": nunca se pone
    un costo en NULL por omisión, con lo que la regla de obligatoriedad se
    satisface también con el costo ya almacenado.
    """
    codigo = (codigo or "").strip()
    referencia = (referencia or "").strip()
    descripcion_general = (descripcion_general or "").strip()
    departamento = (departamento or "").strip()
    sub_departamento = (sub_departamento or "").strip()

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

    # ── Costos: permiso, normalización y preservación de lo almacenado ───────
    _validar_permiso_costos(costo_usd_efectivo, costo_usd_bcv, rol_usuario)
    costo_usd_efectivo = normalizar_costo(costo_usd_efectivo, "Costo USD Efectivo")
    costo_usd_bcv = normalizar_costo(costo_usd_bcv, "Costo USD BCV")
    alerta_stock_minimo = normalizar_alerta_stock_minimo(alerta_stock_minimo)

    almacenado = _obtener_costos_almacenados(codigo)
    if almacenado is None:
        raise ValueError(f"ERR_PROD_NOT_FOUND: No se encontró el producto con código '{codigo}'.")
    if costo_usd_efectivo is None:
        costo_usd_efectivo = almacenado["costo_usd_efectivo"]
    if costo_usd_bcv is None:
        costo_usd_bcv = almacenado["costo_usd_bcv"]
    validar_costo_obligatorio(existencia, costo_usd_efectivo)

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
                sub_departamento = ?, costo_usd_efectivo = ?,
                costo_usd_bcv = ?, alerta_stock_minimo = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE codigo = ?
            """,
            (
                referencia, departamento, descripcion_general,
                marca, precio_dolares, precio_bcv,
                proveedor_id, existencia, codigo_barras,
                nombre_referencia_corto, fecha_mod,
                sub_departamento or None, costo_usd_efectivo,
                costo_usd_bcv, alerta_stock_minimo, codigo,
            ),
        )
        conn.commit()

    registrar_desde_producto(departamento, sub_departamento)

    resultado = obtener_producto(codigo, rol_usuario=rol_usuario)
    if not resultado:
        raise ValueError(f"ERR_PROD_NOT_FOUND: No se encontró el producto con código '{codigo}'.")
    return resultado


def _obtener_costos_almacenados(codigo: str) -> dict | None:
    """Costos actualmente guardados del producto, sin filtro de rol (uso
    interno para preservarlos en las actualizaciones). `None` si no existe."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT costo_usd_efectivo, costo_usd_bcv FROM productos WHERE codigo = ?",
            (codigo,),
        )
        row = cursor.fetchone()
    return dict(row) if row else None


# Columnas categóricas del inventario ofrecidas como filtros de selección
# múltiple con buscador (ver `ui/components/multi_select_filter.py`).
_COLUMNAS_MULTISELECT = ("departamento", "sub_departamento", "marca")


def obtener_opciones_filtro(columna: str) -> list[dict]:
    """Valores distintos no vacíos de una columna categórica del inventario
    (`departamento`, `sub_departamento` o `marca`), con la cantidad de
    productos que la usan.
    Ordenados por popularidad descendente: el filtro multi-selección con
    buscador muestra primero los valores más usados cuando no hay texto
    escrito en el buscador."""
    if columna not in _COLUMNAS_MULTISELECT:
        raise ValueError(f"Columna de filtro no soportada: {columna}")
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT {columna} AS valor, COUNT(*) AS total FROM productos "
            f"WHERE {columna} IS NOT NULL AND TRIM({columna}) <> '' "
            f"GROUP BY {columna} ORDER BY total DESC, valor COLLATE NOCASE ASC"
        )
        return [{"value": r["valor"], "label": r["valor"], "total": r["total"]} for r in cursor.fetchall()]


def obtener_opciones_proveedor_filtro() -> list[dict]:
    """Proveedores vinculados a algún producto del inventario, con la cantidad
    de productos que usan cada uno, ordenados por popularidad descendente."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT pv.id AS id,
                   COALESCE(NULLIF(TRIM(pv.empresa), ''), NULLIF(TRIM(pv.contacto), ''), 'Proveedor #' || pv.id) AS etiqueta,
                   COUNT(*) AS total
            FROM productos p
            JOIN proveedores pv ON pv.id = p.proveedor_id
            WHERE p.proveedor_id IS NOT NULL
            GROUP BY pv.id
            ORDER BY total DESC, etiqueta COLLATE NOCASE ASC
            """
        )
        return [{"value": str(r["id"]), "label": r["etiqueta"], "total": r["total"]} for r in cursor.fetchall()]


def listar_productos(
    departamento: str = "",
    busqueda: str = "",
    proveedor_id: int | None = None,
    filtros: dict | None = None,
    page: int = 1,
    per_page: int = 20,
    rol_usuario: str | None = None,
) -> list[dict]:
    """Lista productos con filtros opcionales.

    - `busqueda`: texto libre combinado con OR sobre varias columnas (búsqueda
      rápida tipo escáner/general, usada por Ventas y por el buscador general
      de Inventario). Cada palabra se exige con AND sobre el conjunto de
      columnas de texto (codigo, referencia, descripcion_general, marca,
      codigo_barras, nombre_referencia_corto).
    - `rol_usuario`: si no es administrativo, los campos de costo no aparecen
      en los diccionarios devueltos (fail-closed, por defecto `None`).
    - `filtros`: diccionario de filtros avanzados combinables, todos con AND
      entre sí:
        - `departamento`, `sub_departamento`, `marca`: lista de valores
          exactos (selección múltiple) — IN.
        - `proveedor_ids`: lista de IDs de proveedor — IN.
        - `precio_dolares_min/max`, `precio_bcv_min/max`, `existencia_min/max`:
          rango numérico (inclusive en ambos extremos).
        - `fecha_ingreso_desde/hasta`: rango sobre `created_at` (formato
          'YYYY-MM-DD').
        - `fecha_actualizacion_desde/hasta`: rango sobre
          `fecha_ultima_modificacion` (formato 'YYYY-MM-DD').
    """
    query = "SELECT * FROM productos WHERE 1=1"
    params: list = []

    if departamento:
        query += " AND departamento = ?"
        params.append(departamento.strip())

    if busqueda:
        # Búsqueda por palabras independientes (AND de ORs).
        # Cada columna va envuelta en IFNULL porque `marca`, `codigo_barras` y
        # `nombre_referencia_corto` son nullables: en SQL `NULL LIKE ?` evalúa
        # a NULL (no a falso), así que una sola columna nula bastaba para que
        # el OR dejara de encontrar coincidencias válidas en las demás.
        columnas_texto = (
            "codigo", "referencia", "descripcion_general",
            "marca", "codigo_barras", "nombre_referencia_corto",
        )
        condicion = " OR ".join(f"IFNULL({c}, '') LIKE ?" for c in columnas_texto)
        palabras = busqueda.strip().split()
        for pal in palabras:
            termino = f"%{pal}%"
            query += f" AND ({condicion})"
            params.extend([termino] * len(columnas_texto))

    if proveedor_id is not None:
        query += " AND proveedor_id = ?"
        params.append(proveedor_id)

    filtros = filtros or {}

    # ── Selección múltiple (IN) para columnas categóricas ────────────────────
    for columna in _COLUMNAS_MULTISELECT:
        valores = [v for v in (filtros.get(columna) or []) if v]
        if valores:
            placeholders = ",".join("?" * len(valores))
            query += f" AND {columna} IN ({placeholders})"
            params.extend(valores)

    proveedor_ids = [v for v in (filtros.get("proveedor_ids") or []) if v not in (None, "")]
    if proveedor_ids:
        placeholders = ",".join("?" * len(proveedor_ids))
        query += f" AND proveedor_id IN ({placeholders})"
        params.extend(int(v) for v in proveedor_ids)

    # ── Rangos numéricos (mín./máx. inclusive) ───────────────────────────────
    def _aplicar_rango_numerico(columna: str, prefijo: str) -> None:
        nonlocal query
        for sufijo, operador in (("_min", ">="), ("_max", "<=")):
            crudo = filtros.get(f"{prefijo}{sufijo}")
            crudo = str(crudo).strip() if crudo not in (None, "") else ""
            if not crudo:
                continue
            try:
                valor = float(crudo.replace(",", "."))
            except ValueError:
                continue
            query += f" AND {columna} {operador} ?"
            params.append(valor)

    _aplicar_rango_numerico("precio_dolares", "precio_dolares")
    _aplicar_rango_numerico("precio_bcv", "precio_bcv")
    _aplicar_rango_numerico("existencia", "existencia")

    # ── Rangos de fecha (ingreso = created_at, actualización = fecha_ultima_modificacion) ──
    def _aplicar_rango_fecha(columna: str, prefijo: str) -> None:
        nonlocal query
        desde = str(filtros.get(f"{prefijo}_desde") or "").strip()
        hasta = str(filtros.get(f"{prefijo}_hasta") or "").strip()
        if desde:
            query += f" AND {columna} >= ?"
            params.append(desde)
        if hasta:
            query += f" AND {columna} <= ?"
            # Fecha suelta (sin hora) debe incluir todo ese día completo.
            params.append(f"{hasta} 23:59:59" if len(hasta) == 10 else hasta)

    _aplicar_rango_fecha("created_at", "fecha_ingreso")
    _aplicar_rango_fecha("fecha_ultima_modificacion", "fecha_actualizacion")

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
    return [filtrar_campos_costo(p, rol_usuario) for p in productos]


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
