import os
import re
import tkinter as tk
from tkinter import filedialog
import flet as ft
from ui.views.base_view import BaseView
from core.database import get_setting, set_setting
from services.bcv_service import obtener_estado_tasa
from services.cartera_service import buscar_cliente_por_cedula, crear_cliente
from services.inventario_service import listar_productos
from services.ventas_service import procesar_venta
from services.pdf_service import generar_nota_entrega_pdf, enviar_a_impresora
from services.cart_manager import (
    obtener_todos_los_carritos,
    obtener_id_carrito_activo,
    obtener_carrito_activo,
    cambiar_carrito_activo,
    crear_nuevo_carrito,
    eliminar_carrito,
    vincular_cliente_a_carrito,
    desvincular_cliente,
    agregar_o_actualizar_producto,
    editar_item_en_carrito,
    remover_item_de_carrito,
    vaciar_carrito_activo
)

# ERS 3.4: formato exigido para la Venta Formal — [V-00.000.000 ó J-00000000-0].
# Letra de nacionalidad/tipo (V/E/J/G/P) + guion + dígitos (agrupados con
# puntos o corridos) + dígito verificador opcional con guion (RIF).
_PATRON_CEDULA_RIF = re.compile(r"^[VEJGPvejgp]-(\d{6,9}|\d{1,3}(\.\d{3}){1,3})(-\d)?$")


def _formato_cedula_rif_valido(texto: str) -> bool:
    """Valida el formato de Cédula/RIF exigido por el ERS 3.4 antes de buscar."""
    return bool(_PATRON_CEDULA_RIF.match((texto or "").strip()))


