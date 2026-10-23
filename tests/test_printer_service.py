"""Pruebas unitarias para el servicio de impresión térmica (printer_service.py).

Verifica:
- Listado y detección de impresoras térmicas (palabras clave y configuración manual).
- Generación de comandos binarios ESC/POS para papel de 80mm (MP80-12).
- Comprobación de estado de conexión (en línea vs fuera de línea).
- Impresión de ticket de prueba y manejo de contingencia.
"""
import pytest
from unittest.mock import patch, MagicMock

from core.database import get_connection, set_setting
from services.printer_service import (
    listar_impresoras_sistema,
    detectar_impresora_termica,
    esta_impresora_conectada,
    obtener_impresora_termica_configurada,
    guardar_impresora_termica_configurada,
    generar_comandos_escpos,
    imprimir_ticket_prueba,
    CLAVE_IMPRESORA_TERMICA,
)


@pytest.fixture
def venta_de_prueba():
    """Crea una venta formal con items en la base de datos para pruebas."""
    with get_connection() as conn:
        cursor = conn.cursor()
        # Asegurar cliente
        cursor.execute("""
            INSERT OR REPLACE INTO clientes (cedula_rif, nombre, telefono, direccion)
            VALUES ('V-12345678', 'Juan Pérez', '0414-1234567', 'Calle Comercio 123')
        """)
        # Asegurar producto
        cursor.execute("""
            INSERT OR REPLACE INTO productos (
                codigo, referencia, departamento, descripcion_general,
                precio_dolares, precio_bcv, existencia, nombre_referencia_corto
            ) VALUES (
                'PROD-001', 'F-ACEITE', 'General', 'Filtro de aceite automotriz',
                10.0, 400.0, 50, 'Filtro Aceite Ref'
            )
        """)
        # Insertar venta
        cursor.execute("""
            INSERT INTO ventas (
                tipo_venta, cliente_id, total_usd, total_bcv, metodo_pago,
                referencia_pago, referencia_omitida, monto_cobrado,
                porcentaje_descuento, usuario_nombre, fecha
            ) VALUES (
                'Formal', 'V-12345678', 20.0, 800.0, 'Transferencia',
                'REF-9999', 0, 20.0, 0, 'admin', '2026-10-23 12:00:00'
            )
        """)
        venta_id = cursor.lastrowid
        cursor.execute("""
            INSERT INTO ventas_detalle (
                venta_id, producto_codigo, cantidad, precio_unitario_usd,
                precio_unitario_bcv, subtotal_usd, subtotal_bcv
            ) VALUES (
                ?, 'PROD-001', 2.0, 10.0, 400.0, 20.0, 800.0
            )
        """, (venta_id,))
        conn.commit()

    return venta_id


def test_guardar_y_obtener_impresora_configurada():
    """Verifica la persistencia de la impresora térmica en app_settings."""
    guardar_impresora_termica_configurada("POS-80 Impresora")
    assert obtener_impresora_termica_configurada() == "POS-80 Impresora"

    guardar_impresora_termica_configurada("")
    assert obtener_impresora_termica_configurada() == ""


def test_detectar_impresora_por_palabra_clave():
    """Detecta automáticamente si hay una impresora con 'MP80' o 'POS-80'."""
    set_setting(CLAVE_IMPRESORA_TERMICA, "")
    impresoras_falsas = [
        {"nombre": "Microsoft Print to PDF", "is_default": True, "is_offline": False},
        {"nombre": "Mini Impresora MP80-12", "is_default": False, "is_offline": False},
    ]

    with patch("services.printer_service.listar_impresoras_sistema", return_value=impresoras_falsas):
        det = detectar_impresora_termica()
        assert det is not None
        assert det["nombre"] == "Mini Impresora MP80-12"
        assert det["conectada"] is True


