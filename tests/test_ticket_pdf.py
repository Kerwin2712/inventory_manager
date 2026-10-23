import os
import re
import pytest

from core.database import get_connection
from services.pdf_service import generar_nota_entrega_pdf, _FORMATOS_PAPEL


@pytest.fixture
def venta_ticket(tmp_path):
    """Crea una venta formal en SQLite para validar el PDF."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO clientes (cedula_rif, nombre, telefono, direccion)
            VALUES ('J-99887766', 'Distribuidora Central C.A.', '0241-8888888', 'Av. Bolívar Norte')
        """)
        cursor.execute("""
            INSERT OR REPLACE INTO productos (
                codigo, referencia, departamento, descripcion_general,
                precio_dolares, precio_bcv, existencia, nombre_referencia_corto
            ) VALUES (
                'BATT-80', 'BAT-800', 'Repuestos', 'Batería automotriz de 800 amperios',
                85.0, 3400.0, 20, 'Bateria 800AMP'
            )
        """)
        cursor.execute("""
            INSERT INTO ventas (
                tipo_venta, cliente_id, total_usd, total_bcv, metodo_pago,
                referencia_pago, referencia_omitida, monto_cobrado,
                porcentaje_descuento, usuario_nombre, fecha
            ) VALUES (
                'Formal', 'J-99887766', 170.0, 6800.0, 'Punto de Venta',
                'POS-12345', 0, 170.0, 0, 'cajero1', '2026-10-23 15:30:00'
            )
        """)
        venta_id = cursor.lastrowid
        cursor.execute("""
            INSERT INTO ventas_detalle (
                venta_id, producto_codigo, cantidad, precio_unitario_usd,
                precio_unitario_bcv, subtotal_usd, subtotal_bcv
            ) VALUES (
                ?, 'BATT-80', 2.0, 85.0, 3400.0, 170.0, 6800.0
            )
        """, (venta_id,))
        conn.commit()

    return venta_id


def test_formato_ticket_80mm_registrado():
    """Verifica que 'ticket_80mm' esté disponible en los formatos del servicio."""
    assert "ticket_80mm" in _FORMATOS_PAPEL
    cfg = _FORMATOS_PAPEL["ticket_80mm"]
    assert cfg["margen"] == 4
    # La suma de los anchos útiles debe ser 72mm (80mm - 2*4mm de márgenes)
    assert sum(cfg["anchos"]) == 72


def test_generar_pdf_ticket_80mm_dimensiones(venta_ticket, tmp_path):
    """El PDF generado con formato ticket_80mm debe tener un ancho exacto de 80mm."""
    ruta_pdf = str(tmp_path / "Ticket_Prueba_80mm.pdf")
    resultado = generar_nota_entrega_pdf(
        venta_id=venta_ticket,
        divisa_impresion="USD",
        ruta_destino=ruta_pdf,
        formato_papel="ticket_80mm",
    )

    assert os.path.exists(resultado)
    assert os.path.getsize(resultado) > 0

    # Leer MediaBox del PDF: 80 mm en puntos tipográficos = 80 * 72 / 25.4 = 226.77 pt
    with open(resultado, "rb") as f:
        contenido = f.read().decode("latin1")

    match = re.search(r'/MediaBox\s*\[\s*([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s*\]', contenido)
    assert match is not None, "El PDF debe definir un /MediaBox válido"
    ancho_pt = float(match.group(3))
    ancho_mm = ancho_pt * 25.4 / 72.0

    assert pytest.approx(ancho_mm, abs=0.5) == 80.0


def test_contenido_pdf_ticket_80mm(venta_ticket, tmp_path):
    """El archivo PDF debe generarse correctamente con contenido de la venta."""
    ruta_pdf = str(tmp_path / "Ticket_Detalle.pdf")
    resultado = generar_nota_entrega_pdf(
        venta_id=venta_ticket,
        divisa_impresion="USD",
        ruta_destino=ruta_pdf,
        formato_papel="ticket_80mm",
    )

    assert os.path.exists(resultado)
    assert os.path.getsize(resultado) > 1000

    with open(resultado, "rb") as f:
        datos = f.read()
    # Verifica que sea un PDF válido
    assert datos.startswith(b"%PDF-")


def test_generar_pdf_ticket_en_bcv(venta_ticket, tmp_path):
    """Verifica que el ticket en bolívares se genere exitosamente."""
    ruta_pdf = str(tmp_path / "Ticket_BCV.pdf")
    resultado = generar_nota_entrega_pdf(
        venta_id=venta_ticket,
        divisa_impresion="BCV",
        ruta_destino=ruta_pdf,
        formato_papel="ticket_80mm",
    )

    assert os.path.exists(resultado)
    assert os.path.getsize(resultado) > 1000
    with open(resultado, "rb") as f:
        datos = f.read()
    assert datos.startswith(b"%PDF-")
