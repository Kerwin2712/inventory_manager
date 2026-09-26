"""Motor de búsqueda multicriterio de productos para el módulo de Ventas.

Vive aparte de `inventario_service.listar_productos` por dos razones:

1. La búsqueda libre de `listar_productos` es un OR fijo sobre
   (codigo, referencia, descripcion_general, marca, codigo_barras,
   nombre_referencia_corto) — **no incluye `departamento`** —, así que no se
   puede obtener el criterio "Departamento" post-filtrando su resultado.
2. Ventas necesita elegir *en qué columna* buscar (el Dropdown "Buscar por"),
   no solo *qué* buscar. Eso exige una consulta cuyo conjunto de columnas se
   arma desde el criterio.

DECISIÓN DE SEGURIDAD (costos): las consultas de este módulo seleccionan las
columnas explícitamente y **jamás** incluyen `costo_usd_efectivo` ni
`costo_usd_bcv`. El módulo de Ventas no debe exponer los costos del negocio a
quien atiende el mostrador, así que aquí el filtrado no depende de un rol: los
costos simplemente nunca salen de la base. El SQL nunca interpola valores
(siempre parámetros `?`); los nombres de columna provienen exclusivamente del
mapa cerrado `CRITERIOS_BUSQUEDA` y se validan contra él.
"""
from core.database import get_connection
from services.inventario_service import calcular_monto_bolivares

# Mapa data-driven criterio visible → columnas de texto donde buscar. El orden
# de las claves es el orden en que el Dropdown de Ventas muestra las opciones.
# Agregar un criterio es agregar una línea aquí; no hay if/elif que tocar.
CRITERIOS_BUSQUEDA: dict[str, tuple[str, ...]] = {
    "Todos": (
        "codigo",
        "codigo_barras",
        "referencia",
        "descripcion_general",
        "nombre_referencia_corto",
        "departamento",
        "sub_departamento",
        "marca",
    ),
    "Código": ("codigo", "codigo_barras"),
    "Descripción": ("descripcion_general", "nombre_referencia_corto"),
    "Referencia": ("referencia",),
    "Departamento": ("departamento",),
    "Marca": ("marca",),
    "Sub-Departamento": ("sub_departamento",),
}

CRITERIO_POR_DEFECTO = "Todos"

# Columnas devueltas, enumeradas a propósito (nunca SELECT *): así una columna
# nueva —en particular una de costo— no se filtra sola hacia la vista de Ventas.
COLUMNAS_RESULTADO: tuple[str, ...] = (
    "codigo",
    "referencia",
    "descripcion_general",
    "nombre_referencia_corto",
    "departamento",
    "sub_departamento",
    "marca",
    "codigo_barras",
    "precio_dolares",
    "precio_bcv",
    "existencia",
)


def _columnas_de(criterio: str) -> tuple[str, ...]:
    """Valida el criterio contra el mapa cerrado y devuelve sus columnas."""
    if criterio not in CRITERIOS_BUSQUEDA:
        validos = ", ".join(CRITERIOS_BUSQUEDA)
        raise ValueError(
            f"ERR_BUSQ_CRITERIO: Criterio de búsqueda desconocido '{criterio}'. "
            f"Válidos: {validos}."
        )
    return CRITERIOS_BUSQUEDA[criterio]


def buscar_productos(termino: str, criterio: str = CRITERIO_POR_DEFECTO, limite: int = 50) -> list[dict]:
    """Busca productos por texto parcial dentro de las columnas de `criterio`.

    - Coincidencia parcial e insensible a mayúsculas/minúsculas (`LIKE` con
      `COLLATE NOCASE`).
    - Multi-palabra: cada palabra se exige con AND sobre el conjunto de
      columnas del criterio (mismo contrato que la búsqueda de Inventario).
    - Término vacío o de solo espacios → `[]` (nunca la tabla entera: el panel
      de resultados de Ventas no es un listado de inventario).
    - Criterio inexistente → `ValueError`.
    - Orden estable `departamento, codigo` para que el resultado sea predecible.
    - Agrega `monto_bcv_bolivares` calculado en vivo (Precio USD BCV × tasa
      vigente) reutilizando `inventario_service.calcular_monto_bolivares`.
    - No devuelve columnas de costo (ver docstring del módulo).
    """
    columnas = _columnas_de(criterio)

    palabras = (termino or "").strip().split()
    if not palabras:
        return []

    seleccion = ", ".join(COLUMNAS_RESULTADO)
    condiciones: list[str] = []
    params: list = []
    for palabra in palabras:
        # `IFNULL` porque `codigo_barras`, `marca` y `nombre_referencia_corto`
        # son nullables: un NULL haría que el LIKE evaluase a NULL, no a falso,
        # y el OR perdería el resto de las columnas.
        ors = " OR ".join(f"IFNULL({c}, '') LIKE ? COLLATE NOCASE" for c in columnas)
        condiciones.append(f"({ors})")
        params.extend([f"%{palabra}%"] * len(columnas))

    query = (
        f"SELECT {seleccion} FROM productos"
        f" WHERE {' AND '.join(condiciones)}"
        " ORDER BY departamento, codigo"
        " LIMIT ?"
    )
    params.append(max(0, int(limite)))

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        resultados = [dict(fila) for fila in cursor.fetchall()]

    for p in resultados:
        p["monto_bcv_bolivares"] = calcular_monto_bolivares(p.get("precio_bcv") or 0.0)
    return resultados


def resolver_coincidencia_exacta(termino: str, resultados: list[dict]) -> dict | None:
    """Devuelve el producto cuyo `codigo` o `codigo_barras` es exactamente
    `termino` (sin distinguir mayúsculas), o `None` si no hay ninguno.

    Es la regla que hace determinista el escaneo de código de barras: el
    escáner escribe el código completo y debe resolver a un único producto sin
    depender del orden de la lista. `codigo` tiene prioridad sobre
    `codigo_barras`.
    """
    clave = (termino or "").strip().upper()
    if not clave:
        return None

    for campo in ("codigo", "codigo_barras"):
        for p in resultados:
            valor = (p.get(campo) or "").strip().upper()
            if valor and valor == clave:
                return p
    return None
