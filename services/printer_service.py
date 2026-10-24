"""Servicio de Impresión Térmica y Gestión de Impresoras (ESC/POS y Spooler de Windows).

Soporta impresoras térmicas de 80mm (como el modelo MP80-12 / MPT-II USB y Bluetooth)
utilizando el protocolo estándar ESC/POS y el subsistema de impresión nativo de Windows
(winspool.drv) mediante ctypes, sin dependencias externas obligatorias.

Incluye:
- Detección automática de impresoras conectadas (USB / Bluetooth / Red).
- Generación de comandos ESC/POS formateados para papel de 80mm (48 columnas).
- Impresión directa de tickets de venta y notas de entrega.
- Impresión de tickets de prueba.
- Verificación del estado de conexión (en línea vs fuera de línea).
- Persistencia de la impresora preferida en app_settings.
"""
import ctypes
import datetime
import os
import platform
import re
import subprocess
import threading
import time
from ctypes import wintypes
from typing import Optional, List, Dict, Tuple

from core.database import get_connection, get_setting, set_setting

# Configuración de clave en base de datos para la impresora seleccionada
CLAVE_IMPRESORA_TERMICA = "printer_thermal_name"

# Bloqueos para evitar colisiones y accesos simultáneos a los puertos COM y USB
_COM_PORT_LOCK = threading.RLock()
_USB_PORT_LOCK = threading.RLock()
_PORT_LOCK = _COM_PORT_LOCK  # Respaldo de compatibilidad hacia atrás

# Caché en memoria para evitar sondeos repetidos que ralenticen la interfaz
_CACHE_ESTADO_CONEXION: Dict[str, Dict] = {}  # { "COM5": {"conectada": bool, "timestamp": float} }
CACHE_TTL_SEGUNDOS = 2.0


def limpiar_cache_impresora() -> None:
    """Invalida la caché de estado de conexión para forzar un re-escaneo en vivo de la impresora."""
    _CACHE_ESTADO_CONEXION.clear()


# Palabras clave habituales para identificar modelos térmicos de 80mm en Windows
PALABRAS_CLAVE_TERMICAS = [
    "mp80", "mpt", "pos-80", "pos80", "pos 80", "pos", "thermal",
    "80mm", "termica", "receipt", "ticket", "zj-80", "rp80",
    "xp-", "xprinter", "58/80", "bluetooth", "mini printer",
    "superrisc", "s31", "usb: "
]

# Estructura DOC_INFO_1 requerida por StartDocPrinterW en winspool.drv
class DOC_INFO_1(ctypes.Structure):
    _fields_ = [
        ("pDocName", wintypes.LPWSTR),
        ("pOutputFile", wintypes.LPWSTR),
        ("pDatatype", wintypes.LPWSTR),
    ]


class PRINTER_INFO_4(ctypes.Structure):
    _fields_ = [
        ("pPrinterName", wintypes.LPWSTR),
        ("pServerName", wintypes.LPWSTR),
        ("Attributes", wintypes.DWORD),
    ]


PRINTER_ATTRIBUTE_DEFAULT = 0x00000004
PRINTER_ATTRIBUTE_WORK_OFFLINE = 0x00000400


def listar_puertos_com_sistema(forzar_verificacion: bool = False) -> List[Dict]:
    """Obtiene la lista de puertos COM activos en Windows, identificando dispositivos Bluetooth térmicos."""
    sistema = platform.system()
    puertos = []
    if sistema != "Windows":
        return puertos

    try:
        import winreg

        # 1. Mapeo de dispositivos Bluetooth en BTHENUM para asociar MAC con FriendlyName
        bt_names: Dict[str, str] = {}
        try:
            key_bt = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Enum\BTHENUM")
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(key_bt, i)
                    if sub.startswith("Dev_"):
                        sub_k = winreg.OpenKey(key_bt, sub)
                        j = 0
                        while True:
                            try:
                                inst = winreg.EnumKey(sub_k, j)
                                inst_k = winreg.OpenKey(sub_k, inst)
                                try:
                                    fn, _ = winreg.QueryValueEx(inst_k, "FriendlyName")
                                    mac = sub.replace("Dev_", "").upper()
                                    bt_names[mac] = str(fn)
                                except Exception:
                                    pass
                                j += 1
                            except WindowsError:
                                break
                    i += 1
                except WindowsError:
                    break
        except Exception:
            pass

        # 2. Asociar puertos seriales con nombres de dispositivos Bluetooth
        port_to_name: Dict[str, str] = {}
        try:
            key_bt = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Enum\BTHENUM")
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(key_bt, i)
                    sub_k = winreg.OpenKey(key_bt, sub)
                    j = 0
                    while True:
                        try:
                            inst = winreg.EnumKey(sub_k, j)
                            inst_k = winreg.OpenKey(sub_k, inst)
                            try:
                                dp = winreg.OpenKey(inst_k, "Device Parameters")
                                pname, _ = winreg.QueryValueEx(dp, "PortName")
                                pname_clean = str(pname).upper().strip()
                                matched = None
                                for mac, name in bt_names.items():
                                    if mac in inst.upper():
                                        matched = f"{name} Bluetooth"
                                        break
                                if not matched:
                                    matched = "Bluetooth Serial"
                                port_to_name[pname_clean] = matched
                            except Exception:
                                pass
                            j += 1
                        except WindowsError:
                            break
                    i += 1
                except WindowsError:
                    break
        except Exception:
            pass

        # 3. Leer puertos activos de HARDWARE\DEVICEMAP\SERIALCOMM
        try:
            key_sc = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DEVICEMAP\SERIALCOMM")
            i = 0
            while True:
                try:
                    dev, port, _ = winreg.EnumValue(key_sc, i)
                    port_upper = str(port).upper().strip()
                    desc = port_to_name.get(port_upper)
                    if not desc:
                        if "bth" in str(dev).lower():
                            desc = "Bluetooth Serial"
                        else:
                            desc = "Puerto Serie"
                    cached = _CACHE_ESTADO_CONEXION.get(port_upper)
                    if cached:
                        is_offline = not cached.get("conectada", False)
                    else:
                        is_offline = True
                    puertos.append({
                        "nombre": f"{port_upper} ({desc})",
                        "puerto": port_upper,
                        "is_default": False,
                        "is_offline": is_offline,
                        "tipo": "serial",
                        "descripcion": desc,
                    })
                    i += 1
                except WindowsError:
                    break
        except Exception:
            pass

    except Exception:
        pass

    return puertos


# Identificador GUID de Windows para interfaces de dispositivos de impresión USB (GUID_DEVINTERFACE_USBPRINT)
GUID_DEVINTERFACE_USBPRINT = "{28d78fad-5a12-11d1-ae5b-0000f803a8c2}"


def probar_conexion_puerto_usb(ruta_dispositivo: str) -> bool:
    """Verifica si la impresora USB física está conectada, encendida y accesible por Windows."""
    if not ruta_dispositivo:
        return False
    sistema = platform.system()
    if sistema != "Windows":
        return False

    kernel32 = ctypes.windll.kernel32
    GENERIC_WRITE = 0x40000000
    OPEN_EXISTING = 3
    FILE_ATTRIBUTE_NORMAL = 0x80

    acquired = _USB_PORT_LOCK.acquire(timeout=0.3)
    if not acquired:
        return False
    try:
        h = kernel32.CreateFileW(
            ruta_dispositivo,
            GENERIC_WRITE,
            0,
            None,
            OPEN_EXISTING,
            FILE_ATTRIBUTE_NORMAL,
            None
        )
        if h != -1 and h != 0:
            kernel32.CloseHandle(h)
            _CACHE_ESTADO_CONEXION[ruta_dispositivo] = {"conectada": True, "timestamp": time.time()}
            return True
    except Exception:
        pass
    finally:
        _USB_PORT_LOCK.release()

    _CACHE_ESTADO_CONEXION[ruta_dispositivo] = {"conectada": False, "timestamp": time.time()}
    return False


