import os
import platform
import subprocess
from fpdf import FPDF
from core.database import get_connection

# ERS 3.5: la Nota de Entrega debe poder adaptarse a hojas media carta o carta.
# Medidas en mm: Carta (Letter) = 215.9 x 279.4; Media Carta = mitad portrait
# de una Carta = 139.7 x 215.9 (5.5" x 8.5").
_FORMATOS_PAPEL = {
    # anchos = (codigo, nombre_corto, cantidad, precio_unit, subtotal) en mm,
    # calibrados para no exceder el ancho útil de cada tamaño de hoja.
    "carta": {"page": "Letter", "margen": 15, "anchos": (28, 76, 18, 28, 28)},
    "media_carta": {"page": (139.7, 215.9), "margen": 8, "anchos": (20, 50, 14, 18, 18)},
}


def enviar_a_impresora(ruta_pdf: str) -> bool:
    """Envía el PDF a la impresora predeterminada del sistema (ERS 3.5, paso 4).
    Retorna True si se pudo despachar la orden de impresión, False si no hay
    un mecanismo de impresión disponible en la plataforma actual."""
    if not ruta_pdf or not os.path.exists(ruta_pdf):
        raise ValueError(f"El archivo PDF '{ruta_pdf}' no existe para poder imprimirlo.")

    sistema = platform.system()
    if sistema == "Windows":
        # Usa el verbo "print" registrado en el sistema para PDFs (visor
        # predeterminado), que despacha el trabajo a la impresora por defecto.
        os.startfile(ruta_pdf, "print")
        return True
    if sistema == "Darwin":
        subprocess.run(["lp", ruta_pdf], check=True)
        return True
    if sistema == "Linux":
        subprocess.run(["lp", ruta_pdf], check=True)
        return True
    return False

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

def generar_nota_entrega_pdf(
    venta_id: int,
    divisa_impresion: str = "USD",
    ruta_destino: str = "",
    formato_papel: str = "carta",
) -> str:
    """
    Genera la Nota de Entrega en PDF cumpliendo estrictamente con la regla ERS 3.5:
    extrae e imprime exclusivamente el campo 'nombre_referencia_corto' de la tabla productos.
    Guarda el archivo en la 'ruta_destino' especificada.

    `formato_papel` acepta "carta" (Letter) o "media_carta" (mitad de una
    hoja carta), adaptando márgenes y anchos de columna a cada tamaño.
    """
    if not ruta_destino or not ruta_destino.strip():
        raise ValueError("Debe especificar una ruta de destino válida para el archivo PDF.")

    clave_formato = (formato_papel or "carta").strip().lower()
    if clave_formato not in _FORMATOS_PAPEL:
        clave_formato = "carta"
    cfg_papel = _FORMATOS_PAPEL[clave_formato]
    margen = cfg_papel["margen"]
    ancho_codigo, ancho_nombre, ancho_cant, ancho_preciou, ancho_subtotal = cfg_papel["anchos"]
    ancho_tabla = ancho_codigo + ancho_nombre + ancho_cant + ancho_preciou + ancho_subtotal

    pdf_path = os.path.abspath(ruta_destino.strip())
    dir_padre = os.path.dirname(pdf_path)
    if dir_padre:
        os.makedirs(dir_padre, exist_ok=True)

    divisa = divisa_impresion.upper().strip() if divisa_impresion else "USD"
    if divisa not in ["USD", "BCV"]:
        divisa = "USD"

    conn = get_connection()
    cursor = conn.cursor()

    # Obtener cabecera de la venta y datos del cliente si aplica
    cursor.execute("""
        SELECT v.id, v.tipo_venta, v.cliente_id, v.total_usd, v.total_bcv, v.fecha, v.metodo_pago,
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

    pdf = NotaEntregaPDF(orientation="P", unit="mm", format=cfg_papel["page"])

    pdf.alias_nb_pages()
    pdf.set_margins(margen, margen, margen)
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=margen)

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

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(38, 6, "Método de Pago:", ln=False)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, str(venta["metodo_pago"] or "Efectivo"), ln=True)

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

    # Tabla de renglones (anchos adaptados al formato de papel elegido)
    pdf.set_fill_color(230, 230, 230)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(ancho_codigo, 7, "Código", border=1, align="C", fill=True)
    # ERS 3.5: Imprimir EXCLUSIVAMENTE el nombre_referencia_corto
    pdf.cell(ancho_nombre, 7, "Nombre Corto (Ref.)", border=1, align="L", fill=True)
    pdf.cell(ancho_cant, 7, "Cant.", border=1, align="C", fill=True)
    moneda_label = "$" if divisa == "USD" else "Bs."
    pdf.cell(ancho_preciou, 7, f"P. Unit ({moneda_label})", border=1, align="R", fill=True)
    pdf.cell(ancho_subtotal, 7, f"Subtotal ({moneda_label})", border=1, align="R", fill=True)
    pdf.ln()

    pdf.set_font("Helvetica", "", 9)
    total_acumulado = 0.0
    max_chars_nombre = max(8, int(ancho_nombre / 2))

    for d in detalles:
        # Extraer exclusivamente el nombre_referencia_corto
        nombre_corte = d['nombre_referencia_corto'] or d['referencia'] or d['codigo']
        if len(str(nombre_corte)) > max_chars_nombre:
            nombre_corte = str(nombre_corte)[:max_chars_nombre - 3] + "..."

        cant = float(d['cantidad'])
        if divisa == "USD":
            precio_u = float(d['precio_unitario_usd'])
            subtotal = float(d['subtotal_usd'])
        else:
            precio_u = float(d['precio_unitario_bcv'])
            subtotal = float(d['subtotal_bcv'])

        total_acumulado += subtotal

        pdf.cell(ancho_codigo, 6, str(d['codigo']), border=1, align="C")
        pdf.cell(ancho_nombre, 6, str(nombre_corte), border=1, align="L")
        pdf.cell(ancho_cant, 6, f"{cant:.2f}", border=1, align="C")
        pdf.cell(ancho_preciou, 6, f"{precio_u:,.2f}", border=1, align="R")
        pdf.cell(ancho_subtotal, 6, f"{subtotal:,.2f}", border=1, align="R")
        pdf.ln()

    # Total de la nota (ancho de etiqueta = tabla menos la columna de subtotal)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(ancho_tabla - ancho_subtotal, 7, "TOTAL GENERAL:", border=1, align="R", fill=True)
    pdf.cell(ancho_subtotal, 7, f"{moneda_label} {total_acumulado:,.2f}", border=1, align="R", fill=True)

    # Bloque de firmas (mitad del ancho de la tabla cada una)
    mitad_tabla = ancho_tabla / 2
    pdf.ln(18)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(mitad_tabla, 5, "___________________________________", align="C")
    pdf.cell(mitad_tabla, 5, "___________________________________", align="C", ln=True)
    pdf.cell(mitad_tabla, 5, "Entregado por", align="C")
    pdf.cell(mitad_tabla, 5, "Recibido Conforme (Cliente)", align="C", ln=True)

    pdf.output(pdf_path)
    return pdf_path
