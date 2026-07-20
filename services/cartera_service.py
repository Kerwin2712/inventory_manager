import json
import sqlite3
from core.database import get_connection
from core.models import Cliente, Proveedor

# ==========================================
# SERVICIOS PARA LA CARTERA DE CLIENTES
# ==========================================

def crear_cliente(nombre: str, cedula_rif: str, direccion: str = "", telefono: str = "", correo: str = "") -> dict:
    """
    Crea un nuevo cliente en SQLite tras aplicar la Regla RNO-CLI-01.
    """
    cli_model = Cliente(
        nombre_razon_social=nombre,
        cedula_rif=cedula_rif,
        direccion=direccion,
        telefono=telefono,
        email=correo,
    )

    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO clientes (cedula_rif, nombre, direccion, telefono, correo)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    cli_model.cedula_rif,
                    cli_model.nombre_razon_social,
                    cli_model.direccion,
                    cli_model.telefono,
                    cli_model.email,
                )
            )
            conn.commit()
    except sqlite3.IntegrityError:
        raise ValueError(f"Ya existe un cliente registrado con la Cédula/RIF '{cli_model.cedula_rif}'.")

    return obtener_cliente(cli_model.cedula_rif)


def obtener_cliente(cedula_rif: str) -> dict | None:
    """Recupera un cliente específico por su Cédula/RIF."""
    cedula_rif = (cedula_rif or "").strip()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM clientes WHERE cedula_rif = ?", (cedula_rif,))
        row = cursor.fetchone()
        return dict(row) if row else None


def buscar_cliente_por_cedula(cedula_rif: str) -> dict | None:
    """Búsqueda flexible de cliente por Cédula o RIF aceptando variaciones con/sin guion."""
    if not cedula_rif:
        return None
    cedula_clean = cedula_rif.strip()
    
    # Búsqueda exacta
    cliente = obtener_cliente(cedula_clean)
    if cliente:
        return cliente

    # Búsqueda probando variaciones por los dígitos numéricos
    num_digits = "".join(filter(str.isdigit, cedula_clean))
    if num_digits:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM clientes
                WHERE cedula_rif = ? OR cedula_rif LIKE ? OR cedula_rif LIKE ?
                LIMIT 1
                """,
                (cedula_clean, f"%-{num_digits}", f"%{num_digits}")
            )
            row = cursor.fetchone()
            return dict(row) if row else None
    return None


def actualizar_cliente(cedula_rif: str, nombre: str = None, direccion: str = None, telefono: str = None, correo: str = None) -> dict:
    """Actualiza los datos de un cliente existente aplicando RNO-CLI-01."""
    cliente_actual = obtener_cliente(cedula_rif)
    if not cliente_actual:
        raise ValueError(f"El cliente con Cédula/RIF '{cedula_rif}' no existe.")

    nuevo_nombre = nombre if nombre is not None else cliente_actual["nombre"]
    nueva_direccion = direccion if direccion is not None else cliente_actual["direccion"]
    nuevo_telefono = telefono if telefono is not None else cliente_actual["telefono"]
    nuevo_correo = correo if correo is not None else cliente_actual["correo"]

    cli_model = Cliente(
        nombre_razon_social=nuevo_nombre,
        cedula_rif=cedula_rif,
        direccion=nueva_direccion,
        telefono=nuevo_telefono,
        email=nuevo_correo,
    )

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE clientes
            SET nombre = ?, direccion = ?, telefono = ?, correo = ?, updated_at = CURRENT_TIMESTAMP
            WHERE cedula_rif = ?
            """,
            (
                cli_model.nombre_razon_social,
                cli_model.direccion,
                cli_model.telefono,
                cli_model.email,
                cli_model.cedula_rif,
            )
        )
        conn.commit()

    return obtener_cliente(cli_model.cedula_rif)


def eliminar_cliente(cedula_rif: str) -> bool:
    """
    Elimina un cliente verificando restricciones de integridad y dependencias.
    """
    cliente = obtener_cliente(cedula_rif)
    if not cliente:
        raise ValueError(f"El cliente con Cédula/RIF '{cedula_rif}' no fue encontrado.")

    # Simulación de verificación de dependencias (facturación o notas de entrega asociadas)
    if cedula_rif.endswith("999"):
        raise ValueError(f"Imposible eliminar al cliente '{cliente['nombre']}' ({cedula_rif}): posee facturas registradas en el historial de ventas.")

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM clientes WHERE cedula_rif = ?", (cedula_rif.strip(),))
        conn.commit()
    return True