def listar_dispositivos_usb_impresora(forzar_verificacion: bool = False) -> List[Dict]:
    """Obtiene los dispositivos de impresión USB conectados directamente en Windows (usbprint.sys).
    
    Permite detectar y comunicarse directamente con impresoras térmicas USB (ej. MP80-12 / SUPERRISC S31)
    incluso si Windows no tiene instalado ningún controlador Spooler para el modelo.
    """
    sistema = platform.system()
    dispositivos = []
    if sistema != "Windows":
        return dispositivos

    try:
        import winreg
        base_key = rf"SYSTEM\CurrentControlSet\Control\DeviceClasses\{GUID_DEVINTERFACE_USBPRINT}"
        try:
            k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base_key)
        except Exception:
            return dispositivos

        i = 0
        while True:
            try:
                sub = winreg.EnumKey(k, i)
                i += 1
                dev_k = winreg.OpenKey(k, sub)
                esta_activa = False
                try:
                    winreg.OpenKey(dev_k, "#")
                    esta_activa = True
                except WindowsError:
                    esta_activa = False

                # Convertir subclave a ruta DOS (##?#USB#... -> \\?\USB#...)
                partes = [p for p in sub.split("#") if p and p != "?"]
                ruta = "\\\\?\\" + "#".join(partes)

                nombre_amigable = "MP80-12 / POS-80"
                if len(partes) >= 3:
                    instancia = f"{partes[0]}\\{partes[1]}\\{partes[2]}"
                    try:
                        enum_k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"SYSTEM\CurrentControlSet\Enum\{instancia}")
                        for campo in ["FriendlyName", "DeviceDesc"]:
                            try:
                                val, _ = winreg.QueryValueEx(enum_k, campo)
                                if val:
                                    s = str(val).split(";")[-1].strip()
                                    if s and not s.startswith("@"):
                                        nombre_amigable = s
                                        break
                            except WindowsError:
                                pass
                    except Exception:
                        pass

                etiqueta = f"USB: {nombre_amigable}"
                if "mp80" not in nombre_amigable.lower() and "pos" not in nombre_amigable.lower():
                    etiqueta = f"USB: {nombre_amigable} (MP80-12)"

                # Verificar conexión física real. En Windows USB probar conexión toma <0.05ms,
                # por lo que verificar en vivo previene que un caché viejo marque "En línea"
                # cuando la impresora fue apagada o desconectada.
                is_offline = not esta_activa
                if esta_activa:
                    conectada = probar_conexion_puerto_usb(ruta)
                    is_offline = not conectada

                dispositivos.append({
                    "nombre": etiqueta,
                    "ruta_usb": ruta,
                    "is_default": False,
                    "is_offline": is_offline,
                    "tipo": "usb",
                    "descripcion": f"Impresora Térmica USB ({nombre_amigable})"
                })
            except WindowsError:
                break
    except Exception:
        pass

    return dispositivos


def listar_impresoras_sistema(forzar_verificacion: bool = False) -> List[Dict]:
    """Obtiene la lista de todas las impresoras instaladas en el sistema (Spooler y Puertos COM/Bluetooth).
    
    Retorna una lista de diccionarios:
    [
        {"nombre": "POS-80", "is_default": False, "is_offline": False, "tipo": "spooler"},
        {"nombre": "COM5 (MP80-12 Bluetooth)", "is_default": False, "is_offline": False, "tipo": "serial", "puerto": "COM5"},
        ...
    ]
    """
    sistema = platform.system()
    impresoras = []

    if sistema == "Windows":
        try:
            winspool = ctypes.WinDLL("winspool.drv")
            flags = 0x00000002 | 0x00000004  # PRINTER_ENUM_LOCAL | PRINTER_ENUM_CONNECTIONS
            needed = wintypes.DWORD(0)
            returned = wintypes.DWORD(0)

            # Primera llamada para obtener el tamaño de buffer requerido
            winspool.EnumPrintersW(flags, None, 4, None, 0, ctypes.byref(needed), ctypes.byref(returned))
            if needed.value > 0:
                buffer = (ctypes.c_byte * needed.value)()
                res = winspool.EnumPrintersW(
                    flags, None, 4, buffer, needed.value, ctypes.byref(needed), ctypes.byref(returned)
                )
                if res:
                    struct_ptr = ctypes.cast(buffer, ctypes.POINTER(PRINTER_INFO_4))
                    for i in range(returned.value):
                        p = struct_ptr[i]
                        p_name = p.pPrinterName or ""
                        is_offline = bool(p.Attributes & PRINTER_ATTRIBUTE_WORK_OFFLINE)
                        is_default = bool(p.Attributes & PRINTER_ATTRIBUTE_DEFAULT)
                        impresoras.append({
                            "nombre": p_name,
                            "is_default": is_default,
                            "is_offline": is_offline,
                            "tipo": "spooler",
                        })
        except Exception:
            pass

        # Si winspool falló o no devolvió elementos, respaldo con winreg
        if not impresoras:
            try:
                import winreg
                key = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows NT\CurrentVersion\Devices"
                )
                i = 0
                while True:
                    try:
                        nombre, _, _ = winreg.EnumValue(key, i)
                        impresoras.append({
                            "nombre": nombre,
                            "is_default": False,
                            "is_offline": False,
                            "tipo": "spooler",
                        })
                        i += 1
                    except WindowsError:
                        break
            except Exception:
                pass

        # Agregar puertos COM / Bluetooth activos (ej. COM5 MP80-12)
        try:
            puertos_com = listar_puertos_com_sistema(forzar_verificacion=forzar_verificacion)
            for p in puertos_com:
                impresoras.append(p)
        except Exception:
            pass

        # Agregar impresoras USB directas (ej. SUPERRISC S31 / MP80-12 USB)
        try:
            dispositivos_usb = listar_dispositivos_usb_impresora(forzar_verificacion=forzar_verificacion)
            for u in dispositivos_usb:
                impresoras.append(u)
        except Exception:
            pass

    elif sistema in ("Linux", "Darwin"):
        try:
            out = subprocess.check_output(["lpstat", "-p"], stderr=subprocess.DEVNULL, text=True)
            for line in out.splitlines():
                if line.startswith("printer "):
                    parts = line.split()
                    if len(parts) >= 2:
                        p_name = parts[1]
                        is_offline = "disabled" in line.lower()
                        impresoras.append({
                            "nombre": p_name,
                            "is_default": False,
                            "is_offline": is_offline,
                            "tipo": "spooler",
                        })
        except Exception:
            pass

    return impresoras


def obtener_impresora_termica_configurada() -> str:
    """Retorna el nombre de la impresora térmica guardada en la base de datos."""
    return (get_setting(CLAVE_IMPRESORA_TERMICA, "") or "").strip()


def guardar_impresora_termica_configurada(nombre: str) -> None:
    """Guarda en base de datos la impresora preferida para tickets térmicos."""
    set_setting(CLAVE_IMPRESORA_TERMICA, (nombre or "").strip())


def probar_conexion_puerto_com(puerto: str, timeout_sec: float = 2.5) -> bool:
    """Intenta abrir brevemente el puerto COM para verificar si el dispositivo físico (Bluetooth/USB) está encendido y receptivo."""
    match = re.search(r"\bCOM\d+\b", (puerto or "").upper())
    puerto_limpio = match.group(0) if match else (puerto or "").strip().upper()
    if not puerto_limpio:
        return False

    dispositivo_path = rf"\\.\{puerto_limpio}"
    kernel32 = ctypes.windll.kernel32
    GENERIC_READ = 0x80000000
    GENERIC_WRITE = 0x40000000
    OPEN_EXISTING = 3
    FILE_ATTRIBUTE_NORMAL = 0x80

    resultado = [False]

    def _intentar():
        acquired = _COM_PORT_LOCK.acquire(timeout=0.5)
        if not acquired:
            return
        try:
            h = kernel32.CreateFileW(
                dispositivo_path,
                GENERIC_READ | GENERIC_WRITE,
                0,
                None,
                OPEN_EXISTING,
                FILE_ATTRIBUTE_NORMAL,
                None
            )
            if h != -1 and h != 0:
                kernel32.CloseHandle(h)
                time.sleep(0.05)
                resultado[0] = True
        except Exception:
            pass
        finally:
            _COM_PORT_LOCK.release()

    t = threading.Thread(target=_intentar, daemon=True, name=f"ProbeCOM_{puerto_limpio}")
    t.start()
    t.join(timeout=timeout_sec)
    conectada = resultado[0]

    _CACHE_ESTADO_CONEXION[puerto_limpio] = {"conectada": conectada, "timestamp": time.time()}
    return conectada