def test_detectar_impresora_configurada_manualmente():
    """Si el usuario seleccionó una impresora específica, tiene prioridad sobre la búsqueda."""
    set_setting(CLAVE_IMPRESORA_TERMICA, "Impresora Mostrador")
    impresoras_falsas = [
        {"nombre": "POS-80", "is_default": False, "is_offline": False},
        {"nombre": "Impresora Mostrador", "is_default": True, "is_offline": False},
    ]

    with patch("services.printer_service.listar_impresoras_sistema", return_value=impresoras_falsas):
        det = detectar_impresora_termica()
        assert det is not None
        assert det["nombre"] == "Impresora Mostrador"
        assert det["configurada_manualmente"] is True


def test_detectar_impresora_no_encontrada():
    """Si no hay impresoras térmicas ni configuradas, devuelve None."""
    set_setting(CLAVE_IMPRESORA_TERMICA, "")
    impresoras_falsas = [
        {"nombre": "OneNote (Desktop)", "is_default": False, "is_offline": False},
        {"nombre": "Microsoft Print to PDF", "is_default": True, "is_offline": False},
    ]

    with patch("services.printer_service.listar_impresoras_sistema", return_value=impresoras_falsas):
        det = detectar_impresora_termica()
        assert det is None


def test_esta_impresora_conectada():
    """Verifica que identifique si una impresora está fuera de línea."""
    impresoras_falsas = [
        {"nombre": "MP80-12", "is_default": False, "is_offline": True},
        {"nombre": "POS-80", "is_default": False, "is_offline": False},
    ]

    with patch("services.printer_service.listar_impresoras_sistema", return_value=impresoras_falsas):
        assert esta_impresora_conectada("MP80-12") is False
        assert esta_impresora_conectada("POS-80") is True


def test_generar_comandos_escpos_para_venta(venta_de_prueba):
    """Verifica que el generador ESC/POS produzca una secuencia binaria válida con los datos."""
    bytes_ticket = generar_comandos_escpos(venta_de_prueba, divisa="USD")

    assert isinstance(bytes_ticket, bytes)
    assert len(bytes_ticket) > 100

    # Comprobar inicialización ESC @ (\x1b@)
    assert b"\x1b@" in bytes_ticket
    # Comprobar datos del encabezado
    assert b"SISTEMA INTEGRADO DE VENTAS" in bytes_ticket
    assert b"COMPROBANTE / NOTA DE ENTREGA" in bytes_ticket
    # Comprobar datos de la venta y cliente
    assert f"{venta_de_prueba:06d}".encode() in bytes_ticket
    assert b"Juan Perez" in bytes_ticket or b"Juan P" in bytes_ticket
    assert b"V-12345678" in bytes_ticket
    # Comprobar producto (nombre_referencia_corto)
    assert b"Filtro Aceite Ref" in bytes_ticket
    # Comprobar totales y corte de papel (\x1dV\x41\x03)
    assert b"TOTAL USD: $ 20.00" in bytes_ticket
    assert b"\x1dV\x41\x03" in bytes_ticket


def test_generar_comandos_escpos_divisa_bcv(venta_de_prueba):
    """Verifica la generación de comandos en bolívares BCV."""
    bytes_ticket = generar_comandos_escpos(venta_de_prueba, divisa="BCV")
    assert b"TOTAL BCV: Bs. 800.00" in bytes_ticket


def test_imprimir_ticket_prueba_sin_impresora():
    """Si no hay impresora térmica configurada ni detectada, retorna error amigable."""
    set_setting(CLAVE_IMPRESORA_TERMICA, "")
    with patch("services.printer_service.listar_impresoras_sistema", return_value=[]):
        ok, msg = imprimir_ticket_prueba()
        assert ok is False
        assert "No se detectó ninguna impresora" in msg


def test_detectar_impresora_puerto_com_bluetooth():
    """Detecta automáticamente una impresora térmica conectada vía puerto COM Bluetooth (MP80-12)."""
    set_setting(CLAVE_IMPRESORA_TERMICA, "")
    impresoras_falsas = [
        {"nombre": "Microsoft Print to PDF", "is_default": True, "is_offline": False, "tipo": "spooler"},
        {"nombre": "COM5 (MP80-12 Bluetooth)", "puerto": "COM5", "is_default": False, "is_offline": False, "tipo": "serial"},
    ]

    with patch("services.printer_service.listar_impresoras_sistema", return_value=impresoras_falsas):
        det = detectar_impresora_termica()
        assert det is not None
        assert det["nombre"] == "COM5 (MP80-12 Bluetooth)"
        assert det["conectada"] is True
        assert det["tipo"] == "serial"
        assert det["puerto"] == "COM5"


