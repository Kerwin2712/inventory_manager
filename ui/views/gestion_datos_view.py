import os
import tkinter as tk
from tkinter import filedialog
from datetime import datetime
import pandas as pd
import flet as ft
from ui.views.base_view import BaseView
from core.database import get_connection, get_setting, set_setting
from services.importacion_service import procesar_importacion_excel

class GestionDatosView(BaseView):
    """Vista de Gestión de Datos y Respaldos del Sistema (ERS 1.1)."""

    def __init__(self, page: ft.Page = None, user_data: dict = None):
        self.user_data = user_data or {}
        super().__init__(route="/gestion-datos", title="Gestión de Datos y Respaldos")

    def abrir_dialogo_guardado(self, initial_dir: str, sugerencia_nombre: str) -> str:
        """Abre un cuadro de diálogo nativo de Windows (Tkinter) para seleccionar dónde guardar el respaldo Excel."""
        root = tk.Tk()
        root.attributes("-topmost", True)  # Ventana en primer plano
        root.withdraw()  # Ocultar la ventana principal de Tkinter
        ruta = filedialog.asksaveasfilename(
            initialdir=initial_dir,
            initialfile=sugerencia_nombre,
            title="Guardar Copia de Seguridad Excel",
            defaultextension=".xlsx",
            filetypes=[("Archivos de Excel", "*.xlsx")]
        )
        root.destroy()
        return ruta

    def abrir_dialogo_abrir(self) -> str:
        """Abre un cuadro de diálogo nativo de Windows (Tkinter) para seleccionar un archivo Excel a importar."""
        root = tk.Tk()
        root.attributes("-topmost", True)  # Ventana en primer plano
        root.withdraw()
        ruta = filedialog.askopenfilename(
            title="Seleccionar Archivo Excel para Carga Masiva",
            filetypes=[("Archivos de Excel", "*.xlsx;*.xls"), ("Todos los archivos", "*.*")]
        )
        root.destroy()
        return ruta

    def get_body(self) -> ft.Control:
        accent = self.get_accent_color()
        text_color = self.get_text_color()
        subtext_color = self.get_subtext_color()
        card_bg = self.get_card_bg()

        # ── Tarjeta 1: Carga Masiva (Importar Excel - ERS 1.1) ─────────────────
        card_importar = ft.Card(
            content=ft.Container(
                content=ft.Column([
                    ft.Row([
                        ft.Icon(ft.Icons.UPLOAD_FILE_ROUNDED, size=40, color=accent),
                        ft.Column([
                            ft.Text("Carga Masiva de Datos", size=16, weight=ft.FontWeight.BOLD, color=text_color),
                            ft.Text("Importación masiva de inventario y catálogos en lote desde Excel.", size=12, color=subtext_color)
                        ], spacing=2)
                    ], spacing=15),
                    ft.Divider(),
                    ft.Text("Permite cargar o actualizar simultáneamente productos, clientes y proveedores desde plantillas estructuradas.", size=13, color=subtext_color),
                    ft.Container(height=10),
                    ft.Button(
                        content=ft.Row([
                            ft.Icon(ft.Icons.FILE_UPLOAD_OUTLINED, color=ft.Colors.WHITE),
                            ft.Text("IMPORTAR DESDE EXCEL", weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE)
                        ], alignment=ft.MainAxisAlignment.CENTER),
                        style=ft.ButtonStyle(bgcolor=accent, shape=ft.RoundedRectangleBorder(radius=8)),
                        on_click=self.handle_importar_click
                    )
                ], spacing=12),
                padding=20
            ),
            bgcolor=card_bg,
            col={"sm": 12, "lg": 6}
        )

        # ── Tarjeta 2: Copias de Seguridad (Exportar a Excel - ERS 1.1) ───────
        card_exportar = ft.Card(
            content=ft.Container(
                content=ft.Column([
                    ft.Row([
                        ft.Icon(ft.Icons.SAVINGS_ROUNDED, size=40, color=ft.Colors.GREEN_600),
                        ft.Column([
                            ft.Text("Copias de Seguridad (Backup)", size=16, weight=ft.FontWeight.BOLD, color=text_color),
                            ft.Text("Exportación completa a libro Excel (.xlsx) con pestañas separadas.", size=12, color=subtext_color)
                        ], spacing=2)
                    ], spacing=15),
                    ft.Divider(),
                    ft.Text("Genera un respaldo integral exportando Productos, Clientes y Proveedores en hojas separadas.", size=13, color=subtext_color),
                    ft.Container(height=10),
                    ft.Button(
                        content=ft.Row([
                            ft.Icon(ft.Icons.DOWNLOAD_ROUNDED, color=ft.Colors.WHITE),
                            ft.Text("GENERAR COPIA DE SEGURIDAD (.XLSX)", weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE)
                        ], alignment=ft.MainAxisAlignment.CENTER),
                        style=ft.ButtonStyle(bgcolor=ft.Colors.GREEN_700, shape=ft.RoundedRectangleBorder(radius=8)),
                        on_click=self.handle_exportar_excel
                    )
                ], spacing=12),
                padding=20
            ),
            bgcolor=card_bg,
            col={"sm": 12, "lg": 6}
        )

        return ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Icon(ft.Icons.DATASET_ROUNDED, size=28, color=accent),
                    ft.Text("Módulo de Gestión de Datos y Respaldos", size=20, weight=ft.FontWeight.BOLD, color=text_color)
                ], spacing=10),
                ft.Text("Administre las importaciones masivas y la exportación de copias de seguridad de la base de datos.", color=subtext_color),
                ft.Divider(height=20, color=self.get_border_color()),
                ft.ResponsiveRow([card_importar, card_exportar], spacing=20, vertical_alignment=ft.CrossAxisAlignment.START)
            ], spacing=15, scroll=ft.ScrollMode.AUTO, expand=True),
            padding=15,
            expand=True
        )

    def handle_importar_click(self, e):
        """Ejecuta la Carga Masiva defensiva y transaccional desde Excel."""
        ruta_archivo = self.abrir_dialogo_abrir()
        if not ruta_archivo:
            return

        res = procesar_importacion_excel(ruta_archivo)

        if res.get("exito"):
            self.show_alert_success(e, res.get("mensaje"))
        else:
            self.mostrar_dialogo_error(e, res.get("mensaje"))

    def mostrar_dialogo_error(self, e, error_msg: str):
        """Muestra un AlertDialog emergente cuando la importación transaccional falla y ejecuta ROLLBACK."""
        p = self.get_current_page(e)
        if not p:
            return

        def cerrar_dialogo(e_close):
            dlg.open = False
            p.update()

        dlg = ft.AlertDialog(
            title=ft.Row([
                ft.Icon(ft.Icons.ERROR_OUTLINED, color=ft.Colors.RED_500, size=28),
                ft.Text("Error en Carga Masiva de Excel", weight=ft.FontWeight.BOLD, color=ft.Colors.RED_500)
            ], spacing=10),
            content=ft.Container(
                content=ft.Column([
                    ft.Text("Se ha realizado un ROLLBACK automático en la base de datos.", weight=ft.FontWeight.BOLD, size=13),
                    ft.Divider(height=10),
                    ft.Text(error_msg, color=self.get_text_color(), size=13),
                ], spacing=10, tight=True),
                width=450,
                padding=10
            ),
            actions=[
                ft.TextButton("Entendido", on_click=cerrar_dialogo)
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

        p.dialog = dlg
        dlg.open = True
        p.update()

    def handle_exportar_excel(self, e):
        """Exporta la base de datos completa a un libro Excel (.xlsx) con pestañas separadas (ERS 1.1)."""
        last_dir = get_setting("last_excel_dir", default=None)
        if last_dir and not os.path.exists(last_dir):
            last_dir = None

        sugerencia = f"Backup_Inventario_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        ruta_destino = self.abrir_dialogo_guardado(last_dir, sugerencia)

        if not ruta_destino:
            return

        try:
            conn = get_connection()

            # 1. Cargar DataFrames de cada tabla
            df_productos = pd.read_sql_query("""
                SELECT 
                    codigo AS [Código],
                    referencia AS [Referencia],
                    departamento AS [Departamento],
                    descripcion_general AS [Descripción General],
                    marca AS [Marca],
                    precio_dolares AS [Precio ($)],
                    precio_bcv AS [Precio (Bs BCV)],
                    proveedor_id AS [ID Proveedor],
                    existencia AS [Existencia],
                    codigo_barras AS [Código Barras],
                    nombre_referencia_corto AS [Nombre Referencia Corto],
                    fecha_ultima_modificacion AS [Última Modificación]
                FROM productos
            """, conn)

            df_clientes = pd.read_sql_query("""
                SELECT 
                    cedula_rif AS [Cédula / RIF],
                    nombre AS [Razón Social / Nombre],
                    direccion AS [Dirección],
                    telefono AS [Teléfono],
                    correo AS [Correo Electrónico]
                FROM clientes
            """, conn)

            df_proveedores = pd.read_sql_query("""
                SELECT 
                    id AS [ID],
                    empresa AS [Razón Social / Empresa],
                    contacto AS [Persona de Contacto],
                    telefono AS [Teléfono],
                    correo AS [Correo Electrónico],
                    descripcion AS [Descripción / Notas]
                FROM proveedores
            """, conn)

            conn.close()

            # 2. Generar archivo Excel con pestañas separadas usando openpyxl
            with pd.ExcelWriter(ruta_destino, engine="openpyxl") as writer:
                df_productos.to_excel(writer, sheet_name="Productos", index=False)
                df_clientes.to_excel(writer, sheet_name="Clientes", index=False)
                df_proveedores.to_excel(writer, sheet_name="Proveedores", index=False)

            # 3. Guardar el directorio contenedor en app_settings
            directorio = os.path.dirname(ruta_destino)
            if directorio:
                set_setting("last_excel_dir", directorio)

            self.show_alert_success(e, f"Copia de seguridad guardada exitosamente en:\n{ruta_destino}")

        except Exception as ex:
            self.show_alert_error(e, f"Error al generar la copia de seguridad Excel: {ex}")

    def show_alert_success(self, e, msg: str):
        p = self.get_current_page(e)
        if p:
            s = ft.SnackBar(
                content=ft.Text(msg, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD),
                bgcolor=ft.Colors.GREEN_700,
                duration=4000
            )
            p.overlay.append(s)
            s.open = True
            p.update()

    def show_alert_error(self, e, msg: str):
        p = self.get_current_page(e)
        if p:
            s = ft.SnackBar(
                content=ft.Text(msg, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD),
                bgcolor=ft.Colors.RED_700,
                duration=4000
            )
            p.overlay.append(s)
            s.open = True
            p.update()

    def show_alert_info(self, e, msg: str):
        p = self.get_current_page(e)
        if p:
            s = ft.SnackBar(
                content=ft.Text(msg, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD),
                bgcolor=self.get_accent_color(),
                duration=3500
            )
            p.overlay.append(s)
            s.open = True
            p.update()
