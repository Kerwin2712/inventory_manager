from datetime import datetime, timezone
from core.database import get_setting, set_setting

# Claves de persistencia en app_settings
_KEY_TASA = "tasa_bcv"
_KEY_FECHA = "fecha_tasa_bcv"


def actualizar_tasa(tasa: float) -> None:
    """Guarda la tasa BCV y el timestamp de actualización en app_settings."""
    if tasa <= 0:
        raise ValueError("La tasa BCV debe ser un valor positivo mayor a cero.")
    set_setting(_KEY_TASA, str(tasa))
    set_setting(_KEY_FECHA, datetime.now(timezone.utc).isoformat())


def obtener_estado_tasa() -> dict:
    """Retorna la tasa actual y una cadena descriptiva del tiempo transcurrido.

    Retorna:
        {
            "tasa": float,          # 0.0 si no se ha configurado
            "fecha_iso": str,       # ISO 8601 del último guardado o ""
            "descripcion": str,     # Ej: "Actualizado hace 4 horas" / "Sin tasa configurada"
        }
    """
    tasa_raw = get_setting(_KEY_TASA, "0")
    fecha_raw = get_setting(_KEY_FECHA, "")

    try:
        tasa = float(tasa_raw)
    except (ValueError, TypeError):
        tasa = 0.0

    if not fecha_raw or tasa <= 0:
        return {
            "tasa": tasa,
            "fecha_iso": fecha_raw,
            "descripcion": "Sin tasa BCV configurada",
        }

    try:
        fecha_guardada = datetime.fromisoformat(fecha_raw)
        # Asegurar que ambos datetimes sean conscientes de la zona horaria
        ahora = datetime.now(timezone.utc)
        if fecha_guardada.tzinfo is None:
            fecha_guardada = fecha_guardada.replace(tzinfo=timezone.utc)
        delta = ahora - fecha_guardada
        segundos = int(delta.total_seconds())

        if segundos < 60:
            descripcion = "Actualizado hace menos de un minuto"
        elif segundos < 3600:
            minutos = segundos // 60
            descripcion = f"Actualizado hace {minutos} minuto{'s' if minutos != 1 else ''}"
        elif segundos < 86400:
            horas = segundos // 3600
            descripcion = f"Actualizado hace {horas} hora{'s' if horas != 1 else ''}"
        else:
            dias = segundos // 86400
            descripcion = f"Tiene {dias} día{'s' if dias != 1 else ''} sin actualizarse"
    except Exception:
        descripcion = "Fecha de actualización desconocida"

    return {
        "tasa": tasa,
        "fecha_iso": fecha_raw,
        "descripcion": descripcion,
    }