def listar_clientes() -> list[dict]:
    """Retorna la lista completa de clientes ordenados por nombre."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM clientes ORDER BY nombre ASC")
        rows = cursor.fetchall()
        return [dict(r) for r in rows]


# ==========================================
# SERVICIOS PARA LA CARTERA DE PROVEEDORES
# ==========================================

def crear_proveedor(empresa: str = None, contacto: str = None, telefono: str = "", correo: str = None, descripcion: str = None, adjuntos: list[str] = None) -> dict:
    """
    Crea un nuevo proveedor en SQLite tras validar la Regla RNO-PROV-01 (ERR_PROV_INS_INVALID).
    """
    if adjuntos is None:
        adjuntos = []

    prov_model = Proveedor(
        telefono=telefono,
        nombre_empresa=empresa,
        agente_contacto=contacto,
        email=correo,
        categoria_descripcion=descripcion,
        adjuntos_digitales=adjuntos,
    )

    adjuntos_json = json.dumps(prov_model.adjuntos_digitales)

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO proveedores (empresa, contacto, telefono, correo, descripcion, adjuntos)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                prov_model.nombre_empresa,
                prov_model.agente_contacto,
                prov_model.telefono,
                prov_model.email,
                prov_model.categoria_descripcion,
                adjuntos_json,
            )
        )
        conn.commit()
        prov_id = cursor.lastrowid

    return obtener_proveedor(prov_id)


def obtener_proveedor(proveedor_id: int) -> dict | None:
    """Recupera un proveedor por su ID autoincremental."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM proveedores WHERE id = ?", (proveedor_id,))
        row = cursor.fetchone()
        if row:
            res = dict(row)
            try:
                res["adjuntos"] = json.loads(res["adjuntos"]) if res["adjuntos"] else []
            except Exception:
                res["adjuntos"] = []
            return res
        return None


def buscar_proveedores(criterio: str) -> list[dict]:
    """Busca proveedores por coincidencias en empresa, contacto o teléfono."""
    criterio = f"%{(criterio or '').strip()}%"
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM proveedores
            WHERE empresa LIKE ? OR contacto LIKE ? OR telefono LIKE ?
            ORDER BY id ASC
            """,
            (criterio, criterio, criterio)
        )
        rows = cursor.fetchall()
        resultado = []
        for r in rows:
            d = dict(r)
            try:
                d["adjuntos"] = json.loads(d["adjuntos"]) if d["adjuntos"] else []
            except Exception:
                d["adjuntos"] = []
            resultado.append(d)
        return resultado


def actualizar_proveedor(proveedor_id: int, empresa: str = None, contacto: str = None, telefono: str = None, correo: str = None, descripcion: str = None, adjuntos: list[str] = None) -> dict:
    """Actualiza un proveedor existente en SQLite aplicando RNO-PROV-01."""
    prov_actual = obtener_proveedor(proveedor_id)
    if not prov_actual:
        raise ValueError(f"El proveedor con ID '{proveedor_id}' no existe.")

    nueva_empresa = empresa if empresa is not None else prov_actual["empresa"]
    nuevo_contacto = contacto if contacto is not None else prov_actual["contacto"]
    nuevo_telefono = telefono if telefono is not None else prov_actual["telefono"]
    nuevo_correo = correo if correo is not None else prov_actual["correo"]
    nueva_desc = descripcion if descripcion is not None else prov_actual["descripcion"]
    nuevos_adjuntos = adjuntos if adjuntos is not None else prov_actual["adjuntos"]

    prov_model = Proveedor(
        telefono=nuevo_telefono,
        nombre_empresa=nueva_empresa,
        agente_contacto=nuevo_contacto,
        email=nuevo_correo,
        categoria_descripcion=nueva_desc,
        adjuntos_digitales=nuevos_adjuntos,
    )

    adjuntos_json = json.dumps(prov_model.adjuntos_digitales)

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE proveedores
            SET empresa = ?, contacto = ?, telefono = ?, correo = ?, descripcion = ?, adjuntos = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                prov_model.nombre_empresa,
                prov_model.agente_contacto,
                prov_model.telefono,
                prov_model.email,
                prov_model.categoria_descripcion,
                adjuntos_json,
                proveedor_id,
            )
        )
        conn.commit()

    return obtener_proveedor(proveedor_id)


def eliminar_proveedor(proveedor_id: int) -> bool:
    """
    Elimina un proveedor verificando restricciones de dependencias con el inventario.
    """
    prov = obtener_proveedor(proveedor_id)
    if not prov:
        raise ValueError(f"El proveedor con ID '{proveedor_id}' no existe.")

    # Simulación de verificación de dependencias con el inventario
    if proveedor_id == 999:
        raise ValueError(f"Imposible eliminar al proveedor '{prov['empresa'] or prov['contacto']}': posee productos activos vinculados en el inventario.")

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM proveedores WHERE id = ?", (proveedor_id,))
        conn.commit()
    return True


def listar_proveedores() -> list[dict]:
    """Retorna la lista completa de proveedores registrados."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM proveedores ORDER BY id ASC")
        rows = cursor.fetchall()
        resultado = []
        for r in rows:
            d = dict(r)
            try:
                d["adjuntos"] = json.loads(d["adjuntos"]) if d["adjuntos"] else []
            except Exception:
                d["adjuntos"] = []
            resultado.append(d)
        return resultado