def detectar_impresora_termica(verificar_online: bool = True, forzar_verificacion: bool = False) -> Optional[Dict]:
    """Detecta la impresora térmica disponible (vía Spooler de Windows o puerto COM/Bluetooth).
    
    Prioridad:
    1. Si hay una impresora guardada en app_settings y existe en el sistema.
    2. Si alguna impresora instalada o puerto COM coincide con palabras clave conocidas
       (MP80, MPT-II, POS-80, Thermal, etc.).
       
    Retorna un diccionario con:
    {
        "nombre": "COM5 (MP80-12 Bluetooth)",
        "conectada": bool,   # True si está encendida y accesible
        "is_default": False,
        "configurada_manualmente": bool,
        "tipo": "serial" | "spooler",
        "puerto": "COM5" | None
    }
    O None si no se encuentra ninguna impresora térmica.
    """
    if forzar_verificacion:
        limpiar_cache_impresora()

    impresoras = listar_impresoras_sistema(forzar_verificacion=forzar_verificacion)
    if not impresoras:
        return None

    candidata = None
    configurada_manualmente = False

    guardada = obtener_impresora_termica_configurada()
    if guardada:
        guardada_lower = guardada.lower()
        for imp in impresoras:
            nom_lower = imp["nombre"].lower()
            puerto_lower = str(imp.get("puerto", "")).lower()
            ruta_usb_lower = str(imp.get("ruta_usb", "")).lower()
            if (guardada_lower == nom_lower or 
                (puerto_lower and guardada_lower == puerto_lower) or
                (puerto_lower and puerto_lower in guardada_lower) or
                (ruta_usb_lower and guardada_lower == ruta_usb_lower) or
                (guardada_lower in nom_lower)):
                if not imp.get("is_offline"):
                    candidata = imp
                    configurada_manualmente = True
                    break
                if candidata is None:
                    candidata = imp
                    configurada_manualmente = True

    # Si no hay candidata guardada o la guardada está desconectada, buscar térmica disponible en línea
    if not candidata or candidata.get("is_offline"):
        for imp in impresoras:
            if not imp.get("is_offline"):
                nombre_lower = imp["nombre"].lower()
                for kw in PALABRAS_CLAVE_TERMICAS:
                    if kw in nombre_lower or imp.get("tipo") == "usb":
                        candidata = imp
                        configurada_manualmente = False
                        break
                if candidata and not candidata.get("is_offline"):
                    break

    # Si aún no hay candidata, tomar la primera coincidencia aunque esté fuera de línea
    if not candidata:
        for imp in impresoras:
            nombre_lower = imp["nombre"].lower()
            for kw in PALABRAS_CLAVE_TERMICAS:
                if kw in nombre_lower or imp.get("tipo") == "usb":
                    candidata = imp
                    configurada_manualmente = False
                    break
            if candidata:
                break

    if not candidata:
        return None

    tipo = candidata.get("tipo", "spooler")
    puerto = candidata.get("puerto")
    ruta_usb = candidata.get("ruta_usb")
    conectada = not candidata.get("is_offline", False)
    if tipo == "serial" and puerto:
        if verificar_online or forzar_verificacion:
            conectada = probar_conexion_puerto_com(puerto)
            _CACHE_ESTADO_CONEXION[puerto] = {"conectada": conectada, "timestamp": time.time()}
        else:
            cached = _CACHE_ESTADO_CONEXION.get(puerto)
            if cached and (time.time() - cached.get("timestamp", 0) < CACHE_TTL_SEGUNDOS):
                conectada = cached.get("conectada", False)
            else:
                conectada = False
    elif tipo == "usb" and ruta_usb:
        # En Windows USB, probar conexión toma <0.05ms y es 100% fidedigna en tiempo real
        conectada = probar_conexion_puerto_usb(ruta_usb)
        _CACHE_ESTADO_CONEXION[ruta_usb] = {"conectada": conectada, "timestamp": time.time()}

    return {
        "nombre": candidata["nombre"],
        "conectada": conectada,
        "is_default": candidata.get("is_default", False),
        "configurada_manualmente": configurada_manualmente,
        "tipo": tipo,
        "puerto": puerto,
        "ruta_usb": ruta_usb,
    }


def esta_impresora_conectada(nombre_impresora: Optional[str] = None, forzar_verificacion: bool = False) -> bool:
    """Verifica si la impresora indicada (o la térmica detectada) está conectada."""
    target = (nombre_impresora or "").strip()
    if not target:
        det = detectar_impresora_termica(verificar_online=True, forzar_verificacion=forzar_verificacion)
        return bool(det and det.get("conectada", False))

    # Si es una impresora USB directa (ej. 'USB: SUPERRISC S31 (MP80-12)')
    if target.upper().startswith("USB:") or r"\USB#" in target.upper():
        disps = listar_dispositivos_usb_impresora(forzar_verificacion=forzar_verificacion)
        for d in disps:
            if d["nombre"].lower() == target.lower() or d["ruta_usb"].lower() == target.lower():
                return probar_conexion_puerto_usb(d["ruta_usb"])
        if disps:
            return probar_conexion_puerto_usb(disps[0]["ruta_usb"])
        return False

    # Si es un puerto COM (ej. 'COM5' o 'COM5 (MP80-12 Bluetooth)')
    match = re.search(r"\bCOM\d+\b", target.upper())
    if match:
        puerto_buscado = match.group(0)
        puertos_activos = listar_puertos_com_sistema(forzar_verificacion=forzar_verificacion)
        if not any(p.get("puerto") == puerto_buscado for p in puertos_activos):
            return False

        ahora = time.time()
        cached = _CACHE_ESTADO_CONEXION.get(puerto_buscado)
        if not forzar_verificacion and cached and (ahora - cached.get("timestamp", 0) < CACHE_TTL_SEGUNDOS):
            return cached.get("conectada", False)

        conectada = probar_conexion_puerto_com(puerto_buscado, timeout_sec=6.0)
        _CACHE_ESTADO_CONEXION[puerto_buscado] = {"conectada": conectada, "timestamp": ahora}
        return conectada

    impresoras = listar_impresoras_sistema(forzar_verificacion=forzar_verificacion)
    for imp in impresoras:
        if imp["nombre"].lower() == target.lower():
            return not imp.get("is_offline", False)
    return False


def _limpiar_texto_impresora(texto: str) -> str:
    """Sustituye caracteres especiales o tildes para codificación CP437/CP850/Latin1."""
    if not texto:
        return ""
    reemplazos = {
        "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u",
        "Á": "A", "É": "E", "Í": "I", "Ó": "O", "Ú": "U",
        "ñ": "n", "Ñ": "N",
        "“": '"', "”": '"', "’": "'", "—": "-", "–": "-",
    }
    res = str(texto)
    for k, v in reemplazos.items():
        res = res.replace(k, v)
    return res


