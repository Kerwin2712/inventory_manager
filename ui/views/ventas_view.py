import os
import flet as ft
from ui.views.base_view import BaseView
from core.database import get_setting, set_setting
from services.bcv_service import obtener_estado_tasa
from services.cartera_service import buscar_cliente_por_cedula
from services.inventario_service import listar_productos
from services.ventas_service import procesar_venta
from services.pdf_service import generar_nota_entrega_pdf


class VentasView(BaseView):
    def __init__(self, page: ft.Page = None, user_data: dict = None):
        self.user_data = user_data or {}
        self.carrito = []  # Lista de dicts con los ítems agregados
        self.cliente_seleccionado = None
        self.tipo_venta = "Formal"
        self.tasa_bcv = 0.0
        self.venta_id_reciente = None
        self.divisa_impresion_pdf = "USD"

        # Instanciar el FilePicker nativo antes del super().__init__
        self.file_picker = ft.FilePicker()
        self.file_picker.on_result = self.handle_pdf_save_result

        super().__init__(route="/ventas", title="Módulo de Ventas y Notas de Entrega")


        # Cargar tasa BCV actual
        estado_tasa = obtener_estado_tasa()
        self.tasa_bcv = estado_tasa.get("tasa", 0.0)

    def get_current_page(self, e=None):
        """Obtiene la instancia de page activa de forma segura."""
        if e and hasattr(e, "page") and e.page:
            return e.page
        if e and hasattr(e, "control") and hasattr(e.control, "page") and e.control.page:
            return e.control.page
        try:
            if self.page:
                return self.page
        except (RuntimeError, AttributeError):
            pass
        return None

    def safe_update(self, e=None):
        """Actualiza la interfaz evitando excepciones de renderizado."""
        p = self.get_current_page(e)
        if p:
            p.update()
        else:
            try:
                self.update()
            except (RuntimeError, AttributeError):
                pass

    def show_alert_success(self, e, msg: str):
        """Despliega una notificación flotante de éxito."""
        p = self.get_current_page(e)
        if p:
            s = ft.SnackBar(
                content=ft.Text(msg, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD),
                bgcolor=ft.Colors.GREEN_700,
                duration=3500
            )
            p.overlay.append(s)
            s.open = True
            p.update()

    def show_alert_error(self, e, msg: str):
        """Despliega una notificación flotante de error."""
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

    def ensure_file_picker_in_overlay(self, e=None) -> ft.FilePicker:
        """Garantiza de forma segura la reutilización del FilePicker en page.overlay."""
        p = self.get_current_page(e)
        if p and hasattr(p, "overlay"):
            for control in p.overlay:
                if isinstance(control, ft.FilePicker):
                    control.on_result = self.handle_pdf_save_result
                    self.file_picker = control
                    return control

            # Si por algún motivo no estuviera en overlay, se crea e inserta
            fp = ft.FilePicker()
            fp.on_result = self.handle_pdf_save_result
            p.overlay.append(fp)
            p.update()
            self.file_picker = fp
            return fp

        if not hasattr(self, "file_picker") or self.file_picker is None:
            self.file_picker = ft.FilePicker()
            self.file_picker.on_result = self.handle_pdf_save_result
        return self.file_picker


    def handle_pdf_save_result(self, e):
        """Procesa la selección de ubicación elegida en la ventana Guardar como."""
        if e.path and self.venta_id_reciente:
            try:
                ruta_guardada = generar_nota_entrega_pdf(
                    venta_id=self.venta_id_reciente,
                    divisa_impresion=self.divisa_impresion_pdf,
                    ruta_destino=e.path
                )
                # Extraer y guardar la carpeta seleccionada en SQLite
                directorio = os.path.dirname(e.path)
                if directorio:
                    set_setting("last_pdf_dir", directorio)

                self.show_alert_success(e, f"Nota de Entrega guardada exitosamente en:\n{e.path}")
            except Exception as ex:
                self.show_alert_error(e, f"Error al generar la Nota de Entrega PDF: {ex}")


    def get_body(self) -> ft.Control:
        self.ensure_file_picker_in_overlay()

        # ── 1. Cabecera: Selector de Tipo de Venta y Tasa BCV ────────────────
        self.tipo_venta_selector = ft.SegmentedButton(
            selected=["Formal"],
            segments=[

                ft.Segment(value="Formal", label=ft.Text("Venta Formal (Con Cliente)", weight=ft.FontWeight.BOLD), icon=ft.Icons.BUSINESS),
                ft.Segment(value="Informal", label=ft.Text("Venta Informal (Mostrador)", weight=ft.FontWeight.BOLD), icon=ft.Icons.STORE),
            ],
            on_change=self.handle_cambio_tipo_venta
        )

        tasa_badge = ft.Container(
            content=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.ATTACH_MONEY, color=ft.Colors.GREEN_600, size=20),
                    ft.Text(
                        f"Tasa BCV: {self.tasa_bcv:,.2f} Bs/$" if self.tasa_bcv > 0 else "Tasa BCV No Configurada",
                        weight=ft.FontWeight.BOLD,
                        color=self.get_text_color()
                    )
                ],
                tight=True
            ),
            bgcolor=self.get_card_bg(),
            padding=ft.Padding.symmetric(horizontal=12, vertical=8),
            border_radius=8,
            border=ft.Border.all(1, self.get_border_color())
        )



        cabecera_card = ft.Card(
            content=ft.Container(
                content=ft.Row(
                    controls=[self.tipo_venta_selector, tasa_badge],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    wrap=True
                ),
                padding=15
            ),
            bgcolor=self.get_card_bg()
        )

        # ── 2. Panel de Cliente (ERS 3.4) ────────────────────────────────────
        self.cli_search_input = ft.TextField(
            label="Cédula o RIF del Cliente",
            hint_text="Ej: V-12345678 o J-304567890",
            prefix_icon=ft.Icons.BADGE,
            expand=True,
            on_submit=self.handle_buscar_cliente
        )
        self.btn_buscar_cli = ft.Button(
            content=ft.Row([ft.Icon(ft.Icons.SEARCH), ft.Text("Buscar Cliente")]),
            on_click=self.handle_buscar_cliente
        )
        self.lbl_cliente_info = ft.Text(
            "Seleccione un cliente para la venta formal.",
            color=self.get_subtext_color(),
            weight=ft.FontWeight.BOLD
        )

        self.panel_cliente_container = ft.Card(
            content=ft.Container(
                content=ft.Column([
                    ft.Text("DATOS DEL CLIENTE", size=14, weight=ft.FontWeight.BOLD, color=self.get_accent_color()),
                    ft.Row([self.cli_search_input, self.btn_buscar_cli]),
                    self.lbl_cliente_info
                ], spacing=10),
                padding=15
            ),
            bgcolor=self.get_card_bg(),
            visible=True
        )

        # ── 3. Panel de Selección e Inserción de Productos ───────────────────
        self.prod_search_input = ft.TextField(
            label="Código o Nombre del Producto",
            hint_text="Ingrese el código de barras o referencia corta",
            prefix_icon=ft.Icons.QR_CODE_SCANNER,
            expand=True,
            on_submit=self.handle_agregar_producto
        )
        self.cant_input = ft.TextField(
            label="Cant.",
            value="1",
            width=90,
            keyboard_type=ft.KeyboardType.NUMBER,
            text_align=ft.TextAlign.CENTER
        )
        self.btn_agregar_prod = ft.Button(
            content=ft.Row([ft.Icon(ft.Icons.ADD_SHOPPING_CART), ft.Text("Agregar")]),
            on_click=self.handle_agregar_producto
        )

        panel_agregar_prod = ft.Card(
            content=ft.Container(
                content=ft.Column([
                    ft.Text("BÚSQUEDA Y SELECCIÓN DE ARTÍCULOS", size=14, weight=ft.FontWeight.BOLD, color=self.get_accent_color()),
                    ft.Row([self.prod_search_input, self.cant_input, self.btn_agregar_prod], alignment=ft.MainAxisAlignment.START)
                ], spacing=10),
                padding=15
            ),
            bgcolor=self.get_card_bg()
        )

        # ── 4. Carrito de Compras (Tabla de Ítems) ───────────────────────────
        self.tabla_carrito_container = ft.Container(
            content=self.build_tabla_carrito(),
            expand=True
        )

        # ── 5. Panel de Totales Bimoneda y Botón de Procesar ─────────────────
        self.lbl_subtotal_usd = ft.Text("$ 0.00", size=15, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_600)
        self.lbl_subtotal_bcv = ft.Text("Bs. 0.00", size=15, weight=ft.FontWeight.BOLD, color=ft.Colors.AMBER_700)
        self.lbl_total_usd = ft.Text("$ 0.00", size=18, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_700)
        self.lbl_total_bcv = ft.Text("Bs. 0.00", size=18, weight=ft.FontWeight.BOLD, color=ft.Colors.AMBER_800)

        panel_totales = ft.Card(
            content=ft.Container(
                content=ft.Column([
                    ft.Text("RESUMEN DE VENTA", size=14, weight=ft.FontWeight.BOLD, color=self.get_accent_color()),
                    ft.Divider(),
                    ft.Row([ft.Text("Subtotal ($):", weight=ft.FontWeight.BOLD, color=self.get_text_color()), self.lbl_subtotal_usd], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    ft.Row([ft.Text("Subtotal (Bs):", weight=ft.FontWeight.BOLD, color=self.get_text_color()), self.lbl_subtotal_bcv], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    ft.Divider(),
                    ft.Row([ft.Text("TOTAL A PAGAR ($):", size=16, weight=ft.FontWeight.BOLD, color=self.get_text_color()), self.lbl_total_usd], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    ft.Row([ft.Text("TOTAL A PAGAR (Bs):", size=16, weight=ft.FontWeight.BOLD, color=self.get_text_color()), self.lbl_total_bcv], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    ft.Container(height=10),
                    ft.Button(
                        content=ft.Container(
                            content=ft.Row([
                                ft.Icon(ft.Icons.POINT_OF_SALE, size=24, color=ft.Colors.WHITE),
                                ft.Text("PROCESAR VENTA", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE)
                            ], alignment=ft.MainAxisAlignment.CENTER),
                            padding=10
                        ),
                        on_click=self.handle_procesar_venta,
                        style=ft.ButtonStyle(
                            bgcolor=ft.Colors.BLUE_700,
                            shape=ft.RoundedRectangleBorder(radius=8)
                        )
                    )

                ], spacing=8),
                padding=15
            ),
            bgcolor=self.get_card_bg(),
            width=360
        )

        row_carrito_totales = ft.Row(
            controls=[
                self.tabla_carrito_container,
                panel_totales
            ],
            vertical_alignment=ft.CrossAxisAlignment.START,
            alignment=ft.MainAxisAlignment.START,
            spacing=15
        )

        columna_derecha = ft.Column(
            controls=[
                panel_agregar_prod,
                row_carrito_totales
            ],
            spacing=15
        )

        return ft.Container(
            content=ft.Column(
                controls=[cabecera_card, self.panel_cliente_container, columna_derecha],
                spacing=15,
                scroll=ft.ScrollMode.AUTO,
                expand=True
            ),
            padding=15,
            expand=True
        )


    # ── Manejadores de Eventos y Lógica de Negocio ───────────────────────────

    def handle_cambio_tipo_venta(self, e):
        """Conmuta entre Venta Formal e Informal."""
        val = list(e.control.selected)[0] if e.control.selected else "Formal"
        self.tipo_venta = val
        e.control.selected = [val]
        if val == "Informal":
            self.panel_cliente_container.visible = False
            self.cliente_seleccionado = None
        else:
            self.panel_cliente_container.visible = True
        self.safe_update(e)


    def handle_buscar_cliente(self, e):
        """Busca un cliente por su Cédula/RIF."""
        query = self.cli_search_input.value or ""
        if not query.strip():
            self.show_alert_error(e, "Ingrese una Cédula o RIF para buscar.")
            return

        cliente = buscar_cliente_por_cedula(query)
        if cliente:
            self.cliente_seleccionado = cliente
            self.lbl_cliente_info.value = f"✓ Cliente Seleccionado: {cliente['nombre']} ({cliente['cedula_rif']}) - {cliente.get('telefono', '')}"
            self.lbl_cliente_info.color = ft.Colors.GREEN_600
            self.show_alert_success(e, f"Cliente '{cliente['nombre']}' encontrado.")
        else:
            self.cliente_seleccionado = None
            self.lbl_cliente_info.value = f"✗ No se encontró ningún cliente con '{query}'. Registre el cliente en el módulo de Cartera."
            self.lbl_cliente_info.color = ft.Colors.RED_600
            self.show_alert_error(e, f"El cliente '{query}' no está registrado en la base de datos.")

        self.safe_update(e)

    def handle_agregar_producto(self, e):
        """Busca un producto por código y lo agrega al carrito de compras."""
        codigo_query = (self.prod_search_input.value or "").strip()
        if not codigo_query:
            self.show_alert_error(e, "Ingrese un código de producto.")
            return

        try:
            cant_deseada = float(self.cant_input.value or "1")
            if cant_deseada <= 0:
                raise ValueError()
        except ValueError:
            self.show_alert_error(e, "La cantidad debe ser un número entero o decimal mayor a cero.")
            return

        # Consultar productos por código
        prods = listar_productos(busqueda=codigo_query)
        prod_encontrado = None

        for p in prods:
            if p["codigo"].upper() == codigo_query.upper() or (p.get("codigo_barras") and p["codigo_barras"].upper() == codigo_query.upper()):
                prod_encontrado = p
                break

        if not prod_encontrado and prods:
            prod_encontrado = prods[0]

        if not prod_encontrado:
            self.show_alert_error(e, f"No existe ningún producto con el código '{codigo_query}'.")
            return

        # Verificar existencia disponible
        stock_disponible = float(prod_encontrado["existencia"])
        
        # Verificar cuánto de este producto ya está en el carrito
        cant_en_carrito = sum(item["cantidad"] for item in self.carrito if item["codigo"] == prod_encontrado["codigo"])
        cant_total_requerida = cant_en_carrito + cant_deseada

        if cant_total_requerida > stock_disponible:
            self.show_alert_error(
                e,
                f"Stock insuficiente para {prod_encontrado['codigo']}.\n"
                f"Existencia en almacén: {stock_disponible:.2f} | En carrito: {cant_en_carrito:.2f} | Solicitado: {cant_deseada:.2f}"
            )
            return

        # Agregar o actualizar ítem en el carrito
        item_existente = next((item for item in self.carrito if item["codigo"] == prod_encontrado["codigo"]), None)
        precio_usd = float(prod_encontrado["precio_dolares"])
        precio_bcv = float(prod_encontrado["precio_bcv"])

        if item_existente:
            item_existente["cantidad"] += cant_deseada
            item_existente["subtotal_usd"] = item_existente["cantidad"] * precio_usd
            item_existente["subtotal_bcv"] = item_existente["cantidad"] * precio_bcv
        else:
            self.carrito.append({
                "codigo": prod_encontrado["codigo"],
                "nombre_corto": prod_encontrado["nombre_referencia_corto"] or prod_encontrado["referencia"],
                "cantidad": cant_deseada,
                "precio_usd": precio_usd,
                "precio_bcv": precio_bcv,
                "subtotal_usd": cant_deseada * precio_usd,
                "subtotal_bcv": cant_deseada * precio_bcv
            })

        self.prod_search_input.value = ""
        self.cant_input.value = "1"
        self.actualizar_carrito_y_totales()
        self.show_alert_success(e, f"Producto '{prod_encontrado['nombre_referencia_corto']}' agregado al carrito.")
        self.safe_update(e)

    def handle_remover_item(self, e, codigo):
        """Elimina un producto del carrito de compras."""
        self.carrito = [item for item in self.carrito if item["codigo"] != codigo]
        self.actualizar_carrito_y_totales()
        self.safe_update(e)

    def actualizar_carrito_y_totales(self):
        """Recalcula subtotales y reconstruye la vista del carrito."""
        tot_usd = sum(item["subtotal_usd"] for item in self.carrito)
        tot_bcv = sum(item["subtotal_bcv"] for item in self.carrito)

        self.lbl_subtotal_usd.value = f"$ {tot_usd:,.2f}"
        self.lbl_subtotal_bcv.value = f"Bs. {tot_bcv:,.2f}"
        self.lbl_total_usd.value = f"$ {tot_usd:,.2f}"
        self.lbl_total_bcv.value = f"Bs. {tot_bcv:,.2f}"

        self.tabla_carrito_container.content = self.build_tabla_carrito()

    def build_tabla_carrito( me ) -> ft.Control:
        """Construye la tarjeta y tabla DataTable del carrito de compras."""
        if not me.carrito:
            return ft.Card(
                content=ft.Container(
                    content=ft.Column([
                        ft.Icon(ft.Icons.SHOPPING_CART_OUTLINED, size=56, color=me.get_accent_color()),
                        ft.Text("CARRITO DE COMPRAS VACÍO", size=15, weight=ft.FontWeight.BOLD, color=me.get_text_color()),
                        ft.Text("Busque un producto arriba e ingrese la cantidad deseada para añadir renglones a la venta.", size=13, color=me.get_subtext_color(), text_align=ft.TextAlign.CENTER)
                    ], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=8),
                    padding=35,
                    alignment=ft.Alignment.CENTER
                ),
                bgcolor=me.get_card_bg()
            )

        filas = []
        for item in me.carrito:
            cod = item["codigo"]
            filas.append(
                ft.DataRow(cells=[
                    ft.DataCell(ft.Text(item["codigo"], weight=ft.FontWeight.BOLD, color=me.get_text_color())),
                    ft.DataCell(ft.Text(item["nombre_corto"], color=me.get_text_color())),
                    ft.DataCell(ft.Text(f"{item['cantidad']:.2f}", color=me.get_text_color())),
                    ft.DataCell(ft.Text(f"$ {item['precio_usd']:,.2f}", color=ft.Colors.GREEN_600, weight=ft.FontWeight.BOLD)),
                    ft.DataCell(ft.Text(f"Bs. {item['precio_bcv']:,.2f}", color=ft.Colors.AMBER_700, weight=ft.FontWeight.BOLD)),
                    ft.DataCell(ft.Text(f"$ {item['subtotal_usd']:,.2f}", weight=ft.FontWeight.BOLD, color=me.get_accent_color())),
                    ft.DataCell(
                        ft.IconButton(
                            icon=ft.Icons.DELETE_OUTLINED,
                            icon_color=ft.Colors.RED_400,
                            tooltip="Remover ítem",
                            on_click=lambda e, c=cod: me.handle_remover_item(e, c)
                        )
                    )
                ])
            )

        return ft.Card(
            content=ft.Container(
                content=ft.Column([
                    ft.Text(f"CARRITO DE COMPRAS ({len(me.carrito)} renglones)", size=14, weight=ft.FontWeight.BOLD, color=me.get_accent_color()),
                    ft.Row(
                        controls=[
                            ft.DataTable(
                                columns=[
                                    ft.DataColumn(ft.Text("Código", color=me.get_text_color())),
                                    ft.DataColumn(ft.Text("Producto (Nombre Corto)", color=me.get_text_color())),
                                    ft.DataColumn(ft.Text("Cant.", color=me.get_text_color())),
                                    ft.DataColumn(ft.Text("P. Unit ($)", color=me.get_text_color())),
                                    ft.DataColumn(ft.Text("P. Unit (Bs)", color=me.get_text_color())),
                                    ft.DataColumn(ft.Text("Subtotal ($)", color=me.get_text_color())),
                                    ft.DataColumn(ft.Text("Acciones", color=me.get_text_color())),
                                ],
                                rows=filas,
                                heading_row_color=me.get_card_bg()
                            )
                        ],
                        scroll=ft.ScrollMode.AUTO
                    )
                ], spacing=10),
                padding=15
            ),
            bgcolor=me.get_card_bg()
        )


    # ── 5. Procesamiento de Venta & Diálogo PDF (ERS 3.5) ─────────────────────

    def handle_procesar_venta(self, e):
        """Ejecuta la transacción ACID procesar_venta y despliega el diálogo de PDF."""
        if not self.carrito:
            self.show_alert_error(e, "No puede procesar una venta sin artículos en el carrito.")
            return

        cliente_id = None
        if self.tipo_venta == "Formal":
            if not self.cliente_seleccionado:
                self.show_alert_error(e, "Debe buscar y seleccionar un cliente registrado para realizar una Venta Formal.")
                return
            cliente_id = self.cliente_seleccionado["cedula_rif"]

        # Preparar renglones de la venta
        lineas = []
        for item in self.carrito:
            lineas.append({
                "producto_codigo": item["codigo"],
                "cantidad": item["cantidad"],
                "precio_unitario_usd": item["precio_usd"],
                "precio_unitario_bcv": item["precio_bcv"],
                "subtotal_usd": item["subtotal_usd"],
                "subtotal_bcv": item["subtotal_bcv"]
            })

        try:
            # Invocar motor transaccional ERS 3.4
            resultado = procesar_venta(
                tipo_venta=self.tipo_venta,
                cliente_id=cliente_id,
                lineas=lineas
            )

            self.venta_id_reciente = resultado["venta_id"]

            # Limpiar carrito y campos
            self.carrito.clear()
            self.cliente_seleccionado = None
            if hasattr(self, "cli_search_input"):
                self.cli_search_input.value = ""
            if hasattr(self, "lbl_cliente_info"):
                self.lbl_cliente_info.value = "Seleccione un cliente para la venta formal."
                self.lbl_cliente_info.color = self.get_subtext_color()

            self.actualizar_carrito_y_totales()

            self.show_alert_success(e, f"¡Venta N° {self.venta_id_reciente:06d} registrada exitosamente con COMMIT ACID!")

            # Abrir diálogo para generar e imprimir Nota de Entrega PDF (ERS 3.5)
            self.mostrar_dialogo_pdf(e)

        except ValueError as ve:
            self.show_alert_error(e, str(ve))
        except Exception as ex:
            self.show_alert_error(e, f"Error inesperado al procesar la venta: {ex}")

    def mostrar_dialogo_pdf(self, e):
        """Despliega el diálogo de confirmación para guardar/imprimir Nota de Entrega PDF."""
        dd_divisa = ft.Dropdown(
            label="Divisa de Impresión (ERS 3.5)",
            value="USD",
            options=[
                ft.dropdown.Option("USD", "Dólares ($)"),
                ft.dropdown.Option("BCV", "Bolívares (Bs. BCV)")
            ],
            width=220
        )

        def cerrar_dialogo(e_dialog):
            dialog.open = False
            self.safe_update(e_dialog)

        def confirmar_generar_pdf(e_dialog):
            self.divisa_impresion_pdf = dd_divisa.value or "USD"
            dialog.open = False
            self.safe_update(e_dialog)

            # Recuperar última ruta guardada de SQLite (app_settings)
            last_dir = get_setting("last_pdf_dir", default=None)
            if last_dir and not os.path.exists(last_dir):
                last_dir = None

            # Abrir cuadro de diálogo nativo de Windows "Guardar como"
            fp = self.ensure_file_picker_in_overlay(e_dialog)
            p = self.get_current_page(e_dialog)

            kwargs_save = {
                "dialog_title": "Guardar Nota de Entrega PDF",
                "file_name": f"Nota_Entrega_{self.venta_id_reciente}.pdf",
                "initial_directory": last_dir,
                "allowed_extensions": ["pdf"]
            }

            if p and hasattr(p, "run_task"):
                p.run_task(fp.save_file, **kwargs_save)
            else:
                try:
                    fp.save_file(**kwargs_save)
                except Exception as ex:
                    print(f"[ERROR] No se pudo lanzar FilePicker.save_file: {ex}")




        dialog = ft.AlertDialog(
            title=ft.Row([ft.Icon(ft.Icons.PICTURE_AS_PDF, color=ft.Colors.RED_600), ft.Text("¿Generar Nota de Entrega PDF?")]),
            content=ft.Column([
                ft.Text(f"La venta N° {self.venta_id_reciente:06d} ha sido procesada con éxito."),
                ft.Text("Seleccione la divisa para reflejar los precios en el documento impreso:"),
                dd_divisa
            ], tight=True, spacing=10),
            actions=[
                ft.TextButton("No - Finalizar", on_click=cerrar_dialogo),
                ft.Button("Sí - Guardar PDF", on_click=confirmar_generar_pdf, style=ft.ButtonStyle(bgcolor=ft.Colors.GREEN_700, color=ft.Colors.WHITE))
            ],
            actions_alignment=ft.MainAxisAlignment.END
        )

        p = self.get_current_page(e)
        if p:
            if dialog not in p.overlay:
                p.overlay.append(dialog)
            dialog.open = True
            p.update()

