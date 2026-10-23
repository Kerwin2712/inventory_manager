"""Pruebas de interfaz para el diálogo de comprobante / impresora térmica en VentasView.

Verifica:
- Apertura del diálogo tras finalizar una venta.
- Detección de impresora conectada vs no detectada en la UI.
- Fallback a exportación en PDF.
- Apertura del diálogo de configuración de impresora.
"""
import pytest
from unittest.mock import patch

from core.database import get_connection
from ui.views.ventas_view import VentasView


class PageFalsa:
    """Emula la pila de diálogos de flet.BasePage."""
    def __init__(self):
        self.dialogos = []
        self.overlay = []
        self.updates = 0

    def show_dialog(self, dialog):
        dialog.open = True
        self.dialogos.append(dialog)
        self.updates += 1

    def pop_dialog(self):
        dlg = next((d for d in reversed(self.dialogos) if d.open), None)
        if dlg is None:
            return None
        dlg.open = False
        self.updates += 1
        return dlg

    def update(self):
        self.updates += 1


class EventoFalso:
    def __init__(self, page, control=None):
        self.page = page
        self.control = control


@pytest.fixture
def pagina():
    return PageFalsa()


@pytest.fixture
def evento(pagina):
    return EventoFalso(pagina)


@pytest.fixture
def vista_ventas():
    """Instancia de VentasView."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO ventas (tipo_venta, total_usd, total_bcv, metodo_pago)
            VALUES ('Formal', 50.0, 2000.0, 'Efectivo')
        """)
        venta_id = cursor.lastrowid
        conn.commit()

    vista = VentasView(user_data={"username": "cajero_test", "role": "Vendedor"})
    vista.get_body()
    vista.venta_id_reciente = venta_id
    return vista


def test_dialogo_con_impresora_conectada(vista_ventas, evento):
    """Si la impresora térmica está conectada, el diálogo ofrece 'Imprimir en Térmica (80mm)'."""
    info_conectada = {
        "nombre": "Mini Impresora MP80-12",
        "conectada": True,
        "is_default": False,
        "configurada_manualmente": False,
    }

    with patch("ui.views.ventas_view.detectar_impresora_termica", return_value=info_conectada):
        vista_ventas.mostrar_dialogo_pdf(evento)

    dlg = vista_ventas._dlg_pdf
    assert dlg is not None
    assert any("Comprobante de Venta" in str(getattr(t, "value", "")) for t in dlg.title.controls if hasattr(t, "value"))

    textos_acciones = [
        getattr(a, "text", "") or getattr(a, "content", "")
        for a in dlg.actions
        if hasattr(a, "text") or hasattr(a, "content")
    ]
    assert any("Imprimir en Térmica" in t for t in textos_acciones)
    assert any("Exportar PDF" in t for t in textos_acciones)


def test_dialogo_con_impresora_desconectada_ofrece_pdf(vista_ventas, evento):
    """Si la impresora térmica no está conectada, el diálogo prioriza 'Exportar como PDF'."""
    with patch("ui.views.ventas_view.detectar_impresora_termica", return_value=None):
        vista_ventas.mostrar_dialogo_pdf(evento)

    dlg = vista_ventas._dlg_pdf
    assert dlg is not None

    textos_acciones = [
        getattr(a, "text", "") or getattr(a, "content", "")
        for a in dlg.actions
        if hasattr(a, "text") or hasattr(a, "content")
    ]
    # No debe ofrecer el botón de imprimir en térmica porque no está conectada
    assert not any("Imprimir en Térmica" in t for t in textos_acciones)
    # Debe ofrecer directamente la exportación en PDF
    assert any("Exportar como PDF" in t for t in textos_acciones)


def test_abrir_dialogo_configuracion_impresora(vista_ventas, evento):
    """Verifica que el diálogo de configuración de impresora se abra con las impresoras del sistema."""
    impresoras_sistema = [
        {"nombre": "POS-80", "is_default": False, "is_offline": False},
        {"nombre": "Microsoft Print to PDF", "is_default": True, "is_offline": False},
    ]

    with patch("ui.views.ventas_view.listar_impresoras_sistema", return_value=impresoras_sistema):
        vista_ventas.abrir_dialogo_configuracion_impresora(evento)

    assert len(vista_ventas._dialog_stack) >= 1
    dlg_conf = vista_ventas._dialog_stack[-1]
    assert "Configurar Impresora Térmica" in str(dlg_conf.title.controls[1].value)