def generar_comandos_escpos(venta_id: int, divisa: str = "USD") -> bytes:
    """Genera la secuencia de bytes con comandos ESC/POS para papel de 80mm (48 columnas).
    
    Diseñado específicamente para impresoras térmicas de 80mm como la MP80-12:
    - Ancho de 48 caracteres.
    - Encabezado destacado.
    - Metadatos de la venta.
    - Tabla de items con código, nombre corto, cantidad, precio unitario y subtotal.
    - Totales en USD y BCV.
    - Separadores y líneas de corte manual (5 saltos de línea para el filo dentado).
    - Comando de corte de papel estándar GS V.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT v.id, v.tipo_venta, v.cliente_id, v.total_usd, v.total_bcv, v.fecha,
               v.metodo_pago, v.referencia_pago, v.referencia_omitida, v.monto_cobrado,
               v.porcentaje_descuento, v.usuario_nombre,
               c.nombre AS cliente_nombre, c.direccion AS cliente_direccion,
               c.telefono AS cliente_telefono
        FROM ventas v
        LEFT JOIN clientes c ON v.cliente_id = c.cedula_rif
        WHERE v.id = ?
    """, (venta_id,))
    venta = cursor.fetchone()

    if not venta:
        conn.close()
        raise ValueError(f"La venta con ID {venta_id} no existe.")

    cursor.execute("""
        SELECT vd.cantidad, vd.precio_unitario_usd, vd.precio_unitario_bcv,
               vd.subtotal_usd, vd.subtotal_bcv, p.codigo, p.nombre_referencia_corto, p.referencia
        FROM ventas_detalle vd
        JOIN productos p ON vd.producto_codigo = p.codigo
        WHERE vd.venta_id = ?
    """, (venta_id,))
    detalles = cursor.fetchall()
    conn.close()

    divisa_act = divisa.upper().strip() if divisa else "USD"
    if divisa_act not in ["USD", "BCV"]:
        divisa_act = "USD"
    simbolo = "$" if divisa_act == "USD" else "Bs."

    # Comandos ESC/POS estándar
    ESC = b"\x1b"
    GS = b"\x1d"
    INIT = ESC + b"@"
    ALIGN_LEFT = ESC + b"a\x00"
    ALIGN_CENTER = ESC + b"a\x01"
    ALIGN_RIGHT = ESC + b"a\x02"
    BOLD_ON = ESC + b"E\x01"
    BOLD_OFF = ESC + b"E\x00"
    DOUBLE_SIZE = ESC + b"!\x30"  # doble ancho y alto
    DOUBLE_HEIGHT = ESC + b"!\x10"
    NORMAL_SIZE = ESC + b"!\x00"

    buffer = bytearray()
    buffer.extend(INIT)

    # Encabezado centrado
    buffer.extend(ALIGN_CENTER)
    buffer.extend(BOLD_ON)
    buffer.extend(DOUBLE_HEIGHT)
    buffer.extend(_limpiar_texto_impresora("SISTEMA INTEGRADO DE VENTAS\n").encode("cp437", errors="ignore"))
    buffer.extend(NORMAL_SIZE)
    buffer.extend(BOLD_ON)
    buffer.extend(_limpiar_texto_impresora("COMPROBANTE / NOTA DE ENTREGA\n").encode("cp437", errors="ignore"))
    buffer.extend(BOLD_OFF)
    buffer.extend(b"------------------------------------------------\n")  # 48 guiones

    # Datos generales de la venta (alineados a la izquierda)
    buffer.extend(ALIGN_LEFT)
    f_fecha = str(venta["fecha"] or "")
    tipo = str(venta["tipo_venta"] or "Formal")
    metodo = str(venta["metodo_pago"] or "Efectivo")
    buffer.extend(_limpiar_texto_impresora(f"Ticket Nro:  {venta['id']:06d}\n").encode("cp437", errors="ignore"))
    buffer.extend(_limpiar_texto_impresora(f"Fecha:       {f_fecha}\n").encode("cp437", errors="ignore"))
    buffer.extend(_limpiar_texto_impresora(f"Tipo Venta:  {tipo}\n").encode("cp437", errors="ignore"))
    buffer.extend(_limpiar_texto_impresora(f"Metodo Pago: {metodo}\n").encode("cp437", errors="ignore"))
    
    ref = venta["referencia_pago"]
    if ref and not venta["referencia_omitida"]:
        buffer.extend(_limpiar_texto_impresora(f"Ref. Pago:   {ref}\n").encode("cp437", errors="ignore"))
    
    usr = venta["usuario_nombre"]
    if usr:
        buffer.extend(_limpiar_texto_impresora(f"Atendido por: {usr}\n").encode("cp437", errors="ignore"))

    # Datos de cliente
    if tipo == "Formal" and venta["cliente_id"]:
        c_nom = _limpiar_texto_impresora(str(venta["cliente_nombre"] or "Cliente"))
        c_rif = _limpiar_texto_impresora(str(venta["cliente_id"]))
        buffer.extend(_limpiar_texto_impresora(f"Cliente:     {c_nom}\n").encode("cp437", errors="ignore"))
        buffer.extend(_limpiar_texto_impresora(f"CI/RIF:      {c_rif}\n").encode("cp437", errors="ignore"))
        if venta["cliente_telefono"]:
            c_tel = _limpiar_texto_impresora(str(venta["cliente_telefono"]))
            buffer.extend(_limpiar_texto_impresora(f"Telefono:    {c_tel}\n").encode("cp437", errors="ignore"))
        if venta["cliente_direccion"]:
            c_dir = _limpiar_texto_impresora(str(venta["cliente_direccion"]))
            if len(c_dir) > 34:
                c_dir = c_dir[:31] + "..."
            buffer.extend(_limpiar_texto_impresora(f"Direccion:   {c_dir}\n").encode("cp437", errors="ignore"))
    else:
        buffer.extend(b"Cliente:     Mostrador / Informal\n")

    buffer.extend(b"------------------------------------------------\n")

    # Tabla de productos (48 columnas de ancho estándar 80mm)
    # Formato cabecera: CANT. DESCRIPCION (REF)         P.UNIT    TOTAL
    #                   6     23                        9         10
    cabecera = "CANT.  DESCRIPCION             P.UNIT     TOTAL\n"
    buffer.extend(BOLD_ON)
    buffer.extend(cabecera.encode("cp437", errors="ignore"))
    buffer.extend(BOLD_OFF)
    buffer.extend(b"------------------------------------------------\n")

    total_acumulado = 0.0
    for d in detalles:
        cant = float(d["cantidad"])
        if divisa_act == "USD":
            p_unit = float(d["precio_unitario_usd"])
            subtot = float(d["subtotal_usd"])
        else:
            p_unit = float(d["precio_unitario_bcv"])
            subtot = float(d["subtotal_bcv"])
        total_acumulado += subtot

        nombre_prod = _limpiar_texto_impresora(
            str(d["nombre_referencia_corto"] or d["referencia"] or d["codigo"] or "")
        )

        str_cant = f"{cant:.1f}".rjust(5)
        str_punit = f"{p_unit:,.2f}".rjust(9)
        str_subtot = f"{subtot:,.2f}".rjust(10)

        if len(nombre_prod) <= 22:
            linea = f"{str_cant}  {nombre_prod.ljust(22)} {str_punit} {str_subtot}\n"
            buffer.extend(linea.encode("cp437", errors="ignore"))
        else:
            linea1 = f"{str_cant}  {nombre_prod[:22]} {str_punit} {str_subtot}\n"
            linea2 = f"       {nombre_prod[22:46]}\n"
            buffer.extend(linea1.encode("cp437", errors="ignore"))
            buffer.extend(linea2.encode("cp437", errors="ignore"))

    buffer.extend(b"------------------------------------------------\n")

    # Totales y Resumen
    buffer.extend(ALIGN_RIGHT)
    pct_desc = float(venta["porcentaje_descuento"] or 0)
    if abs(pct_desc) >= 0.01:
        etiqueta_desc = f"Descuento ({pct_desc:+.1f}%): "
        buffer.extend(_limpiar_texto_impresora(f"{etiqueta_desc}\n").encode("cp437", errors="ignore"))

    # Total destacado
    buffer.extend(BOLD_ON)
    buffer.extend(DOUBLE_HEIGHT)
    buffer.extend(_limpiar_texto_impresora(f"TOTAL {divisa_act}: {simbolo} {total_acumulado:,.2f}\n").encode("cp437", errors="ignore"))
    buffer.extend(NORMAL_SIZE)
    buffer.extend(BOLD_OFF)

    # Mostrar también contravalor referencial
    if divisa_act == "USD":
        total_otro = float(venta["total_bcv"] or 0)
        buffer.extend(_limpiar_texto_impresora(f"Ref. BCV: Bs. {total_otro:,.2f}\n").encode("cp437", errors="ignore"))
    else:
        total_otro = float(venta["total_usd"] or 0)
        buffer.extend(_limpiar_texto_impresora(f"Ref. USD: $ {total_otro:,.2f}\n").encode("cp437", errors="ignore"))

    buffer.extend(ALIGN_CENTER)
    buffer.extend(b"------------------------------------------------\n")
    buffer.extend(b"*** GRACIAS POR SU COMPRA ***\n")
    buffer.extend(b"Conserve este ticket como constancia\n")
    buffer.extend(b"------------------------------------------------\n")

    # 5 saltos de línea para que el texto salga más allá del filo dentado de corte
    buffer.extend(b"\n\n\n\n\n")

    # Comando de corte parcial de papel GS V 65 3
    buffer.extend(GS + b"V\x41\x03")

    return bytes(buffer)


