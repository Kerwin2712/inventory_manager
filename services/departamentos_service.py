"""Catálogo jerárquico Departamento → Sub-Departamento.

`productos.departamento` y `productos.sub_departamento` siguen siendo TEXT
(compatibilidad con los filtros y consultas existentes); estas tablas son la
fuente de verdad que alimenta los selectores de la UI.
"""
from core.database import get_connection, _sincronizar_catalogo_departamentos


def _ordenar_alfabetico(valores) -> list[str]:
    """Orden alfabético estricto, case-insensitive y estable."""
    return sorted(valores, key=lambda v: (v.lower(), v))


def listar_departamentos() -> list[str]:
    """Nombres de todos los departamentos del catálogo, en orden alfabético."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT nombre FROM departamentos")
        return _ordenar_alfabetico(r["nombre"] for r in cursor.fetchall())


def listar_sub_departamentos(departamento: str) -> list[str]:
    """Sub-departamentos hijos de `departamento`, en orden alfabético.
    Devuelve `[]` si el nombre viene vacío o el padre no existe."""
    nombre = (departamento or "").strip()
    if not nombre:
        return []
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT s.nombre AS nombre
            FROM sub_departamentos s
            JOIN departamentos d ON d.id = s.departamento_id
            WHERE d.nombre = ? COLLATE NOCASE
            """,
            (nombre,),
        )
        return _ordenar_alfabetico(r["nombre"] for r in cursor.fetchall())


def crear_departamento(nombre: str) -> str:
    """Registra un departamento y devuelve su nombre canónico.

    Idempotente: si ya existe con otra capitalización no se duplica y se
    devuelve el nombre ya almacenado.
    """
    nombre = (nombre or "").strip()
    if not nombre:
        raise ValueError("ERR_DEPTO_REQ: El nombre del departamento es obligatorio.")
    with get_connection() as conn:
        cursor = conn.cursor()
        canonico = _obtener_o_crear_departamento(cursor, nombre)[1]
        conn.commit()
    return canonico


def crear_sub_departamento(departamento: str, nombre: str) -> str:
    """Registra un sub-departamento bajo `departamento` y devuelve su nombre
    canónico.

    Si el departamento padre no existe se crea automáticamente (la jerarquía
    nunca queda huérfana: el sub-departamento siempre necesita un padre).
    Idempotente igual que `crear_departamento`.
    """
    padre = (departamento or "").strip()
    nombre = (nombre or "").strip()
    if not padre:
        raise ValueError("ERR_DEPTO_REQ: El departamento padre es obligatorio.")
    if not nombre:
        raise ValueError("ERR_DEPTO_REQ: El nombre del sub-departamento es obligatorio.")

    with get_connection() as conn:
        cursor = conn.cursor()
        padre_id, _ = _obtener_o_crear_departamento(cursor, padre)
        cursor.execute(
            "SELECT nombre FROM sub_departamentos "
            "WHERE departamento_id = ? AND nombre = ? COLLATE NOCASE",
            (padre_id, nombre),
        )
        fila = cursor.fetchone()
        if fila:
            return fila["nombre"]
        cursor.execute(
            "INSERT INTO sub_departamentos (departamento_id, nombre) VALUES (?, ?)",
            (padre_id, nombre),
        )
        conn.commit()
    return nombre


def sincronizar_catalogo_departamentos() -> None:
    """Backfill del catálogo desde los valores ya presentes en `productos`.
    También la ejecuta `init_db()` al arrancar la aplicación."""
    with get_connection() as conn:
        cursor = conn.cursor()
        _sincronizar_catalogo_departamentos(cursor)
        conn.commit()


def registrar_desde_producto(departamento: str, sub_departamento: str = "") -> None:
    """Registra en el catálogo el departamento (y su sub-departamento) que
    acaba de usarse al crear o actualizar un producto. Silencioso ante valores
    vacíos para poder llamarse sin condicionales desde el servicio."""
    padre = (departamento or "").strip()
    hijo = (sub_departamento or "").strip()
    if not padre:
        return
    if hijo:
        crear_sub_departamento(padre, hijo)
    else:
        crear_departamento(padre)


def _obtener_o_crear_departamento(cursor, nombre: str) -> tuple[int, str]:
    """Devuelve `(id, nombre_canónico)` del departamento, creándolo si falta."""
    cursor.execute(
        "SELECT id, nombre FROM departamentos WHERE nombre = ? COLLATE NOCASE", (nombre,)
    )
    fila = cursor.fetchone()
    if fila:
        return int(fila["id"]), fila["nombre"]
    cursor.execute("INSERT INTO departamentos (nombre) VALUES (?)", (nombre,))
    return int(cursor.lastrowid), nombre
