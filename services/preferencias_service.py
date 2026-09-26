"""Preferencias de interfaz persistidas POR USUARIO.

Se apoya en la tabla `app_settings` (`get_setting`/`set_setting`), el mismo
mecanismo que ya usan el tema y el color de acento. La diferencia es que estas
preferencias se guardan con una clave namespaced (`<preferencia>:<usuario>`)
para que dos vendedores en el mismo equipo no se pisen la configuración.

Criterio tolerante en la LECTURA y estricto en la ESCRITURA: leer nunca lanza
(un valor ausente, corrupto o de una versión anterior cae al valor por
defecto), mientras que guardar un valor fuera del catálogo es un error de
programación y lanza `ValueError`.
"""
from core.database import get_setting, set_setting

# Modos de visualización del catálogo de Inventario (los define
# `InventarioView`; esta tupla es el contrato de valores válidos).
MODOS_VISTA_INVENTARIO = ("separado", "agrupado", "tarjetas")
MODO_VISTA_INVENTARIO_DEFECTO = "separado"

# Nombre de la preferencia dentro de `app_settings`.
PREF_VISTA_INVENTARIO = "vista_inventario"

# Cubo genérico cuando no hay usuario identificado (login pendiente o vista
# instanciada de forma aislada): la preferencia se guarda igual, sin fallar.
_USUARIO_ANONIMO = "_sesion"


def _clave(username: str | None, nombre: str) -> str:
    """Clave namespaced de `app_settings` para una preferencia de usuario."""
    usuario = (username or "").strip() or _USUARIO_ANONIMO
    return f"{nombre}:{usuario}"


def _leer_opcion(username: str | None, nombre: str, validos, defecto: str) -> str:
    """Lee una preferencia de tipo enumerado. Ante cualquier problema (clave
    ausente, valor corrupto o fallo de la base) devuelve `defecto`."""
    try:
        valor = (get_setting(_clave(username, nombre), "") or "").strip()
    except Exception:
        return defecto
    return valor if valor in validos else defecto


def _guardar_opcion(username: str | None, nombre: str, valor: str, validos, etiqueta: str) -> str:
    """Valida contra `validos` y persiste. Devuelve el valor guardado."""
    limpio = (valor or "").strip()
    if limpio not in validos:
        raise ValueError(
            f"ERR_PREF_INVALIDA: '{valor}' no es un valor válido para {etiqueta}. "
            f"Opciones: {', '.join(validos)}."
        )
    set_setting(_clave(username, nombre), limpio)
    return limpio


def obtener_vista_inventario(username: str | None) -> str:
    """Último modo de vista del catálogo elegido por `username`.
    Devuelve `MODO_VISTA_INVENTARIO_DEFECTO` si no hay preferencia guardada,
    si el valor almacenado es inválido o si no hay usuario."""
    return _leer_opcion(
        username, PREF_VISTA_INVENTARIO,
        MODOS_VISTA_INVENTARIO, MODO_VISTA_INVENTARIO_DEFECTO,
    )


def guardar_vista_inventario(username: str | None, modo: str) -> str:
    """Persiste el modo de vista del catálogo para `username` y lo devuelve.
    Lanza `ValueError` si `modo` no pertenece a `MODOS_VISTA_INVENTARIO`."""
    return _guardar_opcion(
        username, PREF_VISTA_INVENTARIO, modo,
        MODOS_VISTA_INVENTARIO, "el modo de vista del inventario",
    )