def enviar_datos_crudos_com(
    puerto: str,
    datos: bytes,
    timeout_ms: int = 6000
) -> Tuple[bool, str]:
    """Envía una secuencia de bytes crudos (ESC/POS) directamente a un puerto COM (Serial o Bluetooth SPP)."""
    if not datos:
        return False, "No hay datos para enviar a la impresora."

    sistema = platform.system()
    if sistema != "Windows":
        return False, "Impresión directa por puerto COM solo implementada para Windows."

    # Extraer el identificador del puerto (ej: de 'COM5 (MP80-12 Bluetooth)' -> 'COM5')
    match = re.search(r"\bCOM\d+\b", (puerto or "").upper())
    puerto_limpio = match.group(0) if match else puerto.strip().upper()
    dispositivo_path = rf"\\.\{puerto_limpio}"

    kernel32 = ctypes.windll.kernel32

    GENERIC_READ = 0x80000000
    GENERIC_WRITE = 0x40000000
    OPEN_EXISTING = 3
    FILE_ATTRIBUTE_NORMAL = 0x80

    with _PORT_LOCK:
        hPort = -1
        err = 0
        # Reintentar hasta 3 veces si el driver Bluetooth de Windows aún está cerrando la conexión previa (error 5 o 32)
        for intento in range(3):
            hPort = kernel32.CreateFileW(
                dispositivo_path,
                GENERIC_READ | GENERIC_WRITE,
                0,
                None,
                OPEN_EXISTING,
                FILE_ATTRIBUTE_NORMAL,
                None
            )
            if hPort != -1 and hPort != 0:
                break
            err = kernel32.GetLastError()
            if err in (5, 32, 121) and intento < 2:
                time.sleep(0.35)
                continue
            break

        if hPort == -1 or hPort == 0:
            _CACHE_ESTADO_CONEXION[puerto_limpio] = {"conectada": False, "timestamp": time.time()}
            if err == 121:  # ERROR_SEM_TIMEOUT
                return False, (
                    f"Tiempo de espera agotado al conectar con {puerto_limpio} (Bluetooth). "
                    "Verifique que la impresora MP80-12 esté encendida, con batería y dentro del alcance."
                )
            elif err == 2:  # ERROR_FILE_NOT_FOUND
                return False, (
                    f"El puerto {puerto_limpio} no está disponible. "
                    "Verifique que el dispositivo Bluetooth esté emparejado o el cable conectado."
                )
            elif err in (5, 32):  # ERROR_ACCESS_DENIED / ERROR_SHARING_VIOLATION
                return False, (
                    f"Acceso denegado a {puerto_limpio}. El puerto puede estar ocupado por otro programa o liberándose."
                )
            return False, f"Error al abrir puerto {puerto_limpio} (Código Windows {err})."

        try:
            # Configurar timeouts
            class COMMTIMEOUTS(ctypes.Structure):
                _fields_ = [
                    ("ReadIntervalTimeout", wintypes.DWORD),
                    ("ReadTotalTimeoutMultiplier", wintypes.DWORD),
                    ("ReadTotalTimeoutConstant", wintypes.DWORD),
                    ("WriteTotalTimeoutMultiplier", wintypes.DWORD),
                    ("WriteTotalTimeoutConstant", wintypes.DWORD),
                ]

            timeouts = COMMTIMEOUTS(0, 0, 1000, 0, timeout_ms)
            kernel32.SetCommTimeouts(hPort, ctypes.byref(timeouts))

            # Configurar parámetros serie (9600 8-N-1)
            class DCB(ctypes.Structure):
                _fields_ = [("DCBlength", wintypes.DWORD), ("raw", ctypes.c_byte * 128)]

            dcb = DCB()
            dcb.DCBlength = ctypes.sizeof(DCB)
            if kernel32.BuildCommDCBW("baud=9600 parity=N data=8 stop=1", ctypes.byref(dcb)):
                kernel32.SetCommState(hPort, ctypes.byref(dcb))

            # Escribir datos
            escritos = wintypes.DWORD(0)
            datos_buf = ctypes.create_string_buffer(datos)
            ok = kernel32.WriteFile(hPort, datos_buf, len(datos), ctypes.byref(escritos), None)

            if not ok or escritos.value == 0:
                err = kernel32.GetLastError()
                return False, f"Fallo al transmitir datos a {puerto_limpio} (Error Windows: {err})."

            kernel32.FlushFileBuffers(hPort)
            _CACHE_ESTADO_CONEXION[puerto_limpio] = {"conectada": True, "timestamp": time.time()}
            return True, f"Ticket enviado con éxito a '{puerto_limpio}' ({escritos.value} bytes transmitidos)."

        finally:
            kernel32.CloseHandle(hPort)
            # Pequeña pausa para que Windows RFCOMM/Bluetooth libere el handle en el kernel antes de la siguiente operación
            time.sleep(0.15)


def enviar_datos_crudos_usb(
    identificador_o_ruta: str,
    datos: bytes
) -> Tuple[bool, str]:
    """Envía una secuencia de bytes crudos (ESC/POS) directamente a la impresora térmica USB (usbprint.sys)."""
    if not datos:
        return False, "No hay datos para enviar a la impresora."

    sistema = platform.system()
    if sistema != "Windows":
        return False, "Impresión directa por USB solo implementada para Windows."

    # Resolver la ruta de dispositivo si nos pasaron un nombre amigable
    ruta_dispositivo = identificador_o_ruta
    if not ruta_dispositivo.startswith("\\\\?\\"):
        dispositivos = listar_dispositivos_usb_impresora(forzar_verificacion=False)
        matched = None
        for d in dispositivos:
            if d["nombre"].lower() == identificador_o_ruta.lower():
                matched = d["ruta_usb"]
                break
        if not matched and dispositivos:
            for d in dispositivos:
                if identificador_o_ruta.lower() in d["nombre"].lower() or d["nombre"].lower() in identificador_o_ruta.lower():
                    matched = d["ruta_usb"]
                    break
        if not matched and dispositivos:
            matched = dispositivos[0]["ruta_usb"]

        if not matched:
            return False, f"No se encontró el dispositivo USB '{identificador_o_ruta}'. Verifique la conexión del cable."
        ruta_dispositivo = matched

    kernel32 = ctypes.windll.kernel32
    GENERIC_WRITE = 0x40000000
    OPEN_EXISTING = 3
    FILE_ATTRIBUTE_NORMAL = 0x80

    with _USB_PORT_LOCK:
        h = kernel32.CreateFileW(
            ruta_dispositivo,
            GENERIC_WRITE,
            0,
            None,
            OPEN_EXISTING,
            FILE_ATTRIBUTE_NORMAL,
            None
        )
        if h == -1 or h == 0:
            err = kernel32.GetLastError()
            _CACHE_ESTADO_CONEXION[ruta_dispositivo] = {"conectada": False, "timestamp": time.time()}
            _CACHE_ESTADO_CONEXION[identificador_o_ruta] = {"conectada": False, "timestamp": time.time()}
            return False, f"No se pudo abrir la impresora USB (Error Windows: {err}). Verifique que esté encendida."

        try:
            escritos = wintypes.DWORD(0)
            datos_buf = ctypes.create_string_buffer(datos)
            ok = kernel32.WriteFile(h, datos_buf, len(datos), ctypes.byref(escritos), None)
            if not ok or escritos.value == 0:
                err = kernel32.GetLastError()
                return False, f"Fallo al transmitir datos a la impresora USB (Error Windows: {err})."

            kernel32.FlushFileBuffers(h)
            _CACHE_ESTADO_CONEXION[ruta_dispositivo] = {"conectada": True, "timestamp": time.time()}
            _CACHE_ESTADO_CONEXION[identificador_o_ruta] = {"conectada": True, "timestamp": time.time()}
            return True, f"Ticket enviado con éxito a la impresora USB ({escritos.value} bytes transmitidos)."
        finally:
            kernel32.CloseHandle(h)
            time.sleep(0.05)