def test_esta_impresora_conectada_puerto_com():
    """Verifica el estado de conexión de un puerto COM mediante listar_puertos_com_sistema."""
    puertos_falsos = [
        {"puerto": "COM5", "nombre": "COM5 (MP80-12 Bluetooth)"}
    ]
    with patch("services.printer_service.listar_puertos_com_sistema", return_value=puertos_falsos):
        assert esta_impresora_conectada("COM5") is True
        assert esta_impresora_conectada("COM5 (MP80-12 Bluetooth)") is True
        assert esta_impresora_conectada("COM9") is False


def test_enviar_datos_crudos_com_timeout():
    """Verifica que el error 121 (timeout Bluetooth) entregue un mensaje claro al usuario."""
    from services.printer_service import enviar_datos_crudos_com
    with patch("ctypes.windll.kernel32.CreateFileW", return_value=-1), \
         patch("ctypes.windll.kernel32.GetLastError", return_value=121):
        ok, msg = enviar_datos_crudos_com("COM5", b"test")
        assert ok is False
        assert "Tiempo de espera agotado" in msg
        assert "MP80-12" in msg


def test_generar_comandos_reportes_termicos():
    """Verifica la generación de comandos ESC/POS para los reportes de ventas, auditoría, inventario y clientes."""
    from services.printer_service import (
        generar_comandos_reporte_ventas_diarias,
        generar_comandos_reporte_auditoria,
        generar_comandos_reporte_inventario,
        generar_comandos_reporte_clientes,
    )

    # 1. Reporte de ventas diarias
    ventas = [
        {"id": 1, "tipo_venta": "Formal", "fecha": "2026-10-23 10:00:00", "metodo_pago": "Efectivo", "monto_cobrado": 25.0, "total_usd": 25.0, "total_bcv": 1000.0},
        {"id": 2, "tipo_venta": "Mostrador", "fecha": "2026-10-23 11:30:00", "metodo_pago": "Pago Movil", "monto_cobrado": 15.0, "total_usd": 15.0, "total_bcv": 600.0},
    ]
    datos_ventas = generar_comandos_reporte_ventas_diarias(ventas=ventas)
    assert isinstance(datos_ventas, bytes)
    assert b"VENTAS DEL DIA / CIERRE" in datos_ventas
    assert b"DESGLOSE POR METODO DE PAGO" in datos_ventas
    assert b"Efectivo" in datos_ventas
    assert b"Pago Movil" in datos_ventas

    # 2. Reporte de auditoría preventiva
    alertas = [
        {"codigo": "P-01", "descripcion": "Aceite 20W50", "existencia": 2, "minimo": 10, "departamento": "Lubricantes"}
    ]
    datos_auditoria = generar_comandos_reporte_auditoria(alertas=alertas)
    assert isinstance(datos_auditoria, bytes)
    assert b"AUDITORIA PREVENTIVA" in datos_auditoria
    assert b"STOCK CRITICO / REPOSICION" in datos_auditoria
    assert b"Aceite 20W50" in datos_auditoria

    # 3. Reporte de inventario resumido
    prods = [
        {"codigo": "P-01", "nombre_referencia_corto": "Aceite 20W50", "existencia": 5, "precio_dolares": 7.5}
    ]
    datos_inv = generar_comandos_reporte_inventario(productos=prods)
    assert isinstance(datos_inv, bytes)
    assert b"INVENTARIO RESUMIDO" in datos_inv
    assert b"Aceite 20W50" in datos_inv

    # 4. Reporte de directorio de clientes
    clientes = [
        {"cedula_rif": "V-12345678", "nombre": "Carlos Perez", "telefono": "0414-0000000"}
    ]
    datos_cli = generar_comandos_reporte_clientes(clientes=clientes)
    assert isinstance(datos_cli, bytes)
    assert b"DIRECTORIO DE CLIENTES" in datos_cli
    assert b"Carlos Perez" in datos_cli