class VentasView(BaseView):
    def __init__(self, page: ft.Page = None, user_data: dict = None):
        self.user_data = user_data or {}
        self.venta_id_reciente = None
        self.divisa_impresion_pdf = "USD"

        super().__init__(route="/ventas", title="Módulo de Ventas y Notas de Entrega")

        # Cargar estado de la Tasa BCV
        self.actualizar_estado_tasa_local()

    def actualizar_estado_tasa_local(self):
        """Actualiza el estado de la tasa BCV desde la persistencia SQLite."""
        estado = obtener_estado_tasa()
        self.tasa_bcv = estado.get("tasa", 0.0)
        self.tasa_antiguedad = estado.get("descripcion", "Sin tasa configurada")

    def abrir_dialogo_guardado(self, initial_dir: str, sugerencia_nombre: str) -> str:
        """Abre un cuadro de diálogo nativo de Windows (Tkinter) para seleccionar dónde guardar el PDF."""
        root = tk.Tk()
        root.attributes("-topmost", True)
        root.withdraw()
        ruta = filedialog.asksaveasfilename(
            initialdir=initial_dir,
            initialfile=sugerencia_nombre,
            title="Guardar Nota de Entrega",
            defaultextension=".pdf",
            filetypes=[("Archivos PDF", "*.pdf")]
        )
        root.destroy()
        return ruta

    def get_body(self) -> ft.Control:
        self.actualizar_estado_tasa_local()
        carrito_activo = obtener_carrito_activo()

        # ── 1. Cabecera: Selector de Carrito, Selector Tipo Venta y Tasa BCV ──
        carritos_dict = obtener_todos_los_carritos()
        options_carritos = [ft.dropdown.Option(cid, cinfo["nombre"]) for cid, cinfo in carritos_dict.items()]

        self.dd_carritos = ft.Dropdown(
            label="Carrito Activo",
            value=obtener_id_carrito_activo(),
            options=options_carritos,
            width=200,
            border_radius=12,
        )
        self.dd_carritos.on_change = self.handle_cambiar_carrito

        btn_nuevo_carrito = ft.IconButton(
            icon=ft.Icons.ADD_SHOPPING_CART,
            icon_color=self.get_accent_color(),
            tooltip="Crear Nuevo Carrito Simultáneo",
            on_click=self.handle_crear_nuevo_carrito
        )

        btn_eliminar_carrito = ft.IconButton(
            icon=ft.Icons.DELETE_OUTLINED,
            icon_color=ft.Colors.RED_400,
            tooltip="Eliminar Carrito Activo",
            on_click=self.handle_eliminar_carrito_activo
        )

        self.tipo_venta_selector = ft.SegmentedButton(
            selected=[carrito_activo.get("tipo_venta", "Formal")],
            segments=[
                ft.Segment(value="Formal", label=ft.Text("Venta Formal", weight=ft.FontWeight.BOLD), icon=ft.Icons.BUSINESS),
                ft.Segment(value="Informal", label=ft.Text("Venta Mostrador", weight=ft.FontWeight.BOLD), icon=ft.Icons.STORE),
            ],
            on_change=self.handle_cambio_tipo_venta
        )

        # Badge interactivo de Tasa BCV con Antigüedad
        tasa_badge = ft.Container(
            content=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.CURRENCY_EXCHANGE, color=ft.Colors.GREEN_600, size=20),
                    ft.Column([
                        ft.Text(
                            f"Tasa BCV: {self.tasa_bcv:,.2f} Bs/$" if self.tasa_bcv > 0 else "Tasa BCV No Configurada",
                            weight=ft.FontWeight.BOLD,
                            size=13,
                            color=self.get_text_color()
                        ),
                        ft.Text(self.tasa_antiguedad, size=10, color=self.get_subtext_color())
                    ], spacing=0),
                    ft.IconButton(
                        icon=ft.Icons.REFRESH_ROUNDED,
                        icon_color=self.get_accent_color(),
                        tooltip="Actualizar Tasa BCV",
                        on_click=lambda e: self.mostrar_modal_tasa_bcv(e, callback_al_guardar=self.on_tasa_actualizada)
                    )
                ],
                tight=True,
                spacing=8
            ),
            bgcolor=self.get_card_bg(),
            padding=ft.Padding.symmetric(horizontal=12, vertical=6),
            border_radius=12,
            border=ft.Border.all(1, self.get_border_color())
        )

        cabecera_card = self.create_card(
            content=ft.Row(
                controls=[
                    ft.Row([self.dd_carritos, btn_nuevo_carrito, btn_eliminar_carrito], spacing=5),
                    self.tipo_venta_selector,
                    tasa_badge
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                wrap=True
            ),
            padding=12,
            border_radius=16
        )

        # ── 2. Panel de Cliente (Venta Formal) ────────────────────────────────
        cliente_actual = carrito_activo.get("cliente")
        self.cli_search_input = ft.TextField(
            label="Cédula o RIF del Cliente",
            hint_text="Ej: V-12345678 o J-304567890",
            prefix_icon=ft.Icons.BADGE,
            border_radius=12,
            expand=True,
            on_submit=self.handle_buscar_cliente
        )
        self.btn_buscar_cli = ft.Button(
            content=ft.Row([ft.Icon(ft.Icons.SEARCH), ft.Text("Buscar Cliente", weight=ft.FontWeight.BOLD)]),
            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=12)),
            on_click=self.handle_buscar_cliente
        )

        if cliente_actual:
            lbl_texto_cli = f"✓ Cliente Seleccionado: {cliente_actual['nombre']} ({cliente_actual['cedula_rif']}) - Tel: {cliente_actual.get('telefono', '-')}"
            lbl_color_cli = ft.Colors.GREEN_600
        else:
            lbl_texto_cli = "Seleccione un cliente registrado para la Venta Formal."
            lbl_color_cli = self.get_subtext_color()

        self.lbl_cliente_info = ft.Text(lbl_texto_cli, color=lbl_color_cli, weight=ft.FontWeight.BOLD)

        btn_desvincular = ft.TextButton(
            "Cambiar / Desvincular Cliente",
            icon=ft.Icons.PERSON_REMOVE,
            visible=bool(cliente_actual),
            on_click=self.handle_desvincular_cliente
        )

        self.panel_cliente_container = self.create_card(
            content=ft.Column([
                ft.Row([
                    ft.Text("DATOS DEL CLIENTE (VENTA FORMAL)", size=13, weight=ft.FontWeight.BOLD, color=self.get_accent_color()),
                    btn_desvincular
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Row([self.cli_search_input, self.btn_buscar_cli]),
                self.lbl_cliente_info
            ], spacing=8),
            padding=12,
            border_radius=16
        )
        self.panel_cliente_container.visible = (carrito_activo.get("tipo_venta") == "Formal")

        # ── 3. Panel de Búsqueda Multicriterio e Inserción de Productos ──────
        self.criterio_busqueda_dd = ft.Dropdown(
            label="Buscar por",
            value="Todos",
            width=140,
            border_radius=12,
            options=[
                ft.dropdown.Option("Todos"),
                ft.dropdown.Option("Código"),
                ft.dropdown.Option("Nombre/Ref"),
                ft.dropdown.Option("Departamento"),
                ft.dropdown.Option("Marca"),
            ]
        )

        self.prod_search_input = ft.TextField(
            label="Buscar o Escanear Producto",
            hint_text="Ingrese nombre, código de barras o referencia...",
            prefix_icon=ft.Icons.QR_CODE_SCANNER,
            border_radius=12,
            expand=True,
            on_submit=self.handle_agregar_producto
        )
        self.cant_input = ft.TextField(
            label="Cant.",
            value="1",
            width=90,
            keyboard_type=ft.KeyboardType.NUMBER,
            text_align=ft.TextAlign.CENTER,
            border_radius=12,
        )
        self.btn_agregar_prod = ft.Button(
            content=ft.Row([ft.Icon(ft.Icons.ADD_SHOPPING_CART), ft.Text("Agregar", weight=ft.FontWeight.BOLD)]),
            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=12)),
            on_click=self.handle_agregar_producto
        )
        self.btn_buscar_inventario = ft.OutlinedButton(
            content=ft.Row([ft.Icon(ft.Icons.INVENTORY_2_OUTLINED), ft.Text("Buscar en Inventario", weight=ft.FontWeight.BOLD)]),
            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=12)),
            tooltip="Abrir el inventario con filtros para seleccionar un producto (ERS 3.3 — Flujo Inverso)",
            on_click=self.abrir_modal_buscar_inventario
        )

        # ── Panel de Recomendaciones Rápidas (Productos Frecuentes) ───────────
        prods_recomendados = listar_productos(per_page=6)
        chips_recomendaciones = []
        for pr in prods_recomendados:
            nombre_c = pr.get("nombre_referencia_corto") or pr.get("referencia") or pr["codigo"]
            precio_str = f"${pr['precio_dolares']:.2f}"
            chips_recomendaciones.append(
                ft.Container(
                    content=ft.Row([
                        ft.Icon(ft.Icons.ADD_CIRCLE_OUTLINE, size=14, color=self.get_accent_color()),
                        ft.Text(f"{nombre_c} ({precio_str})", size=11, weight=ft.FontWeight.BOLD, color=self.get_text_color())
                    ], tight=True, spacing=4),
                    padding=ft.Padding.symmetric(horizontal=10, vertical=6),
                    border_radius=20,
                    bgcolor=self.get_card_bg(),
                    border=ft.Border.all(1, self.get_border_color()),
                    on_click=lambda e, p=pr: self.agregar_producto_directo(p, 1.0, e),
                    ink=True,
                    tooltip=f"Haga clic para añadir 1 unidad de {nombre_c} al carrito"
                )
            )

        panel_recomendaciones = ft.Column([
            ft.Text("💡 Recomendaciones Rápidas (Click para añadir 1 Ud):", size=11, color=self.get_subtext_color(), weight=ft.FontWeight.W_600),
            ft.Row(controls=chips_recomendaciones, wrap=True, spacing=6)
        ], spacing=4) if chips_recomendaciones else ft.Container()

        panel_agregar_prod = self.create_card(
            content=ft.Column([
                ft.Text("BÚSQUEDA Y SELECCIÓN DE ARTÍCULOS", size=13, weight=ft.FontWeight.BOLD, color=self.get_accent_color()),
                ft.Row([self.criterio_busqueda_dd, self.prod_search_input, self.cant_input, self.btn_agregar_prod, self.btn_buscar_inventario], alignment=ft.MainAxisAlignment.START, wrap=True),
                panel_recomendaciones
            ], spacing=10),
            padding=15,
            border_radius=16
        )

        # ── 4. Carrito de Compras (Tabla de Ítems Renglones) ──────────────────
        self.tabla_carrito_container = ft.Container(
            content=self.build_tabla_carrito(carrito_activo["items"]),
            expand=True
        )

        # ── 5. Resumen de Venta Bimoneda Detallado ─────────────────────────────
        tot_usd = sum(item["subtotal_usd"] for item in carrito_activo["items"])
        tot_bcv = sum(item["subtotal_bcv"] for item in carrito_activo["items"])

        self.lbl_subtotal_usd = ft.Text(f"$ {tot_usd:,.2f}", size=14, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_600)
        self.lbl_subtotal_bcv = ft.Text(f"Bs. {tot_bcv:,.2f}", size=14, weight=ft.FontWeight.BOLD, color=ft.Colors.AMBER_700)
        
        # Desglose en USD Efectivo vs USD Pago en Bs
        self.lbl_total_usd_efectivo = ft.Text(f"$ {tot_usd:,.2f}", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_700)
        self.lbl_total_usd_pago_bs = ft.Text(f"$ {tot_usd:,.2f}", size=14, weight=ft.FontWeight.W_600, color=self.get_subtext_color())
        self.lbl_total_bcv = ft.Text(f"Bs. {tot_bcv:,.2f}", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.AMBER_800)
        self.lbl_antiguedad_resumen = ft.Text(f"Tasa: {self.tasa_bcv:,.2f} Bs/$ ({self.tasa_antiguedad})", size=10, color=self.get_subtext_color())

        panel_totales = self.create_card(
            content=ft.Column([
                ft.Text("RESUMEN DE VENTA", size=14, weight=ft.FontWeight.BOLD, color=self.get_accent_color()),
                ft.Divider(height=6),
                ft.Row([ft.Text("Subtotal ($):", weight=ft.FontWeight.BOLD, color=self.get_text_color()), self.lbl_subtotal_usd], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Row([ft.Text("Subtotal (Bs):", weight=ft.FontWeight.BOLD, color=self.get_text_color()), self.lbl_subtotal_bcv], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Divider(height=6),
                ft.Row([ft.Text("Total $ (Efectivo):", size=15, weight=ft.FontWeight.BOLD, color=self.get_text_color()), self.lbl_total_usd_efectivo], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Row([ft.Text("Total $ (Pago en Bs):", size=13, color=self.get_subtext_color()), self.lbl_total_usd_pago_bs], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Row([ft.Text("TOTAL A PAGAR (Bs):", size=15, weight=ft.FontWeight.BOLD, color=self.get_text_color()), self.lbl_total_bcv], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Row([self.lbl_antiguedad_resumen], alignment=ft.MainAxisAlignment.END),
                ft.Container(height=8),
                ft.Button(
                    content=ft.Container(
                        content=ft.Row([
                            ft.Icon(ft.Icons.POINT_OF_SALE, size=22, color=ft.Colors.WHITE),
                            ft.Text("PROCESAR VENTA", size=15, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE)
                        ], alignment=ft.MainAxisAlignment.CENTER),
                        padding=8
                    ),
                    on_click=self.handle_procesar_venta,
                    style=ft.ButtonStyle(
                        bgcolor=ft.Colors.BLUE_700,
                        shape=ft.RoundedRectangleBorder(radius=12)
                    )
                )
            ], spacing=6),
            padding=15,
            border_radius=16
        )
        panel_totales.width = 370

        row_carrito_totales = ft.Row(
            controls=[self.tabla_carrito_container, panel_totales],
            vertical_alignment=ft.CrossAxisAlignment.START,
            alignment=ft.MainAxisAlignment.START,
            spacing=15
        )

        columna_derecha = ft.Column(
            controls=[panel_agregar_prod, row_carrito_totales],
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

    # ── Manejadores de Eventos de Carrito y Tasa ──────────────────────────────

    def on_tasa_actualizada(self, nueva_tasa: float):
        """Callback invocado al actualizar la tasa BCV en el modal global."""
        self.actualizar_estado_tasa_local()
        # Recalcular precios en bolívares de los renglones
        c = obtener_carrito_activo()
        for item in c["items"]:
            item["precio_bcv"] = round(item["precio_usd"] * self.tasa_bcv, 2)
            item["subtotal_bcv"] = round(item["cantidad"] * item["precio_bcv"], 2)
        self.rebuild_ui()

    def handle_cambiar_carrito(self, e):
        cid = e.control.value
        cambiar_carrito_activo(cid)
        self.rebuild_ui()

    def handle_crear_nuevo_carrito(self, e):
        c_nuevo = crear_nuevo_carrito()
        self.show_alert_success(e, f"¡Creado nuevo '{c_nuevo['nombre']}'!")
        self.rebuild_ui()

    def handle_eliminar_carrito_activo(self, e):
        cid = obtener_id_carrito_activo()
        eliminar_carrito(cid)
        self.show_alert_success(e, f"Carrito '{cid}' eliminado.")
        self.rebuild_ui()

    def handle_cambio_tipo_venta(self, e):
        val = list(e.control.selected)[0] if e.control.selected else "Formal"
        c = obtener_carrito_activo()
        c["tipo_venta"] = val
        if val == "Informal":
            desvincular_cliente()
        self.rebuild_ui()

    def handle_desvincular_cliente(self, e):
        desvincular_cliente()
        self.show_alert_info(e, "Cliente desvinculado de la venta.")
        self.rebuild_ui()

    def handle_buscar_cliente(self, e):
        query = (self.cli_search_input.value or "").strip()
        if not query:
            self.show_alert_error(e, "Ingrese una Cédula o RIF para buscar.")
            return

        # ERS 3.4: formato obligatorio [V-00.000.000 ó J-00000000-0] antes de buscar.
        if not _formato_cedula_rif_valido(query):
            self.show_alert_error(
                e,
                "Formato de Cédula/RIF inválido. Use V-00.000.000 o J-00000000-0."
            )
            return

        cliente = buscar_cliente_por_cedula(query)
        if cliente:
            vincular_cliente_a_carrito(cliente)
            self.show_alert_success(e, f"Cliente '{cliente['nombre']}' vinculado a la venta.")
            self.rebuild_ui()
        else:
            # ERS 3.4: si no coincide con la Cartera de Clientes, se abre el
            # Módulo 1.2 para registrarlo sin abandonar la venta en curso.
            self.abrir_modal_crear_cliente(query, e)

    def abrir_modal_crear_cliente(self, cedula_sugerida: str, e=None):
        """Abre el Módulo 1.2 (Cartera de Clientes) para registrar al cliente
        no encontrado, aplicando RNO-CLI-01, y lo vincula a la venta en curso."""
        p = self.get_current_page(e)
        if not p:
            return

        f_cedula = ft.TextField(label="Cédula/RIF *", value=cedula_sugerida, border_radius=12, width=200)
        f_nombre = ft.TextField(label="Nombre / Razón Social *", autofocus=True, border_radius=12, expand=True)
        f_telefono = ft.TextField(label="Teléfono", border_radius=12, width=200)
        f_direccion = ft.TextField(label="Dirección", border_radius=12, expand=True)
        f_correo = ft.TextField(label="Correo (opcional)", border_radius=12, expand=True)
        lbl_err = ft.Text("", color=ft.Colors.RED_500, size=12, weight=ft.FontWeight.BOLD)

        def _crear(ev):
            try:
                nuevo = crear_cliente(
                    nombre=f_nombre.value,
                    cedula_rif=f_cedula.value,
                    direccion=f_direccion.value,
                    telefono=f_telefono.value,
                    correo=f_correo.value,
                )
                dlg.open = False
                self.safe_update(ev)
                vincular_cliente_a_carrito(nuevo)
                self.show_alert_success(ev, f"Cliente '{nuevo['nombre']}' registrado y vinculado a la venta.")
                self.rebuild_ui()
            except ValueError as ex:
                lbl_err.value = str(ex)
                self.safe_update(ev)

        def cerrar(ev):
            dlg.open = False
            self.safe_update(ev)

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.Icons.PERSON_ADD_ALT_1, color=self.get_accent_color()),
                ft.Text("Cliente no registrado — Cartera de Clientes", weight=ft.FontWeight.BOLD),
            ], spacing=10),
            content=ft.Container(
                content=ft.Column([
                    ft.Text(
                        "El cliente no está registrado. Complete sus datos (Módulo 1.2) "
                        "para vincularlo automáticamente a esta venta:",
                        size=12, color=self.get_subtext_color()
                    ),
                    ft.Row([f_cedula, f_telefono], spacing=10),
                    f_nombre,
                    f_direccion,
                    f_correo,
                    lbl_err,
                ], spacing=10, tight=True),
                width=460,
            ),
            actions=[
                ft.TextButton("Cancelar", on_click=cerrar),
                ft.Button(
                    content=ft.Row([ft.Icon(ft.Icons.SAVE), ft.Text("Crear y Vincular")], tight=True),
                    bgcolor=self.get_accent_color(), color=ft.Colors.WHITE,
                    style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=12)),
                    on_click=_crear,
                ),
            ],
        )
        if dlg not in p.overlay:
            p.overlay.append(dlg)
        dlg.open = True
        p.update()

    def agregar_producto_directo(self, producto: dict, cantidad: float, e=None):
        """Agrega un producto directamente al carrito activo."""
        c, es_nuevo = agregar_o_actualizar_producto(producto, cantidad=cantidad, tasa_bcv=self.tasa_bcv)
        nombre_c = producto.get("nombre_referencia_corto") or producto.get("referencia") or producto["codigo"]
        self.show_alert_success(e, f"Agregado {cantidad:.0f} ud(s) de '{nombre_c}' al {c['id']}.")
        self.rebuild_ui()

    def handle_agregar_producto(self, e):
        codigo_query = (self.prod_search_input.value or "").strip()
        if not codigo_query:
            self.show_alert_error(e, "Ingrese un término o código para buscar.")
            return

        try:
            cant_deseada = float(self.cant_input.value or "1")
            if cant_deseada <= 0:
                raise ValueError()
        except ValueError:
            self.show_alert_error(e, "La cantidad debe ser mayor a cero.")
            return

        criterio = self.criterio_busqueda_dd.value or "Todos"
        prods = listar_productos(busqueda=codigo_query)
        prod_encontrado = None

        for p in prods:
            if p["codigo"].upper() == codigo_query.upper() or (p.get("codigo_barras") and p["codigo_barras"].upper() == codigo_query.upper()):
                prod_encontrado = p
                break

        if not prod_encontrado and prods:
            prod_encontrado = prods[0]

        if not prod_encontrado:
            self.show_alert_error(e, f"No se encontró ningún producto para '{codigo_query}'.")
            return

        stock_disponible = float(prod_encontrado["existencia"])
        c_activo = obtener_carrito_activo()
        cant_en_carrito = sum(item["cantidad"] for item in c_activo["items"] if item["codigo"] == prod_encontrado["codigo"])

        if (cant_en_carrito + cant_deseada) > stock_disponible:
            self.show_alert_error(
                e,
                f"Stock insuficiente para {prod_encontrado['codigo']}.\n"
                f"Disponible: {stock_disponible:.2f} | En carrito: {cant_en_carrito:.2f}"
            )
            return

        self.agregar_producto_directo(prod_encontrado, cant_deseada, e)
        self.prod_search_input.value = ""
        self.cant_input.value = "1"

    def abrir_modal_buscar_inventario(self, e):
        """Flujo Inverso (ERS 3.3): abre el Inventario en un modal con filtro de
        búsqueda; al seleccionar un producto, se retorna directamente a la
        línea de venta en curso (se agrega al carrito activo)."""
        p = self.get_current_page(e)
        if not p:
            return

        txt_busqueda = ft.TextField(
            label="Filtrar por código, referencia, descripción, marca o departamento",
            autofocus=True,
            border_radius=12,
            prefix_icon=ft.Icons.SEARCH,
        )
        lista_resultados = ft.Column(spacing=6, scroll=ft.ScrollMode.AUTO, height=340)

        def _agregar_desde_modal(prod: dict, ev):
            dlg.open = False
            self.safe_update(ev)
            try:
                cant = float(self.cant_input.value or "1")
                if cant <= 0:
                    cant = 1.0
            except ValueError:
                cant = 1.0
            self.agregar_producto_directo(prod, cant, ev)

        def _refrescar(ev=None):
            termino = (txt_busqueda.value or "").strip()
            productos = listar_productos(busqueda=termino, per_page=30) if termino else listar_productos(per_page=30)
            if not productos:
                lista_resultados.controls = [
                    ft.Text("No se encontraron productos.", color=self.get_subtext_color())
                ]
            else:
                lista_resultados.controls = [
                    ft.Container(
                        content=ft.Row(
                            controls=[
                                ft.Column([
                                    ft.Text(f"{pr['codigo']} — {pr.get('nombre_referencia_corto') or pr['referencia']}", weight=ft.FontWeight.BOLD, color=self.get_text_color(), size=13),
                                    ft.Text(f"${pr['precio_dolares']:.2f} | Bs {pr['precio_bcv']:.2f} | Stock: {pr['existencia']:.0f} | {pr.get('departamento','-')}", size=11, color=self.get_subtext_color()),
                                ], spacing=2, tight=True, expand=True),
                                ft.IconButton(
                                    icon=ft.Icons.ADD_SHOPPING_CART, icon_color=ft.Colors.GREEN_600,
                                    tooltip="Agregar a la venta en curso",
                                    on_click=lambda ev2, prod=pr: _agregar_desde_modal(prod, ev2),
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        padding=8, border_radius=10, bgcolor=self.get_card_bg(),
                        border=ft.Border.all(1, self.get_border_color()),
                    )
                    for pr in productos
                ]
            self.safe_update(ev)

        txt_busqueda.on_change = _refrescar

        def cerrar(ev):
            dlg.open = False
            self.safe_update(ev)

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([ft.Icon(ft.Icons.INVENTORY_2_ROUNDED, color=self.get_accent_color()), ft.Text("Buscar en Inventario", weight=ft.FontWeight.BOLD)], spacing=10),
            content=ft.Container(
                content=ft.Column([txt_busqueda, ft.Divider(height=6), lista_resultados], spacing=10, tight=True),
                width=560,
            ),
            actions=[ft.TextButton("Cerrar", on_click=cerrar)],
        )

        _refrescar()
        if dlg not in p.overlay:
            p.overlay.append(dlg)
        dlg.open = True
        p.update()

    def handle_remover_item(self, e, codigo):
        remover_item_de_carrito(codigo)
        self.show_alert_info(e, f"Producto '{codigo}' removido del carrito.")
        self.rebuild_ui()

    def handle_abrir_modal_editar_item(self, item: dict, e=None):
        """Abre un diálogo emergente para editar cantidad o precio de un renglón del carrito."""
        p = self.get_current_page(e)
        if not p:
            return

        txt_cant = ft.TextField(
            label="Cantidad",
            value=f"{item['cantidad']:.2f}",
            keyboard_type=ft.KeyboardType.NUMBER,
            width=150,
            border_radius=12
        )
        txt_precio_usd = ft.TextField(
            label="Precio Unitario ($)",
            value=f"{item['precio_usd']:.2f}",
            keyboard_type=ft.KeyboardType.NUMBER,
            width=150,
            border_radius=12
        )
        lbl_err = ft.Text("", color=ft.Colors.RED_500, size=12, weight=ft.FontWeight.BOLD)

        def guardar_cambios(e_save):
            lbl_err.value = ""
            try:
                n_cant = float(txt_cant.value.strip().replace(",", "."))
                n_precio = float(txt_precio_usd.value.strip().replace(",", "."))
                if n_cant <= 0 or n_precio <= 0:
                    raise ValueError("Los valores deben ser mayores a cero.")

                editar_item_en_carrito(item["codigo"], n_cant, n_precio, tasa_bcv=self.tasa_bcv)
                dlg.open = False
                p.update()
                self.show_alert_success(e_save, f"Renglón '{item['codigo']}' actualizado.")
                self.rebuild_ui()
            except ValueError as ex:
                lbl_err.value = str(ex) if str(ex) else "Ingrese valores numéricos válidos."
                p.update()

        def cerrar(e_close):
            dlg.open = False
            p.update()

        dlg = ft.AlertDialog(
            title=ft.Row([
                ft.Icon(ft.Icons.EDIT_NOTE, color=self.get_accent_color()),
                ft.Text(f"Editar Renglón: {item['nombre_corto']}", weight=ft.FontWeight.BOLD, size=15)
            ], spacing=10),
            content=ft.Container(
                content=ft.Column([
                    ft.Text(f"Código: {item['codigo']}", size=12, color=self.get_subtext_color()),
                    ft.Divider(height=10),
                    ft.Row([txt_cant, txt_precio_usd], spacing=10),
                    lbl_err
                ], spacing=10, tight=True),
                width=360,
                padding=10
            ),
            actions=[
                ft.TextButton("Cancelar", on_click=cerrar),
                ft.Button(
                    content=ft.Row([ft.Icon(ft.Icons.SAVE), ft.Text("Guardar Cambios")], tight=True),
                    bgcolor=self.get_accent_color(),
                    color=ft.Colors.WHITE,
                    on_click=guardar_cambios
                )
            ],
            actions_alignment=ft.MainAxisAlignment.SPACE_BETWEEN
        )

        if dlg not in p.overlay:
            p.overlay.append(dlg)
        dlg.open = True
        p.update()

    def build_tabla_carrito(self, items: list) -> ft.Control:
        if not items:
            return self.create_card(
                content=ft.Column([
                    ft.Icon(ft.Icons.SHOPPING_CART_OUTLINED, size=52, color=self.get_accent_color()),
                    ft.Text("CARRITO DE COMPRAS VACÍO", size=14, weight=ft.FontWeight.BOLD, color=self.get_text_color()),
                    ft.Text("Seleccione un producto arriba o use las recomendaciones rápidas para añadir ítems.", size=12, color=self.get_subtext_color(), text_align=ft.TextAlign.CENTER)
                ], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=8),
                padding=35,
                border_radius=16
            )

        filas = []
        for item in items:
            cod = item["codigo"]
            filas.append(
                ft.DataRow(cells=[
                    ft.DataCell(ft.Text(item["codigo"], weight=ft.FontWeight.BOLD, color=self.get_text_color())),
                    ft.DataCell(ft.Text(item["nombre_corto"], color=self.get_text_color())),
                    ft.DataCell(ft.Text(f"{item['cantidad']:.2f}", color=self.get_text_color())),
                    ft.DataCell(ft.Text(f"$ {item['precio_usd']:,.2f}", color=ft.Colors.GREEN_600, weight=ft.FontWeight.BOLD)),
                    ft.DataCell(ft.Text(f"Bs. {item['precio_bcv']:,.2f}", color=ft.Colors.AMBER_700, weight=ft.FontWeight.BOLD)),
                    ft.DataCell(ft.Text(f"$ {item['subtotal_usd']:,.2f}", weight=ft.FontWeight.BOLD, color=self.get_accent_color())),
                    ft.DataCell(
                        ft.Row([
                            ft.IconButton(
                                icon=ft.Icons.EDIT_OUTLINED,
                                icon_color=self.get_accent_color(),
                                tooltip="Editar cantidad o precio",
                                on_click=lambda e, it=item: self.handle_abrir_modal_editar_item(it, e)
                            ),
                            ft.IconButton(
                                icon=ft.Icons.DELETE_OUTLINED,
                                icon_color=ft.Colors.RED_400,
                                tooltip="Remover ítem",
                                on_click=lambda e, c=cod: self.handle_remover_item(e, c)
                            )
                        ], spacing=0)
                    )
                ])
            )

        return self.create_card(
            content=ft.Column([
                ft.Text(f"CARRITO DE COMPRAS ({len(items)} renglones)", size=13, weight=ft.FontWeight.BOLD, color=self.get_accent_color()),
                ft.Row(
                    controls=[
                        ft.DataTable(
                            columns=[
                                ft.DataColumn(ft.Text("Código", color=self.get_text_color())),
                                ft.DataColumn(ft.Text("Producto", color=self.get_text_color())),
                                ft.DataColumn(ft.Text("Cant.", color=self.get_text_color())),
                                ft.DataColumn(ft.Text("P. Unit ($)", color=self.get_text_color())),
                                ft.DataColumn(ft.Text("P. Unit (Bs)", color=self.get_text_color())),
                                ft.DataColumn(ft.Text("Subtotal ($)", color=self.get_text_color())),
                                ft.DataColumn(ft.Text("Acciones", color=self.get_text_color())),
                            ],
                            rows=filas,
                            heading_row_color=self.get_card_bg()
                        )
                    ],
                    scroll=ft.ScrollMode.AUTO,
                )
            ], spacing=10),
            padding=15,
            border_radius=16
        )

    # ── Procesamiento de Venta & Diálogo PDF (ERS 3.5) ─────────────────────

    def handle_procesar_venta(self, e):
        c_activo = obtener_carrito_activo()
        items = c_activo["items"]

        if not items:
            self.show_alert_error(e, "No puede procesar una venta sin artículos en el carrito.")
            return

        cliente_id = None
        if c_activo.get("tipo_venta") == "Formal":
            cliente = c_activo.get("cliente")
            if not cliente:
                self.show_alert_error(e, "Debe buscar y seleccionar un cliente registrado para realizar una Venta Formal.")
                return
            cliente_id = cliente["cedula_rif"]

        lineas = []
        for item in items:
            lineas.append({
                "producto_codigo": item["codigo"],
                "cantidad": item["cantidad"],
                "precio_unitario_usd": item["precio_usd"],
                "precio_unitario_bcv": item["precio_bcv"],
                "subtotal_usd": item["subtotal_usd"],
                "subtotal_bcv": item["subtotal_bcv"]
            })

        try:
            resultado = procesar_venta(
                tipo_venta=c_activo.get("tipo_venta", "Formal"),
                cliente_id=cliente_id,
                lineas=lineas
            )

            self.venta_id_reciente = resultado["venta_id"]
            vaciar_carrito_activo()
            self.show_alert_success(e, f"¡Venta N° {self.venta_id_reciente:06d} registrada exitosamente!")
            self.rebuild_ui()
            self.mostrar_dialogo_pdf(e)

        except ValueError as ve:
            self.show_alert_error(e, str(ve))
        except Exception as ex:
            self.show_alert_error(e, f"Error al procesar la venta: {ex}")

    def mostrar_dialogo_pdf(self, e):
        dd_divisa = ft.Dropdown(
            label="Divisa de Impresión (ERS 3.5)",
            value="USD",
            options=[
                ft.dropdown.Option("USD", "Dólares ($)"),
                ft.dropdown.Option("BCV", "Bolívares (Bs. BCV)")
            ],
            width=220,
            border_radius=12
        )
        dd_formato_papel = ft.Dropdown(
            label="Tamaño de Hoja",
            value="carta",
            options=[
                ft.dropdown.Option("carta", "Carta"),
                ft.dropdown.Option("media_carta", "Media Carta"),
            ],
            width=220,
            border_radius=12
        )

        def cerrar_dialogo(e_dialog):
            dialog.open = False
            self.safe_update(e_dialog)

        def confirmar_generar_pdf(e_dialog):
            self.divisa_impresion_pdf = dd_divisa.value or "USD"
            formato_papel = dd_formato_papel.value or "carta"
            dialog.open = False
            self.safe_update(e_dialog)

            last_pdf_dir = get_setting("last_pdf_dir", default=None)
            if last_pdf_dir and not os.path.exists(last_pdf_dir):
                last_pdf_dir = None

            sugerencia = f"Nota_Entrega_{self.venta_id_reciente:06d}.pdf"
            ruta_destino = self.abrir_dialogo_guardado(last_pdf_dir, sugerencia)

            if ruta_destino:
                try:
                    generar_nota_entrega_pdf(
                        venta_id=self.venta_id_reciente,
                        divisa_impresion=self.divisa_impresion_pdf,
                        ruta_destino=ruta_destino,
                        formato_papel=formato_papel,
                    )
                    directorio = os.path.dirname(ruta_destino)
                    if directorio:
                        set_setting("last_pdf_dir", directorio)

                    # ERS 3.5 paso 4: despachar a la impresora predeterminada.
                    try:
                        enviado = enviar_a_impresora(ruta_destino)
                        if enviado:
                            self.show_alert_success(e_dialog, f"Nota de Entrega enviada a la impresora predeterminada.\nGuardada en:\n{ruta_destino}")
                        else:
                            self.show_alert_info(e_dialog, f"Nota de Entrega guardada en:\n{ruta_destino}\n(Impresión automática no disponible en esta plataforma; ábrala manualmente para imprimir.)")
                    except Exception as ex_print:
                        self.show_alert_error(e_dialog, f"Nota guardada, pero falló el envío a la impresora: {ex_print}")
                except Exception as ex:
                    self.show_alert_error(e_dialog, f"Error al generar Nota de Entrega: {ex}")

        dialog = ft.AlertDialog(
            title=ft.Row([ft.Icon(ft.Icons.PICTURE_AS_PDF, color=ft.Colors.RED_600), ft.Text("¿Generar Nota de Entrega PDF?")]),
            content=ft.Column([
                ft.Text(f"La venta N° {self.venta_id_reciente:06d} ha sido procesada con éxito."),
                ft.Text("Seleccione la divisa para reflejar los precios en el documento impreso:"),
                dd_divisa,
                dd_formato_papel,
            ], tight=True, spacing=10),
            actions=[
                ft.TextButton("No - Finalizar", on_click=cerrar_dialogo),
                ft.Button(
                    "Sí - Guardar PDF",
                    on_click=confirmar_generar_pdf,
                    style=ft.ButtonStyle(
                        bgcolor=ft.Colors.GREEN_700,
                        color=ft.Colors.WHITE,
                        shape=ft.RoundedRectangleBorder(radius=12)
                    )
                )
            ],
            actions_alignment=ft.MainAxisAlignment.END
        )

        p = self.get_current_page(e)
        if p:
            if dialog not in p.overlay:
                p.overlay.append(dialog)
            dialog.open = True
            p.update()