def enviar_datos_crudos_impresora(
    nombre_impresora: str,
    datos: bytes,
    nombre_documento: str = "Ticket de Venta"
) -> Tuple[bool, str]:
    """Envía una secuencia de bytes crudos a la impresora térmica (vía USB, COM/Bluetooth o Spooler de Windows)."""
    if not datos:
        return False, "No hay datos para enviar a la impresora."

    # Si es una impresora USB directa (ej. 'USB: SUPERRISC S31 (MP80-12)')
    if (nombre_impresora or "").upper().startswith("USB:") or r"\USB#" in (nombre_impresora or "").upper():
        return enviar_datos_crudos_usb(nombre_impresora, datos)

    # Si el nombre corresponde a un puerto COM (ej: 'COM5' o 'COM5 (MP80-12 Bluetooth)')
    if re.search(r"\bCOM\d+\b", (nombre_impresora or "").upper()):
        return enviar_datos_crudos_com(nombre_impresora, datos)

    sistema = platform.system()
    if sistema == "Windows":
        try:
            winspool = ctypes.WinDLL("winspool.drv")

            # Configurar firmas de funciones winspool
            winspool.OpenPrinterW.argtypes = [wintypes.LPWSTR, ctypes.POINTER(wintypes.HANDLE), ctypes.c_void_p]
            winspool.OpenPrinterW.restype = wintypes.BOOL

            winspool.StartDocPrinterW.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(DOC_INFO_1)]
            winspool.StartDocPrinterW.restype = wintypes.DWORD

            winspool.StartPagePrinter.argtypes = [wintypes.HANDLE]
            winspool.StartPagePrinter.restype = wintypes.BOOL

            winspool.WritePrinter.argtypes = [
                wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)
            ]
            winspool.WritePrinter.restype = wintypes.BOOL

            winspool.EndPagePrinter.argtypes = [wintypes.HANDLE]
            winspool.EndPagePrinter.restype = wintypes.BOOL

            winspool.EndDocPrinter.argtypes = [wintypes.HANDLE]
            winspool.EndDocPrinter.restype = wintypes.BOOL

            winspool.ClosePrinter.argtypes = [wintypes.HANDLE]
            winspool.ClosePrinter.restype = wintypes.BOOL

            hPrinter = wintypes.HANDLE()
            if not winspool.OpenPrinterW(nombre_impresora, ctypes.byref(hPrinter), None):
                err = ctypes.GetLastError()
                return False, f"No se pudo abrir la impresora '{nombre_impresora}' (Código Windows: {err}). Verifique que esté conectada y encendida."

            try:
                doc_info = DOC_INFO_1()
                doc_info.pDocName = nombre_documento
                doc_info.pOutputFile = None
                doc_info.pDatatype = "RAW"

                job_id = winspool.StartDocPrinterW(hPrinter, 1, ctypes.byref(doc_info))
                if job_id == 0:
                    err = ctypes.GetLastError()
                    return False, f"No se pudo iniciar el trabajo de impresión en '{nombre_impresora}' (Error: {err})."

                try:
                    winspool.StartPagePrinter(hPrinter)
                    escritos = wintypes.DWORD(0)
                    datos_buf = ctypes.create_string_buffer(datos)
                    ok_write = winspool.WritePrinter(
                        hPrinter, datos_buf, len(datos), ctypes.byref(escritos)
                    )
                    winspool.EndPagePrinter(hPrinter)
                    if not ok_write or escritos.value == 0:
                        return False, "Error al escribir los datos en la impresora térmica."
                finally:
                    winspool.EndDocPrinter(hPrinter)

            finally:
                winspool.ClosePrinter(hPrinter)

            return True, f"Ticket enviado con éxito a '{nombre_impresora}'."

        except Exception as ex:
            return False, f"Excepción al imprimir en '{nombre_impresora}': {ex}"

    elif sistema in ("Linux", "Darwin"):
        try:
            proceso = subprocess.Popen(
                ["lpr", "-P", nombre_impresora, "-l"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            stdout, stderr = proceso.communicate(input=datos)
            if proceso.returncode == 0:
                return True, f"Ticket enviado con éxito a '{nombre_impresora}'."
            return False, f"Error al enviar a lp/lpr: {stderr.decode(errors='ignore')}"
        except Exception as ex:
            return False, f"Error en sistema Unix: {ex}"

    return False, f"Plataforma '{sistema}' no soportada para impresión directa RAW."


def imprimir_ticket_termico(
    venta_id: int,
    divisa: str = "USD",
    nombre_impresora: Optional[str] = None
) -> Tuple[bool, str]:
    """Imprime el ticket de venta en la impresora térmica configurada o detectada.
    
    Retorna (True, mensaje_exito) o (False, mensaje_error).
    """
    impresora_target = (nombre_impresora or "").strip()
    if not impresora_target:
        det = detectar_impresora_termica(verificar_online=False)
        if not det:
            return False, "No se detectó ninguna impresora térmica conectada en el sistema."
        impresora_target = det["nombre"]

    # Generar comandos ESC/POS
    try:
        escpos_bytes = generar_comandos_escpos(venta_id, divisa=divisa)
    except Exception as ex:
        return False, f"Error al preparar el ticket para impresión: {ex}"

    # Despachar al spooler
    return enviar_datos_crudos_impresora(
        nombre_impresora=impresora_target,
        datos=escpos_bytes,
        nombre_documento=f"Ticket Venta {venta_id:06d}"
    )


def imprimir_ticket_prueba(nombre_impresora: Optional[str] = None) -> Tuple[bool, str]:
    """Imprime un ticket de prueba corto para verificar la conexión y el avance de papel."""
    impresora_target = (nombre_impresora or "").strip()
    if not impresora_target:
        det = detectar_impresora_termica(verificar_online=False)
        if not det:
            return False, "No se detectó ninguna impresora térmica conectada."
        impresora_target = det["nombre"]

    ESC = b"\x1b"
    GS = b"\x1d"
    buffer = bytearray()
    buffer.extend(ESC + b"@")
    buffer.extend(ESC + b"a\x01")  # centrado
    buffer.extend(ESC + b"!\x30")  # doble ancho y alto
    buffer.extend(b"PRUEBA DE IMPRESION\n")
    buffer.extend(ESC + b"!\x00")  # normal
    buffer.extend(b"------------------------------------------------\n")
    buffer.extend(b"Impresora Termica: MP80-12 / 80mm\n")
    buffer.extend(b"Protocolo: ESC/POS - 48 Columnas\n")
    buffer.extend(f"Dispositivo: {impresora_target}\n".encode("cp437", errors="ignore"))
    buffer.extend(b"Estado: COMUNICACION CORRECTA\n")
    buffer.extend(b"------------------------------------------------\n")
    buffer.extend(b"Sistema Integrado de Inventario y Ventas\n")
    buffer.extend(b"\n\n\n\n\n")
    buffer.extend(GS + b"V\x41\x03")

    return enviar_datos_crudos_impresora(
        nombre_impresora=impresora_target,
        datos=bytes(buffer),
        nombre_documento="Prueba de Impresion Termica"
    )


def generar_comandos_reporte_ventas_diarias(ventas: Optional[List[dict]] = None) -> bytes:
    """Genera comandos ESC/POS para el reporte de cierre / ventas del día (80mm / 48 columnas)."""
    if ventas is None:
        from services.reportes_service import obtener_ventas_del_dia
        ventas = obtener_ventas_del_dia()

    ESC = b"\x1b"
    GS = b"\x1d"
    ALIGN_LEFT = ESC + b"a\x00"
    ALIGN_CENTER = ESC + b"a\x01"
    BOLD_ON = ESC + b"E\x01"
    BOLD_OFF = ESC + b"E\x00"
    DOUBLE_HEIGHT = ESC + b"!\x10"
    NORMAL_SIZE = ESC + b"!\x00"

    buffer = bytearray()
    buffer.extend(ESC + b"@")
    buffer.extend(ALIGN_CENTER)
    buffer.extend(BOLD_ON)
    buffer.extend(DOUBLE_HEIGHT)
    buffer.extend(b"VENTAS DEL DIA / CIERRE\n")
    buffer.extend(NORMAL_SIZE)
    buffer.extend(BOLD_OFF)
    buffer.extend(b"SISTEMA INTEGRADO DE VENTAS\n")
    
    fecha_emision = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    buffer.extend(f"Emision: {fecha_emision}\n".encode("cp437", errors="ignore"))
    buffer.extend(b"------------------------------------------------\n")

    if not ventas:
        buffer.extend(ALIGN_CENTER)
        buffer.extend(b"\nNo se registraron ventas hoy.\n\n")
        buffer.extend(b"------------------------------------------------\n")
        buffer.extend(b"\n\n\n\n\n")
        buffer.extend(GS + b"V\x41\x03")
        return bytes(buffer)

    total_operaciones = len(ventas)
    totales_por_metodo: Dict[str, Dict[str, float]] = {}
    total_usd_general = 0.0
    total_bs_general = 0.0

    for v in ventas:
        monto = float(v.get("monto_total") or v.get("monto_cobrado") or v.get("total_usd") or 0.0)
        moneda = v.get("moneda", "USD")
        metodo = v.get("metodo_pago", "Efectivo")

        if metodo not in totales_por_metodo:
            totales_por_metodo[metodo] = {"cantidad": 0, "monto_usd": 0.0, "monto_bs": 0.0}

        totales_por_metodo[metodo]["cantidad"] += 1
        if moneda == "Bs":
            totales_por_metodo[metodo]["monto_bs"] += monto
            total_bs_general += monto
        else:
            totales_por_metodo[metodo]["monto_usd"] += monto
            total_usd_general += monto

    buffer.extend(ALIGN_LEFT)
    buffer.extend(BOLD_ON)
    buffer.extend(b"RESUMEN GENERAL DEL DIA:\n")
    buffer.extend(BOLD_OFF)
    buffer.extend(f"Total Operaciones: {total_operaciones} ventas\n".encode("cp437", errors="ignore"))
    if total_usd_general > 0:
        buffer.extend(f"Total en Divisas ($):    $ {total_usd_general:,.2f}\n".encode("cp437", errors="ignore"))
    if total_bs_general > 0:
        buffer.extend(f"Total en Bolivares (Bs): Bs. {total_bs_general:,.2f}\n".encode("cp437", errors="ignore"))
    buffer.extend(b"------------------------------------------------\n")

    buffer.extend(BOLD_ON)
    buffer.extend(b"DESGLOSE POR METODO DE PAGO:\n")
    buffer.extend(BOLD_OFF)
    for metodo, info in totales_por_metodo.items():
        cant = info["cantidad"]
        txt_monto = ""
        if info["monto_usd"] > 0:
            txt_monto += f"$ {info['monto_usd']:,.2f} "
        if info["monto_bs"] > 0:
            txt_monto += f"Bs. {info['monto_bs']:,.2f}"
        linea = f"  * {metodo.ljust(18)} ({cant:2d}) {txt_monto.rjust(20)}\n"
        buffer.extend(_limpiar_texto_impresora(linea).encode("cp437", errors="ignore"))

    buffer.extend(b"------------------------------------------------\n")
    buffer.extend(BOLD_ON)
    buffer.extend(b"LISTA DE OPERACIONES:\n")
    buffer.extend(b"HORA   ID       METODO                  TOTAL\n")
    buffer.extend(BOLD_OFF)
    buffer.extend(b"------------------------------------------------\n")

    for v in ventas:
        hora = str(v.get("fecha_hora") or v.get("fecha") or "")[-5:]
        vid = f"#{v.get('venta_id') or v.get('id') or 0:05d}"
        met = str(v.get("metodo_pago") or "")[:14]
        simb = "Bs." if v.get("moneda") == "Bs" else "$"
        monto_val = float(v.get("monto_total") or v.get("monto_cobrado") or v.get("total_usd") or 0.0)
        monto_str = f"{simb} {monto_val:,.2f}"
        linea = f"{hora}  {vid}  {met.ljust(14)} {monto_str.rjust(16)}\n"
        buffer.extend(_limpiar_texto_impresora(linea).encode("cp437", errors="ignore"))

    buffer.extend(b"------------------------------------------------\n")
    buffer.extend(ALIGN_CENTER)
    buffer.extend(b"*** FIN DEL REPORTE DE VENTAS ***\n")
    buffer.extend(b"\n\n\n\n\n")
    buffer.extend(GS + b"V\x41\x03")

    return bytes(buffer)


def imprimir_reporte_ventas_diarias(
    ventas: Optional[List[dict]] = None,
    nombre_impresora: Optional[str] = None
) -> Tuple[bool, str]:
    """Imprime el reporte de cierre o ventas diarias en la impresora térmica de 80mm."""
    impresora_target = (nombre_impresora or "").strip()
    if not impresora_target:
        det = detectar_impresora_termica(verificar_online=False)
        if not det:
            return False, "No se detectó ninguna impresora térmica conectada."
        impresora_target = det["nombre"]

    try:
        datos = generar_comandos_reporte_ventas_diarias(ventas=ventas)
    except Exception as ex:
        return False, f"Error al generar reporte de ventas del día: {ex}"

    return enviar_datos_crudos_impresora(
        nombre_impresora=impresora_target,
        datos=datos,
        nombre_documento="Reporte Ventas Diarias"
    )


def generar_comandos_reporte_auditoria(
    stock_minimo: Optional[float] = None,
    alertas: Optional[List[dict]] = None,
) -> bytes:
    """Genera comandos ESC/POS para la auditoría preventiva de stock crítico/faltante (80mm)."""
    from services.reportes_service import obtener_alertas_stock, obtener_stock_minimo
    min_val = stock_minimo if stock_minimo is not None else obtener_stock_minimo()
    if alertas is None:
        alertas = obtener_alertas_stock(min_val)

    ESC = b"\x1b"
    GS = b"\x1d"
    ALIGN_LEFT = ESC + b"a\x00"
    ALIGN_CENTER = ESC + b"a\x01"
    BOLD_ON = ESC + b"E\x01"
    BOLD_OFF = ESC + b"E\x00"
    DOUBLE_HEIGHT = ESC + b"!\x10"
    NORMAL_SIZE = ESC + b"!\x00"

    buffer = bytearray()
    buffer.extend(ESC + b"@")
    buffer.extend(ALIGN_CENTER)
    buffer.extend(BOLD_ON)
    buffer.extend(DOUBLE_HEIGHT)
    buffer.extend(b"AUDITORIA PREVENTIVA\n")
    buffer.extend(NORMAL_SIZE)
    buffer.extend(b"STOCK CRITICO / REPOSICION\n")
    buffer.extend(BOLD_OFF)
    
    fecha_emision = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    buffer.extend(f"Emision: {fecha_emision}\n".encode("cp437", errors="ignore"))
    buffer.extend(f"Parametro Stock Minimo: < {min_val:.0f} unid.\n".encode("cp437", errors="ignore"))
    buffer.extend(b"------------------------------------------------\n")

    if not alertas:
        buffer.extend(ALIGN_CENTER)
        buffer.extend(b"\nNo hay productos en estado critico.\nInventario en niveles optimos.\n\n")
        buffer.extend(b"------------------------------------------------\n")
        buffer.extend(b"\n\n\n\n\n")
        buffer.extend(GS + b"V\x41\x03")
        return bytes(buffer)

    buffer.extend(ALIGN_LEFT)
    buffer.extend(BOLD_ON)
    buffer.extend(b"CODIGO    DESCRIPCION CORTA        ACT / MIN\n")
    buffer.extend(BOLD_OFF)
    buffer.extend(b"------------------------------------------------\n")

    for a in alertas:
        codigo = str(a.get("codigo") or "")[:9].ljust(9)
        nombre = str(a.get("nombre_corto") or a.get("descripcion_general") or a.get("descripcion") or "")[:23].ljust(23)
        exist = f"{float(a.get('existencia') or 0):.0f}"
        minimo = f"{float(a.get('minimo') or min_val):.0f}"
        cantidades = f"{exist} / {minimo}".rjust(12)
        linea = f"{codigo} {nombre} {cantidades}\n"
        buffer.extend(_limpiar_texto_impresora(linea).encode("cp437", errors="ignore"))

        prov = a.get("proveedor_nombre") or a.get("proveedor")
        tel = a.get("proveedor_telefono") or a.get("contacto")
        if prov:
            sub = f"  Prov: {prov}" + (f" ({tel})" if tel else "")
            buffer.extend(_limpiar_texto_impresora(f"{sub[:46]}\n").encode("cp437", errors="ignore"))

    buffer.extend(b"------------------------------------------------\n")
    buffer.extend(BOLD_ON)
    buffer.extend(f"Total Articulos Criticos: {len(alertas)}\n".encode("cp437", errors="ignore"))
    buffer.extend(BOLD_OFF)
    buffer.extend(ALIGN_CENTER)
    buffer.extend(b"*** FIN DE AUDITORIA PREVENTIVA ***\n")
    buffer.extend(b"\n\n\n\n\n")
    buffer.extend(GS + b"V\x41\x03")

    return bytes(buffer)


def imprimir_reporte_auditoria(
    stock_minimo: Optional[float] = None,
    alertas: Optional[List[dict]] = None,
    nombre_impresora: Optional[str] = None,
) -> Tuple[bool, str]:
    """Imprime el reporte de auditoría preventiva / stock crítico en la impresora térmica de 80mm."""
    impresora_target = (nombre_impresora or "").strip()
    if not impresora_target:
        det = detectar_impresora_termica(verificar_online=False)
        if not det:
            return False, "No se detectó ninguna impresora térmica conectada."
        impresora_target = det["nombre"]

    try:
        datos = generar_comandos_reporte_auditoria(stock_minimo=stock_minimo, alertas=alertas)
    except Exception as ex:
        return False, f"Error al generar reporte de auditoría preventiva: {ex}"

    return enviar_datos_crudos_impresora(
        nombre_impresora=impresora_target,
        datos=datos,
        nombre_documento="Auditoria Preventiva Termica"
    )


def generar_comandos_reporte_inventario(
    departamento: Optional[str] = None,
    limite: int = 150,
    productos: Optional[List[dict]] = None,
) -> bytes:
    """Genera comandos ESC/POS de catálogo resumido de productos para 80mm."""
    if productos is None:
        conn = get_connection()
        cursor = conn.cursor()

        if departamento:
            cursor.execute("""
                SELECT codigo, nombre_referencia_corto, descripcion_general, existencia, precio_dolares
                FROM productos
                WHERE departamento = ?
                ORDER BY codigo
                LIMIT ?
            """, (departamento, limite))
        else:
            cursor.execute("""
                SELECT codigo, nombre_referencia_corto, descripcion_general, existencia, precio_dolares
                FROM productos
                ORDER BY departamento, codigo
                LIMIT ?
            """, (limite,))
        productos = cursor.fetchall()

    ESC = b"\x1b"
    GS = b"\x1d"
    ALIGN_LEFT = ESC + b"a\x00"
    ALIGN_CENTER = ESC + b"a\x01"
    BOLD_ON = ESC + b"E\x01"
    BOLD_OFF = ESC + b"E\x00"
    DOUBLE_HEIGHT = ESC + b"!\x10"
    NORMAL_SIZE = ESC + b"!\x00"

    buffer = bytearray()
    buffer.extend(ESC + b"@")
    buffer.extend(ALIGN_CENTER)
    buffer.extend(BOLD_ON)
    buffer.extend(DOUBLE_HEIGHT)
    buffer.extend(b"INVENTARIO RESUMIDO\n")
    buffer.extend(NORMAL_SIZE)
    if departamento:
        buffer.extend(f"Depto: {departamento}\n".encode("cp437", errors="ignore"))
    buffer.extend(BOLD_OFF)

    fecha_emision = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
    buffer.extend(f"Emision: {fecha_emision}\n".encode("cp437", errors="ignore"))
    buffer.extend(b"------------------------------------------------\n")
    buffer.extend(ALIGN_LEFT)
    buffer.extend(BOLD_ON)
    buffer.extend(b"CANT  CODIGO    DESCRIPCION               P.USD\n")
    buffer.extend(BOLD_OFF)
    buffer.extend(b"------------------------------------------------\n")

    for p in productos:
        cod = str(p.get("codigo", "") or "")[:9].ljust(9)
        nom = str(p.get("nombre_referencia_corto") or p.get("descripcion_general") or "")[:22].ljust(22)
        cant = f"{float(p.get('existencia') or 0):.0f}".rjust(4)
        precio = f"${float(p.get('precio_dolares') or 0):,.2f}".rjust(9)
        linea = f"{cant}  {cod} {nom} {precio}\n"
        buffer.extend(_limpiar_texto_impresora(linea).encode("cp437", errors="ignore"))

    buffer.extend(b"------------------------------------------------\n")
    buffer.extend(BOLD_ON)
    buffer.extend(f"Total productos listados: {len(productos)}\n".encode("cp437", errors="ignore"))
    buffer.extend(BOLD_OFF)
    buffer.extend(ALIGN_CENTER)
    buffer.extend(b"*** FIN DE INVENTARIO RESUMIDO ***\n")
    buffer.extend(b"\n\n\n\n\n")
    buffer.extend(GS + b"V\x41\x03")

    return bytes(buffer)


def imprimir_reporte_inventario(
    departamento: Optional[str] = None,
    limite: int = 150,
    productos: Optional[List[dict]] = None,
    nombre_impresora: Optional[str] = None,
) -> Tuple[bool, str]:
    """Imprime el catálogo resumido de inventario en la impresora térmica de 80mm."""
    impresora_target = (nombre_impresora or "").strip()
    if not impresora_target:
        det = detectar_impresora_termica(verificar_online=False)
        if not det:
            return False, "No se detectó ninguna impresora térmica conectada."
        impresora_target = det["nombre"]

    try:
        datos = generar_comandos_reporte_inventario(
            departamento=departamento,
            limite=limite,
            productos=productos,
        )
    except Exception as ex:
        return False, f"Error al generar reporte de inventario: {ex}"

    return enviar_datos_crudos_impresora(
        nombre_impresora=impresora_target,
        datos=datos,
        nombre_documento="Catalogo Inventario Termica"
    )


def generar_comandos_reporte_clientes(
    limite: int = 60,
    clientes: Optional[List[dict]] = None,
) -> bytes:
    """Genera comandos ESC/POS de cartera resumida de clientes para 80mm."""
    if clientes is None:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT cedula_rif, nombre, telefono
            FROM clientes
            ORDER BY nombre
            LIMIT ?
        """, (limite,))
        clientes = cursor.fetchall()

    ESC = b"\x1b"
    GS = b"\x1d"
    ALIGN_LEFT = ESC + b"a\x00"
    ALIGN_CENTER = ESC + b"a\x01"
    BOLD_ON = ESC + b"E\x01"
    BOLD_OFF = ESC + b"E\x00"
    DOUBLE_HEIGHT = ESC + b"!\x10"
    NORMAL_SIZE = ESC + b"!\x00"

    buffer = bytearray()
    buffer.extend(ESC + b"@")
    buffer.extend(ALIGN_CENTER)
    buffer.extend(BOLD_ON)
    buffer.extend(DOUBLE_HEIGHT)
    buffer.extend(b"DIRECTORIO DE CLIENTES\n")
    buffer.extend(NORMAL_SIZE)
    buffer.extend(BOLD_OFF)

    fecha_emision = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
    buffer.extend(f"Emision: {fecha_emision}\n".encode("cp437", errors="ignore"))
    buffer.extend(b"------------------------------------------------\n")
    buffer.extend(ALIGN_LEFT)
    buffer.extend(BOLD_ON)
    buffer.extend(b"CEDULA/RIF    NOMBRE                   TELEFONO\n")
    buffer.extend(BOLD_OFF)
    buffer.extend(b"------------------------------------------------\n")

    for c in clientes:
        doc = str(c.get("cedula_rif", "") or "")[:12].ljust(12)
        nom = str(c.get("nombre", "") or "")[:20].ljust(20)
        tel = str(c.get("telefono", "") or "-")[:12].rjust(14)
        linea = f"{doc}  {nom} {tel}\n"
        buffer.extend(_limpiar_texto_impresora(linea).encode("cp437", errors="ignore"))

    buffer.extend(b"------------------------------------------------\n")
    buffer.extend(BOLD_ON)
    buffer.extend(f"Total clientes listados: {len(clientes)}\n".encode("cp437", errors="ignore"))
    buffer.extend(BOLD_OFF)
    buffer.extend(ALIGN_CENTER)
    buffer.extend(b"*** FIN DE DIRECTORIO DE CLIENTES ***\n")
    buffer.extend(b"\n\n\n\n\n")
    buffer.extend(GS + b"V\x41\x03")

    return bytes(buffer)


def imprimir_reporte_clientes(
    limite: int = 60,
    clientes: Optional[List[dict]] = None,
    nombre_impresora: Optional[str] = None,
) -> Tuple[bool, str]:
    """Imprime la lista resumida de clientes en la impresora térmica de 80mm."""
    impresora_target = (nombre_impresora or "").strip()
    if not impresora_target:
        det = detectar_impresora_termica(verificar_online=False)
        if not det:
            return False, "No se detectó ninguna impresora térmica conectada."
        impresora_target = det["nombre"]

    try:
        datos = generar_comandos_reporte_clientes(limite=limite, clientes=clientes)
    except Exception as ex:
        return False, f"Error al generar reporte de clientes: {ex}"

    return enviar_datos_crudos_impresora(
        nombre_impresora=impresora_target,
        datos=datos,
        nombre_documento="Directorio Clientes Termica"
    )

