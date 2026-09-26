"""Permisos por rol sobre los campos sensibles del inventario.

Los COSTOS (`costo_usd_efectivo`, `costo_usd_bcv`) son lo que le cuesta al
negocio adquirir el producto — información reservada a la administración. No
deben confundirse con los PRECIOS de venta (`precio_dolares` = Precio USD
Efectivo, `precio_bcv` = Precio USD BCV), que todo vendedor necesita ver.

Criterio fail-closed: `None`, vacío o un rol desconocido NO es administrador.
"""

# Roles con acceso total a los costos del inventario.
ROLES_ADMIN = ("administrador", "superadmin", "gerencia")

# Campos de la tabla `productos` restringidos por rol.
CAMPOS_COSTO = ("costo_usd_efectivo", "costo_usd_bcv")


def es_admin(rol: str | None) -> bool:
    """True solo si el rol pertenece a `ROLES_ADMIN` (comparación
    case-insensitive y tolerante a espacios). `None`/vacío → False."""
    if not rol:
        return False
    return str(rol).strip().lower() in ROLES_ADMIN


def puede_ver_costos(rol: str | None) -> bool:
    """Indica si el rol puede LEER los campos de costo del inventario."""
    return es_admin(rol)


def puede_editar_costos(rol: str | None) -> bool:
    """Indica si el rol puede ESCRIBIR los campos de costo del inventario."""
    return es_admin(rol)


def filtrar_campos_costo(datos: dict, rol: str | None) -> dict:
    """Devuelve una copia de `datos` sin las claves de costo cuando el rol no
    es administrador. Si es administrador, la copia queda intacta."""
    copia = dict(datos or {})
    if puede_ver_costos(rol):
        return copia
    for campo in CAMPOS_COSTO:
        copia.pop(campo, None)
    return copia
