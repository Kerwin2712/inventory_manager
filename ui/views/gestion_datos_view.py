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
        try:
            print(">>> [abrir_dialogo_abrir] Instanciando ventana oculta tk.Tk()...")
            root = tk.Tk()
            root.attributes("-topmost", True)  # Ventana en primer plano
            root.withdraw()
            print(">>> [abrir_dialogo_abrir] Lanzando filedialog.askopenfilename...")
            ruta = filedialog.askopenfilename(
                title="Seleccionar Archivo Excel para Carga Masiva",
                filetypes=[("Archivos de Excel", "*.xlsx;*.xls"), ("Todos los archivos", "*.*")]
            )
            print(f">>> [abrir_dialogo_abrir] Diálogo cerrado. Ruta obtenida: '{ruta}'")
            root.destroy()
            print(">>> [abrir_dialogo_abrir] Ventana tk destruida con éxito.")
            return ruta
        except Exception as ex:
            import traceback
            print(f">>> [abrir_dialogo_abrir] EXCEPCIÓN en diálogo de archivo:\n{traceback.format_exc()}")
            raise ex

    def get_body(self) -> ft.Control:
        accent = self.get_accent_color()
        text_color = self.get_text_color()
        subtext_color = self.get_subtext_color()
        card_bg = self.get_card_bg()

        # ── Tarjeta 1: Carga Masiva (Importar Excel - ERS 1.1) ─────────────────
        card_importar = self.create_card(
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
                    style=ft.ButtonStyle(bgcolor=accent, shape=ft.RoundedRectangleBorder(radius=12)),
                    on_click=self.handle_importar_click
                )
            ], spacing=12),
            padding=20,
            border_radius=16
        )
        card_importar.col = {"sm": 12, "lg": 6}

        # ── Tarjeta 2: Copias de Seguridad (Exportar a Excel - ERS 1.1) ───────
        card_exportar = self.create_card(
            content=ft.Column([
                ft.Row([
                    ft.Icon(ft.Icons.SAVINGS_ROUNDED, size=40, color=accent),
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
                    style=ft.ButtonStyle(bgcolor=accent, shape=ft.RoundedRectangleBorder(radius=12)),
                    on_click=self.handle_exportar_excel
                )
            ], spacing=12),
            padding=20,
            border_radius=16
        )
        card_exportar.col = {"sm": 12, "lg": 6}

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
        """Ejecuta la Carga Masiva analizando primero proveedores nuevos (ERS 1.1)."""
        try:
            print("\n>>> [GestionDatosView] Clic en IMPORTAR DESDE EXCEL")
            with open("import_debug.log", "a", encoding="utf-8") as f:
                f.write(f"\n[{datetime.now()}] Iniciando handle_importar_click\n")
            
            print(">>> [GestionDatosView] Abriendo diálogo de selección de archivo...")
            ruta_archivo = self.abrir_dialogo_abrir()
            with open("import_debug.log", "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now()}] Ruta seleccionada: {ruta_archivo}\n")
            print(f">>> [GestionDatosView] Ruta de archivo seleccionada: '{ruta_archivo}'")
                
            if not ruta_archivo:
                print(">>> [GestionDatosView] Cancelado: No se seleccionó ningún archivo.")
                with open("import_debug.log", "a", encoding="utf-8") as f:
                    f.write(f"[{datetime.now()}] No se seleccionó archivo\n")
                return

            print(">>> [GestionDatosView] Importando y analizando proveedores del Excel...")
            from services.importacion_service import analizar_proveedores_excel
            analisis = analizar_proveedores_excel(ruta_archivo)
            
            with open("import_debug.log", "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now()}] Resultado del análisis: {analisis}\n")
            print(f">>> [GestionDatosView] Resultado del análisis de proveedores: {analisis}")

            if not analisis.get("exito"):
                print(f">>> [GestionDatosView] ERROR en análisis: {analisis.get('mensaje')}")
                self.show_alert_error(e, analisis.get("mensaje"))
                return

            faltantes = analisis.get("proveedores_faltantes", [])
            print(f">>> [GestionDatosView] Proveedores faltantes en BD: {faltantes}")
            if faltantes:
                print(f">>> [GestionDatosView] Iniciando asistente interactivo para {len(faltantes)} proveedores faltantes...")
                self.mostrar_asistente_proveedores_faltantes(e, ruta_archivo, faltantes)
            else:
                print(">>> [GestionDatosView] No hay proveedores faltantes. Procediendo con la importación final...")
                self.ejecutar_importacion_final(e, ruta_archivo)
        except Exception as ex:
            import traceback
            err_msg = traceback.format_exc()
            with open("import_debug.log", "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now()}] EXCEPCIÓN: {err_msg}\n")
            print(f"\n>>> [GestionDatosView] EXCEPCIÓN CRÍTICA en handle_importar_click:\n{err_msg}")
            try:
                self.show_alert_error(e, f"Excepción crítica: {str(ex)}")
            except Exception:
                pass

    def mostrar_asistente_proveedores_faltantes(self, e, ruta_archivo, faltantes, idx=0):
        """Muestra un diálogo dinámico secuencial para completar información de proveedores nuevos."""
        p = self.get_current_page(e)
        if not p:
            print(">>> [mostrar_asistente_proveedores_faltantes] ERROR: No se pudo obtener la instancia de Page activa.")
            return

        nombre_prov = faltantes[idx]
        total_faltantes = len(faltantes)
        print(f">>> [mostrar_asistente_proveedores_faltantes] Abriendo modal para proveedor '{nombre_prov}' ({idx + 1} de {total_faltantes})...")

        # Controles del formulario
        txt_empresa = ft.TextField(
            label="Razón Social / Empresa", 
            value=nombre_prov, 
            disabled=True, 
            prefix_icon=ft.Icons.BUSINESS
        )
        txt_rif = ft.TextField(
            label="Cédula / RIF (Opcional)", 
            prefix_icon=ft.Icons.BADGE
        )
        txt_contacto = ft.TextField(
            label="Persona de Contacto (Opcional)", 
            prefix_icon=ft.Icons.PERSON
        )
        txt_telefono = ft.TextField(
            label="Teléfono de Contacto (Obligatorio)*", 
            prefix_icon=ft.Icons.PHONE,
            keyboard_type=ft.KeyboardType.PHONE
        )
        txt_correo = ft.TextField(
            label="Correo Electrónico (Opcional)", 
            prefix_icon=ft.Icons.EMAIL,
            keyboard_type=ft.KeyboardType.EMAIL
        )
        txt_descripcion = ft.TextField(
            label="Descripción / Notas (Opcional)", 
            multiline=True, 
            min_lines=2, 
            max_lines=3,
            prefix_icon=ft.Icons.NOTE
        )
        lbl_error = ft.Text(
            "", 
            color=ft.Colors.RED_500, 
            size=12, 
            weight=ft.FontWeight.BOLD
        )

        def cerrar_asistente(e_close):
            print(">>> [mostrar_asistente_proveedores_faltantes] Asistente cancelado por el usuario.")
            dlg.open = False
            p.update()
            self.show_alert_info(e, "Importación cancelada por el usuario.")

        def registrar_proveedor(e_reg):
            lbl_error.value = ""
            p.update()

            empresa = txt_empresa.value.strip()
            rif = txt_rif.value.strip()
            contacto = txt_contacto.value.strip()
            telefono = txt_telefono.value.strip()
            correo = txt_correo.value.strip()
            descripcion = txt_descripcion.value.strip()

            print(f">>> [registrar_proveedor] Intentando registrar: Empresa='{empresa}', RIF='{rif}', Teléfono='{telefono}'...")

            if not telefono:
                print(">>> [registrar_proveedor] ERROR: Teléfono vacío")
                lbl_error.value = "El Teléfono de Contacto es obligatorio por regla de negocio."
                p.update()
                return

            try:
                from services.cartera_service import crear_proveedor
                crear_proveedor(
                    empresa=empresa,
                    contacto=contacto if contacto else None,
                    telefono=telefono,
                    correo=correo if correo else None,
                    rif=rif if rif else None,
                    descripcion=descripcion if descripcion else f"Creado automáticamente durante la importación masiva."
                )
                print(f">>> [registrar_proveedor] Registrado exitosamente en SQLite.")
                
                dlg.open = False
                p.update()

                # Siguiente o iniciar importación final
                sig_idx = idx + 1
                if sig_idx < total_faltantes:
                    self.mostrar_asistente_proveedores_faltantes(e, ruta_archivo, faltantes, sig_idx)
                else:
                    print(">>> [registrar_proveedor] Todos los proveedores registrados. Procediendo a la importación final...")
                    self.show_alert_success(e, "Todos los proveedores nuevos se registraron correctamente.")
                    self.ejecutar_importacion_final(e, ruta_archivo)

            except Exception as ex:
                import traceback
                print(f">>> [registrar_proveedor] EXCEPCIÓN al registrar: {traceback.format_exc()}")
                lbl_error.value = f"Error al registrar: {str(ex)}"
                p.update()

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.Icons.ADD_BUSINESS, color=self.get_accent_color(), size=28),
                ft.Text(f"Proveedor Faltante ({idx + 1} de {total_faltantes})", weight=ft.FontWeight.BOLD)
            ], spacing=10),
            content=ft.Container(
                content=ft.Column([
                    ft.Text(f"El proveedor '{nombre_prov}' no existe. Por favor, completa su información para proceder con la importación.", size=13, color=self.get_subtext_color()),
                    ft.Divider(height=10),
                    txt_empresa,
                    txt_rif,
                    txt_contacto,
                    txt_telefono,
                    txt_correo,
                    txt_descripcion,
                    lbl_error
                ], spacing=12, tight=True),
                width=480,
                padding=10
            ),
            actions=[
                ft.TextButton("Cancelar Importación", on_click=cerrar_asistente),
                ft.Button(
                    content=ft.Row([ft.Icon(ft.Icons.SAVE), ft.Text("Guardar y Continuar")], tight=True),
                    bgcolor=self.get_accent_color(),
                    color=ft.Colors.WHITE,
                    on_click=registrar_proveedor
                )
            ],
            actions_alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )

        if dlg not in p.overlay:
            p.overlay.append(dlg)
        dlg.open = True
        p.update()

    def ejecutar_importacion_final(self, e, ruta_archivo):
        """Llama al servicio de importación real para los productos del Excel."""
        try:
            print(f">>> [ejecutar_importacion_final] Iniciando importación de productos desde: '{ruta_archivo}'")
            from services.importacion_service import procesar_importacion_excel
            with open("import_debug.log", "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now()}] Iniciando ejecutar_importacion_final para: {ruta_archivo}\n")
            
            res = procesar_importacion_excel(ruta_archivo)
            
            with open("import_debug.log", "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now()}] Resultado de la importación final: {res}\n")
            print(f">>> [ejecutar_importacion_final] Resultado de la importación: {res}")

            if res.get("exito"):
                print(">>> [ejecutar_importacion_final] Importación exitosa, mostrando snackbar verde.")
                self.show_alert_success(e, res.get("mensaje"))
            else:
                print(f">>> [ejecutar_importacion_final] Falla en importación: {res.get('mensaje')}. Mostrando diálogo de error.")
                self.mostrar_dialogo_error(e, res.get("mensaje"))
        except Exception as ex:
            import traceback
            err_msg = traceback.format_exc()
            with open("import_debug.log", "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now()}] EXCEPCIÓN EN IMPORTACIÓN FINAL: {err_msg}\n")
            print(f"\n>>> [ejecutar_importacion_final] EXCEPCIÓN en importación final:\n{err_msg}")
            try:
                self.show_alert_error(e, f"Excepción crítica en importación final: {str(ex)}")
            except Exception:
                pass

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

        if dlg not in p.overlay:
            p.overlay.append(dlg)
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
