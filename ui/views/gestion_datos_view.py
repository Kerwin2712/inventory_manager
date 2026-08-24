import os
import tkinter as tk
from tkinter import filedialog
from datetime import datetime
import pandas as pd
import flet as ft
from ui.views.base_view import BaseView
from ui.components.scroll_nav import build_scroll_nav
from core.database import get_connection, get_setting, set_setting
from services.importacion_service import (
    procesar_importacion_excel,
    CAMPOS_PRODUCTO_MAPEO,
    listar_hojas_excel,
    detectar_hoja_productos,
    obtener_columnas_y_muestra,
    sugerir_mapeo_columnas,
    analizar_proveedores_con_mapeo,
    ejecutar_importacion_completa_mapeada,
)

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
        """Ejecuta la Carga Masiva: selecciona el archivo y abre el asistente
        de mapeo de columnas (el usuario decide a qué campo de la BD
        corresponde cada columna del Excel, sin importar cómo se llame)."""
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

            self.mostrar_asistente_mapeo(e, ruta_archivo)
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

    def mostrar_asistente_mapeo(self, e, ruta_archivo: str, hoja_forzada: str | None = None):
        """Asistente de mapeo de columnas para la importación de inventario:
        muestra las columnas reales del archivo con una muestra de filas y
        deja que el usuario decida explícitamente a qué campo de la base de
        datos corresponde cada una — funciona sin importar los nombres de
        las columnas del Excel."""
        p = self.get_current_page(e)
        if not p:
            return

        try:
            hojas = listar_hojas_excel(ruta_archivo)
        except Exception as ex:
            self.show_alert_error(e, f"Error al abrir el archivo Excel: {ex}")
            return

        hoja_actual = hoja_forzada or detectar_hoja_productos(ruta_archivo)
        if not hoja_actual and hojas:
            hoja_actual = hojas[0]
        if not hoja_actual:
            self.show_alert_error(e, "El archivo no tiene ninguna hoja legible.")
            return

        info = obtener_columnas_y_muestra(ruta_archivo, hoja_actual)
        columnas_excel = info["columnas"]
        muestra = info["muestra"]
        sugerido = sugerir_mapeo_columnas(columnas_excel)

        if not columnas_excel:
            self.show_alert_error(e, f"La hoja '{hoja_actual}' no tiene columnas.")
            return

        NO_IMPORTAR = ""
        opciones_columna = [ft.dropdown.Option(NO_IMPORTAR, "— No importar —")] + [
            ft.dropdown.Option(c, c) for c in columnas_excel
        ]

        lbl_muestra_por_campo: dict[str, ft.Text] = {}
        dd_por_campo: dict[str, ft.Dropdown] = {}

        def _texto_muestra(columna: str) -> str:
            valores = muestra.get(columna, [])
            if not valores:
                return "(sin datos de muestra)"
            return "Ej: " + ", ".join(v if v else "∅" for v in valores[:4])

        def _campo_mapeo_row(campo: str, etiqueta: str, obligatorio: bool) -> ft.Row:
            valor_inicial = sugerido.get(campo, NO_IMPORTAR)
            dd = ft.Dropdown(
                value=valor_inicial if valor_inicial in columnas_excel else NO_IMPORTAR,
                options=opciones_columna,
                width=240,
                border_radius=10,
                dense=True,
            )
            lbl_muestra = ft.Text(
                _texto_muestra(valor_inicial) if valor_inicial else "",
                size=11, color=self.get_subtext_color(), italic=True, expand=True,
            )

            def _on_change(ev, lbl=lbl_muestra):
                lbl.value = _texto_muestra(dd.value) if dd.value else ""
                p.update()

            dd.on_change = _on_change
            dd_por_campo[campo] = dd
            lbl_muestra_por_campo[campo] = lbl_muestra

            etiqueta_texto = f"{etiqueta} *" if obligatorio else etiqueta
            return ft.Row(
                controls=[
                    ft.Text(etiqueta_texto, size=13, weight=ft.FontWeight.BOLD if obligatorio else ft.FontWeight.NORMAL,
                             color=self.get_text_color(), width=180),
                    dd,
                    lbl_muestra,
                ],
                spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )

        filas_mapeo = [
            _campo_mapeo_row(campo, etiqueta, obligatorio)
            for campo, etiqueta, obligatorio in CAMPOS_PRODUCTO_MAPEO
        ]

        # ── Vista previa cruda del archivo (encabezados + primeras filas) ────
        # Deja ver el contenido real sin depender de que el usuario recuerde
        # los nombres de columna mientras completa el mapeo de arriba.
        preview_table = ft.DataTable(
            columns=[ft.DataColumn(ft.Text(c, weight=ft.FontWeight.BOLD, size=12)) for c in columnas_excel],
            rows=[
                ft.DataRow(cells=[
                    ft.DataCell(ft.Text(muestra[c][i] if i < len(muestra[c]) else "", size=12))
                    for c in columnas_excel
                ])
                for i in range(max((len(v) for v in muestra.values()), default=0))
            ],
            column_spacing=20,
        )
        preview_row = ft.Row(controls=[preview_table], scroll=ft.ScrollMode.AUTO)

        lbl_err = ft.Text("", color=ft.Colors.RED_500, size=12, weight=ft.FontWeight.BOLD)

        def _confirmar(ev):
            mapeo = {campo: dd_por_campo[campo].value for campo, *_ in CAMPOS_PRODUCTO_MAPEO if dd_por_campo[campo].value}
            if not mapeo.get("codigo"):
                lbl_err.value = "Debe mapear una columna al campo obligatorio 'Código'."
                p.update()
                return

            dlg.open = False
            p.update()

            analisis = analizar_proveedores_con_mapeo(ruta_archivo, hoja_actual, mapeo.get("proveedor"))
            if not analisis.get("exito"):
                self.show_alert_error(ev, analisis.get("mensaje"))
                return

            faltantes = analisis.get("proveedores_faltantes", [])
            if faltantes:
                self.mostrar_asistente_proveedores_faltantes(
                    ev, ruta_archivo, faltantes,
                    on_completado=lambda ev2: self.ejecutar_importacion_final_mapeada(ev2, ruta_archivo, hoja_actual, mapeo),
                )
            else:
                self.ejecutar_importacion_final_mapeada(ev, ruta_archivo, hoja_actual, mapeo)

        def _cancelar(ev):
            dlg.open = False
            p.update()

        def _cambiar_hoja(ev):
            dlg.open = False
            p.update()
            self.mostrar_asistente_mapeo(ev, ruta_archivo, hoja_forzada=dd_hoja.value)

        contenido = [
            ft.Text(
                f"Se detectaron {len(columnas_excel)} columnas en la hoja seleccionada. Indique a qué campo "
                "de la base de datos corresponde cada una (o déjelo en 'No importar'). El nombre de las "
                "columnas del archivo no importa — usted decide el mapeo.",
                size=12, color=self.get_subtext_color(),
            ),
        ]

        if len(hojas) > 1:
            dd_hoja = ft.Dropdown(
                label="Hoja del archivo a importar como Productos",
                value=hoja_actual,
                options=[ft.dropdown.Option(h) for h in hojas],
                width=320, border_radius=10,
            )
            dd_hoja.on_change = _cambiar_hoja
            contenido.append(dd_hoja)

        contenido += [
            ft.Divider(height=10),
            ft.Text("MAPEO DE COLUMNAS", size=12, weight=ft.FontWeight.BOLD, color=self.get_accent_color()),
            ft.Column(controls=filas_mapeo, spacing=6, scroll=ft.ScrollMode.AUTO, height=260),
            ft.Divider(height=10),
            ft.Row([
                ft.Text("VISTA PREVIA DEL ARCHIVO", size=12, weight=ft.FontWeight.BOLD, color=self.get_accent_color()),
                build_scroll_nav(preview_row, "horizontal", self.get_accent_color(), tooltip_prefix="Vista previa: "),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.Container(content=preview_row, padding=6, border_radius=10,
                         bgcolor=self.get_card_bg(), border=ft.Border.all(1, self.get_border_color())),
            lbl_err,
        ]

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.Icons.RULE_ROUNDED, color=self.get_accent_color()),
                ft.Text(f"Mapeo de Columnas — Hoja '{hoja_actual}'", weight=ft.FontWeight.BOLD),
            ], spacing=10),
            content=ft.Container(
                content=ft.Column(contenido, spacing=10, tight=True, scroll=ft.ScrollMode.AUTO),
                # Diálogo amplio: hay 11 campos a mapear + una vista previa
                # tabular del archivo, no caben cómodos en un modal chico.
                width=900,
                height=680,
            ),
            actions=[
                ft.TextButton("Cancelar", on_click=_cancelar),
                ft.Button(
                    content=ft.Row([ft.Icon(ft.Icons.PLAY_ARROW_ROUNDED), ft.Text("Confirmar Mapeo e Importar")], tight=True),
                    bgcolor=self.get_accent_color(), color=ft.Colors.WHITE,
                    style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=12)),
                    on_click=_confirmar,
                ),
            ],
        )

        if dlg not in p.overlay:
            p.overlay.append(dlg)
        dlg.open = True
        p.update()

    def mostrar_asistente_proveedores_faltantes(self, e, ruta_archivo, faltantes, idx=0, on_completado=None):
        """Muestra un diálogo dinámico secuencial para completar información
        de proveedores nuevos. Al terminar con todos, invoca `on_completado`
        (por defecto, la importación clásica por heurística de nombres de
        columna); el asistente de mapeo de columnas pasa aquí su propia
        continuación para usar el mapeo explícito que el usuario confirmó."""
        p = self.get_current_page(e)
        if not p:
            print(">>> [mostrar_asistente_proveedores_faltantes] ERROR: No se pudo obtener la instancia de Page activa.")
            return

        nombre_prov = faltantes[idx]
        total_faltantes = len(faltantes)
        print(f">>> [mostrar_asistente_proveedores_faltantes] Abriendo modal para proveedor '{nombre_prov}' ({idx + 1} de {total_faltantes})...")

        # Controles del formulario
        txt_empresa = ft.TextField(
            label="Razón Social / Empresa (Obligatorio)*", 
            value=nombre_prov, 
            disabled=True, 
            prefix_icon=ft.Icons.BUSINESS
        )
        txt_rif = ft.TextField(
            label="Cédula / RIF (Obligatorio)*", 
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

            if not rif:
                print(">>> [registrar_proveedor] ERROR: RIF vacío")
                lbl_error.value = "La Cédula / RIF es obligatoria."
                p.update()
                return

            if not empresa:
                print(">>> [registrar_proveedor] ERROR: Empresa vacía")
                lbl_error.value = "La Razón Social / Empresa es obligatoria."
                p.update()
                return

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
                    self.mostrar_asistente_proveedores_faltantes(e, ruta_archivo, faltantes, sig_idx, on_completado=on_completado)
                else:
                    print(">>> [registrar_proveedor] Todos los proveedores registrados. Procediendo a la importación final...")
                    self.show_alert_success(e, "Todos los proveedores nuevos se registraron correctamente.")
                    (on_completado or (lambda ev: self.ejecutar_importacion_final(ev, ruta_archivo)))(e)

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

    def ejecutar_importacion_final_mapeada(self, e, ruta_archivo, hoja_productos, mapeo):
        """Ejecuta la importación usando el mapeo de columnas explícito que el
        usuario confirmó en el asistente (services.ejecutar_importacion_completa_mapeada)."""
        try:
            print(f">>> [ejecutar_importacion_final_mapeada] hoja='{hoja_productos}' mapeo={mapeo}")
            with open("import_debug.log", "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now()}] Iniciando ejecutar_importacion_final_mapeada: hoja={hoja_productos} mapeo={mapeo}\n")

            res = ejecutar_importacion_completa_mapeada(ruta_archivo, hoja_productos, mapeo)

            with open("import_debug.log", "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now()}] Resultado de la importación mapeada: {res}\n")
            print(f">>> [ejecutar_importacion_final_mapeada] Resultado: {res}")

            if res.get("exito"):
                self.show_alert_success(e, res.get("mensaje"))
            else:
                self.mostrar_dialogo_error(e, res.get("mensaje"))
        except Exception as ex:
            import traceback
            err_msg = traceback.format_exc()
            with open("import_debug.log", "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now()}] EXCEPCIÓN EN IMPORTACIÓN MAPEADA: {err_msg}\n")
            print(f"\n>>> [ejecutar_importacion_final_mapeada] EXCEPCIÓN:\n{err_msg}")
            try:
                self.show_alert_error(e, f"Excepción crítica en importación: {str(ex)}")
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
                    precio_dolares AS [Precio USD (Efectivo)],
                    precio_bcv AS [Precio USD (BCV)],
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
