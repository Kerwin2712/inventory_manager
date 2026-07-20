import os
from fpdf import FPDF
from core.database import get_connection

class NotaEntregaPDF(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 14)
        self.cell(0, 8, "SISTEMA INTEGRADO DE INVENTARIO Y VENTAS", ln=True, align="C")
        self.set_font("Helvetica", "B", 12)
        self.cell(0, 6, "NOTA DE ENTREGA", ln=True, align="C")
        self.ln(4)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.cell(0, 10, f"Página {self.page_no()}/{{nb}}", align="C")

def generar_nota_entrega_pdf(venta_id: int, divisa_impresion: str = "USD") -> str:
    """
    Genera la Nota de Entrega en PDF cumpliendo estrictamente con la regla ERS 3.5:
    extrae e imprime exclusivamente el campo 'nombre_referencia_corto' de la tabla productos.
    """
    divisa = divisa_impresion.upper().strip() if divisa_impresion else "USD"
    if divisa not in ["USD", "BCV"]:
        divisa = "USD"

    conn = get_connection()
    cursor = conn.cursor()

    # Obtener la cabecera de la venta y datos del cliente si aplica
    cursor.execute("""
        SELECT v.id, v.tipo_venta, v.cliente_id, v.total_usd, v.total_bcv, v.fecha,
               c.nombre AS cliente_nombre, c.direccion AS cliente_direccion
        FROM ventas v
        LEFT JOIN clientes c ON v.cliente_id = c.cedula_rif
        WHERE v.id = ?
    """, (venta_id,))
    venta = cursor.fetchone()

    if not venta:
        conn.close()
        raise ValueError(f"La venta con ID {venta_id} no existe.")

    # ERS 3.5: Consultar detalles extrayendo 'nombre_referencia_corto' (sin descripcion_general)
    cursor.execute("""
        SELECT vd.cantidad, vd.precio_unitario_usd, vd.precio_unitario_bcv,
               vd.subtotal_usd, vd.subtotal_bcv, p.codigo, p.nombre_referencia_corto, p.referencia
        FROM ventas_detalle vd
        JOIN productos p ON vd.producto_codigo = p.codigo
        WHERE vd.venta_id = ?
    """, (venta_id,))
    detalles = cursor.fetchall()
    conn.close()

    # Directorio de salida exports/
    exports_dir = os.path.join(os.getcwd(), "exports")
    os.makedirs(exports_dir, exist_ok=True)

    pdf_filename = f"Nota_Entrega_{venta_id}.pdf"
    pdf_path = os.path.join(exports_dir, pdf_filename)

    pdf = NotaEntregaPDF(orientation="P", unit="mm", format="Letter")
    pdf.alias_nb_pages()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    # Cabecera de la Nota
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(38, 6, "Nro. Nota / Venta:", ln=False)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(50, 6, f"{venta['id']:06d}", ln=False)

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(25, 6, "Fecha:", ln=False)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, str(venta['fecha']), ln=True)

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(38, 6, "Tipo de Venta:", ln=False)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(50, 6, str(venta['tipo_venta']), ln=False)

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(25, 6, "Moneda:", ln=False)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, "Dólares ($)" if divisa == "USD" else "Bolívares (Bs. BCV)", ln=True)

    # Información del cliente
    if venta['tipo_venta'] == 'Formal' and venta['cliente_id']:
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(38, 6, "Cliente:", ln=False)
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 6, f"{venta['cliente_nombre']} ({venta['cliente_id']})", ln=True)

        if venta['cliente_direccion']:
            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(38, 6, "Dirección:", ln=False)
            pdf.set_font("Helvetica", "", 10)
            pdf.cell(0, 6, str(venta['cliente_direccion']), ln=True)
    else:
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(38, 6, "Cliente:", ln=False)
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 6, "Cliente Informal / Mostrador", ln=True)

    pdf.ln(4)

    # Tabla de renglones
    pdf.set_fill_color(230, 230, 230)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(30, 7, "Código", border=1, align="C", fill=True)
    # ERS 3.5: Imprimir EXCLUSIVAMENTE el nombre_referencia_corto
    pdf.cell(80, 7, "Nombre Corto (Ref.)", border=1, align="L", fill=True)
    pdf.cell(20, 7, "Cant.", border=1, align="C", fill=True)
    moneda_label = "$" if divisa == "USD" else "Bs."
    pdf.cell(30, 7, f"P. Unit ({moneda_label})", border=1, align="R", fill=True)
    pdf.cell(30, 7, f"Subtotal ({moneda_label})", border=1, align="R", fill=True)
    pdf.ln()

    pdf.set_font("Helvetica", "", 9)
    total_acumulado = 0.0

    for d in detalles:
        # Extraer exclusivamente el nombre_referencia_corto
        nombre_corte = d['nombre_referencia_corto'] or d['referencia'] or d['codigo']
        if len(str(nombre_corte)) > 42:
            nombre_corte = str(nombre_corte)[:39] + "..."

        cant = float(d['cantidad'])
        if divisa == "USD":
            precio_u = float(d['precio_unitario_usd'])
            subtotal = float(d['subtotal_usd'])
        else:
            precio_u = float(d['precio_unitario_bcv'])
            subtotal = float(d['subtotal_bcv'])

        total_acumulado += subtotal

        pdf.cell(30, 6, str(d['codigo']), border=1, align="C")
        pdf.cell(80, 6, str(nombre_corte), border=1, align="L")
        pdf.cell(20, 6, f"{cant:.2f}", border=1, align="C")
        pdf.cell(30, 6, f"{precio_u:,.2f}", border=1, align="R")
        pdf.cell(30, 6, f"{subtotal:,.2f}", border=1, align="R")
        pdf.ln()

    # Total de la nota
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(130, 7, "TOTAL GENERAL:", border=1, align="R", fill=True)
    pdf.cell(60, 7, f"{moneda_label} {total_acumulado:,.2f}", border=1, align="R", fill=True)

    # Bloque de firmas
    pdf.ln(18)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(95, 5, "___________________________________", align="C")
    pdf.cell(95, 5, "___________________________________", align="C", ln=True)
    pdf.cell(95, 5, "Entregado por", align="C")
    pdf.cell(95, 5, "Recibido Conforme (Cliente)", align="C", ln=True)

    pdf.output(pdf_path)
    return pdf_path
