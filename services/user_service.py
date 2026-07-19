from core.database import get_connection
from core.security import hash_password, verify_password

def authenticate_user(username: str, password: str) -> dict | None:
    """Autentica a un usuario comprobando su contraseña contra la BD."""
    username = username.strip()
    if not username or not password:
        return None
        
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, password_hash, role FROM users WHERE username = ?", (username,))
        row = cursor.fetchone()
        
        if row and verify_password(password, row["password_hash"]):
            return {
                "id": row["id"],
                "username": row["username"],
                "role": row["role"]
            }
    return None

def create_user(username: str, password: str, role: str = "vendedor") -> tuple[bool, str]:
    """Crea un nuevo usuario con su contraseña hasheada."""
    username = username.strip()
    if not username or not password:
        return False, "Usuario y contraseña son requeridos."
        
    hashed_pw = hash_password(password)
    
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                (username, hashed_pw, role)
            )
            conn.commit()
            return True, f"Usuario '{username}' creado exitosamente."
    except Exception as e:
        if "UNIQUE constraint failed" in str(e):
            return False, f"El nombre de usuario '{username}' ya se encuentra registrado."
        return False, f"Error al crear usuario: {str(e)}"

def get_all_users() -> list[dict]:
    """Obtiene la lista de todos los usuarios registrados."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, role, created_at FROM users ORDER BY id ASC")
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

def update_user(user_id: int, username: str, password: str = None, role: str = None) -> tuple[bool, str]:
    """Actualiza datos de un usuario existente."""
    username = username.strip()
    if not username:
        return False, "El nombre de usuario no puede estar vacío."
        
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            if password and password.strip():
                hashed_pw = hash_password(password.strip())
                cursor.execute(
                    "UPDATE users SET username = ?, password_hash = ?, role = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (username, hashed_pw, role, user_id)
                )
            else:
                cursor.execute(
                    "UPDATE users SET username = ?, role = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (username, role, user_id)
                )
            conn.commit()
            return True, f"Usuario '{username}' actualizado correctamente."
    except Exception as e:
        if "UNIQUE constraint failed" in str(e):
            return False, f"El nombre de usuario '{username}' ya está en uso."
        return False, f"Error al actualizar usuario: {str(e)}"
