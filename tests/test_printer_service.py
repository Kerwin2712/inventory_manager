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
