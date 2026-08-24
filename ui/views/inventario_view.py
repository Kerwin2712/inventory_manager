import flet as ft
from ui.views.base_view import BaseView
from ui.components.multi_select_filter import MultiSelectFilter, RangeFilter
from ui.components.scroll_nav import build_scroll_nav
from services.bcv_service import actualizar_tasa, obtener_estado_tasa
from services.inventario_service import (
    crear_producto, obtener_producto, actualizar_producto,
    listar_productos, eliminar_producto,
    obtener_opciones_filtro, obtener_opciones_proveedor_filtro,
)
from services.cartera_service import listar_proveedores
from services.reportes_service import obtener_historial_producto


class InventarioView(BaseView):
    """Vista avanzada del Módulo de Inventario con motor BCV, filtros en cascada
    y flujo de registro en 3 pasos (ERS 3.1 / 3.2)."""

    ITEMS_PER_PAGE = 15

    def __init__(self, on_back_callback=None, on_procesar_venta=None, es_admin: bool = False):
        self.on_back_callback = on_back_callback
        # Callback (ERS 3.3 — Flujo Directo Inventario→Ventas): recibe el
        # producto seleccionado y navega automáticamente a Ventas cargándolo.
        self.on_procesar_venta = on_procesar_venta
        # ERS 3.6: el historial clínico de producto es exclusivo admin/gerencia.
        self.es_admin = es_admin
        self._page_num = 1

        # ── Estado del formulario de ingreso ────────────────────────────────
        self._form_codigo_verificado = False
        self._editing_codigo: str | None = None

        # ── Dialogo activo (referencia para cerrarlo) ────────────────────────
        self._dialog: ft.AlertDialog | None = None

        # ── Visibilidad de columnas de la tabla (mostrar/ocultar) ───────────
        # "acciones" es estructural (íconos de edición/venta) y no se puede ocultar.
        self._columnas_ocultables = [
            "codigo", "referencia", "descripcion", "departamento", "marca",
            "precio_efectivo", "precio_bcv", "monto_bs", "existencia",
        ]
        self._columnas_labels = {
            "codigo": "Código",
            "referencia": "Referencia",
            "descripcion": "Descripción",
            "departamento": "Depto.",
            "marca": "Marca",
            "precio_efectivo": "Precio $ (Efectivo)",
            "precio_bcv": "Precio $ (BCV)",
            "monto_bs": "Monto Bs (BCV)",
            "existencia": "Exist.",
            "acciones": "Acciones",
        }
        self._columnas_visibles = {k: True for k in self._columnas_ocultables}

        super().__init__(route="/inventario", title="Módulo de Inventario")

    # =========================================================================
    # HELPERS DE PÁGINA
    # =========================================================================
    def _get_page(self, e=None):
        """Obtiene la instancia de page de forma segura."""
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

    def _safe_update(self, e=None):
        p = self._get_page(e)
        if p:
            p.update()
        else:
            try:
                self.update()
            except (RuntimeError, AttributeError):
                pass

    def _close_dialog(self, e=None):
        p = self._get_page(e)
        if p and self._dialog:
            self._dialog.open = False
            p.update()

    def _open_dialog(self, dialog: ft.AlertDialog, e=None):
        self._dialog = dialog
        p = self._get_page(e)
        if p:
            if dialog not in p.overlay:
                p.overlay.append(dialog)
            dialog.open = True
            p.update()

    def _snack(self, msg: str, color: str, e=None):
        p = self._get_page(e)
        if p:
            s = ft.SnackBar(
                content=ft.Text(msg, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD),
                bgcolor=color, duration=3500,
            )
            p.overlay.append(s)
            s.open = True
            p.update()

    # =========================================================================
    # CONSTRUCCIÓN DE LA VISTA
    # =========================================================================
    def get_body(self) -> ft.Control:
        accent = self.get_accent_color()
        card_bg = self.get_card_bg()
        text_color = self.get_text_color()
        subtext = self.get_subtext_color()
        border = self.get_border_color()

        return ft.Column(
            controls=[
                self._build_bcv_panel(accent, card_bg, text_color, subtext, border),
                ft.Divider(height=6, color=border),
                self._build_filtros_panel(accent, card_bg, text_color, border),
                ft.Divider(height=6, color=border),
                self._build_tabla_panel(accent, card_bg, text_color, subtext, border),
            ],
            spacing=10,
            expand=True,
            scroll=ft.ScrollMode.AUTO,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # PANEL BCV
    # ─────────────────────────────────────────────────────────────────────────
    def _build_bcv_panel(self, accent, card_bg, text_color, subtext, border) -> ft.Control:
        estado = obtener_estado_tasa()
        tasa_val = estado["tasa"]
        descripcion = estado["descripcion"]

        # Indicador de tiempo (amarillo si >24h sin actualizar)
        stale = "día" in descripcion or "días" in descripcion
        ind_color = ft.Colors.AMBER_400 if stale else ft.Colors.GREEN_400
        ind_icon = ft.Icons.WARNING_AMBER_ROUNDED if stale else ft.Icons.CHECK_CIRCLE_OUTLINE_ROUNDED

        self._lbl_tasa = ft.Text(
            f"Tasa BCV: {tasa_val:.4f} Bs/$ — {descripcion}",
            size=13,
            color=ind_color,
            weight=ft.FontWeight.W_600,
        )
        self._lbl_tasa_icon = ft.Icon(ind_icon, color=ind_color, size=18)

        self._inp_nueva_tasa = ft.TextField(
            label="Nueva tasa (Bs/$)",
            hint_text="Ej: 50.35",
            width=180,
            keyboard_type=ft.KeyboardType.NUMBER,
            color=text_color,
            border_color=border,
            focused_border_color=accent,
            border_radius=12,
            on_submit=self._handle_actualizar_tasa,
        )

        btn_act_tasa = ft.Button(
            content=ft.Text("Actualizar Tasa", weight=ft.FontWeight.BOLD),
            icon=ft.Icons.CURRENCY_EXCHANGE,
            style=ft.ButtonStyle(
                bgcolor=accent,
                color=ft.Colors.WHITE,
                shape=ft.RoundedRectangleBorder(radius=12)
            ),
            on_click=self._handle_actualizar_tasa,
        )

        return self.create_card(
            content=ft.Row(
                controls=[
                    ft.Row([self._lbl_tasa_icon, self._lbl_tasa], spacing=8),
                    ft.Row([self._inp_nueva_tasa, btn_act_tasa], spacing=10),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                wrap=True,
            ),
            padding=12,
            border_radius=18
        )

    def _handle_actualizar_tasa(self, e):
        raw = (self._inp_nueva_tasa.value or "").strip().replace(",", ".")
        try:
            tasa = float(raw)
            actualizar_tasa(tasa)
            self._inp_nueva_tasa.value = ""
            # Refrescar indicador
            estado = obtener_estado_tasa()
            stale = "día" in estado["descripcion"] or "días" in estado["descripcion"]
            ind_color = ft.Colors.AMBER_400 if stale else ft.Colors.GREEN_400
            ind_icon = ft.Icons.WARNING_AMBER_ROUNDED if stale else ft.Icons.CHECK_CIRCLE_OUTLINE_ROUNDED
            self._lbl_tasa.value = f"Tasa BCV: {estado['tasa']:.4f} Bs/$ — {estado['descripcion']}"
            self._lbl_tasa.color = ind_color
            self._lbl_tasa_icon.name = ind_icon
            self._lbl_tasa_icon.color = ind_color
            self._snack(f"Tasa BCV actualizada a {tasa:.4f} Bs/$", ft.Colors.GREEN_700, e)
            self._safe_update(e)
        except ValueError as ex:
            self._snack(f"Valor inválido: {ex}", ft.Colors.RED_700, e)

    # ─────────────────────────────────────────────────────────────────────────
    # PANEL FILTROS EN CASCADA (ERS 3.2)
    # ─────────────────────────────────────────────────────────────────────────
    def _build_filtros_panel(self, accent, card_bg, text_color, border) -> ft.Control:
        # Buscador general: un único campo cubre Código, Referencia,
        # Descripción, Marca, Código de Barras y Nombre Corto (búsqueda por
        # palabras independientes con AND), en lugar de seis cajas de texto
        # separadas — minimiza el espacio ocupado sin perder cobertura.
        self._f_busqueda = ft.TextField(
            label="Buscar código, referencia, descripción, marca...",
            hint_text="Escriba cualquier término y los resultados se filtran al instante",
            expand=True,
            color=text_color, border_color=border, focused_border_color=accent,
            border_radius=12, prefix_icon=ft.Icons.SEARCH,
            on_change=self._handle_filtro_change,
        )

        # Filtros de selección múltiple con buscador (departamento, marca,
        # proveedor): al abrir sin escribir nada se muestran primero los
        # valores más usados en el inventario.
        self._msf_departamento = MultiSelectFilter(
            self, "Departamento", ft.Icons.CATEGORY_ROUNDED,
            lambda: obtener_opciones_filtro("departamento"),
            self._handle_filtro_avanzado_change,
        )
        self._msf_marca = MultiSelectFilter(
            self, "Marca", ft.Icons.BRANDING_WATERMARK_ROUNDED,
            lambda: obtener_opciones_filtro("marca"),
            self._handle_filtro_avanzado_change,
        )
        self._msf_proveedor = MultiSelectFilter(
            self, "Proveedor", ft.Icons.LOCAL_SHIPPING_ROUNDED,
            obtener_opciones_proveedor_filtro,
            self._handle_filtro_avanzado_change,
        )

        # Filtros de rango: precios, existencia y periodos de ingreso /
        # actualización del producto.
        self._rf_precio_efectivo = RangeFilter(
            self, "Precio $ Efvo.", ft.Icons.ATTACH_MONEY_ROUNDED,
            self._handle_filtro_avanzado_change,
        )
        self._rf_precio_bcv = RangeFilter(
            self, "Precio $ BCV", ft.Icons.CURRENCY_EXCHANGE_ROUNDED,
            self._handle_filtro_avanzado_change,
        )
        self._rf_existencia = RangeFilter(
            self, "Existencia", ft.Icons.INVENTORY_2_ROUNDED,
            self._handle_filtro_avanzado_change,
        )
        self._rf_fecha_ingreso = RangeFilter(
            self, "Fecha Ingreso", ft.Icons.CALENDAR_MONTH_ROUNDED,
            self._handle_filtro_avanzado_change, is_date=True,
        )
        self._rf_fecha_actualizacion = RangeFilter(
            self, "Últ. Actualización", ft.Icons.UPDATE_ROUNDED,
            self._handle_filtro_avanzado_change, is_date=True,
        )

        self._filtros_avanzados = [
            self._msf_departamento, self._msf_marca, self._msf_proveedor,
            self._rf_precio_efectivo, self._rf_precio_bcv, self._rf_existencia,
            self._rf_fecha_ingreso, self._rf_fecha_actualizacion,
        ]

        btn_ingresar = ft.Button(
            content=ft.Text("  Ingresar Producto", weight=ft.FontWeight.BOLD),
            icon=ft.Icons.ADD_BOX_ROUNDED,
            style=ft.ButtonStyle(
                bgcolor=accent,
                color=ft.Colors.WHITE,
                shape=ft.RoundedRectangleBorder(radius=12)
            ),
            on_click=self._abrir_flujo_ingreso,
        )

        btn_limpiar = ft.OutlinedButton(
            content="Limpiar filtros",
            icon=ft.Icons.FILTER_ALT_OFF_OUTLINED,
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=12)
            ),
            on_click=self._handle_limpiar_filtros,
        )

        return self.create_card(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Icon(ft.Icons.SEARCH, color=accent, size=20),
                            ft.Text("Búsqueda y Filtros",
                                    size=14, weight=ft.FontWeight.BOLD, color=text_color),
                        ],
                        spacing=8,
                    ),
                    self._f_busqueda,
                    ft.Row(
                        controls=[f.control() for f in self._filtros_avanzados],
                        spacing=8,
                        wrap=True,
                    ),
                    ft.Row(controls=[btn_limpiar, btn_ingresar], spacing=12),
                ],
                spacing=10,
            ),
            padding=12,
            border_radius=18
        )

    def _handle_filtro_change(self, e):
        self._page_num = 1
        self._refrescar_tabla(e)

    def _handle_filtro_avanzado_change(self, *_args):
        self._page_num = 1
        self._refrescar_tabla()

    def _handle_limpiar_filtros(self, e):
        self._f_busqueda.value = ""
        for f in self._filtros_avanzados:
            f.reset()
        self._page_num = 1
        self._refrescar_tabla(e)

    # ─────────────────────────────────────────────────────────────────────────
    # TABLA PRINCIPAL
    # ─────────────────────────────────────────────────────────────────────────
    def _columnas_orden_visible(self) -> list[str]:
        """Orden fijo de columnas, filtrando las ocultables que el usuario desactivó."""
        return (
            [k for k in self._columnas_ocultables if self._columnas_visibles.get(k, True)]
            + ["acciones"]
        )

    def _build_columna_header(self, key: str, accent, text_color) -> ft.DataColumn:
        color = accent if key == "acciones" else text_color
        return ft.DataColumn(ft.Text(self._columnas_labels[key], color=color, weight=ft.FontWeight.BOLD))

    def _build_selector_columnas(self, accent, text_color) -> ft.PopupMenuButton:
        self._col_menu_items: dict[str, ft.PopupMenuItem] = {}
        items = []
        for key in self._columnas_ocultables:
            item = ft.PopupMenuItem(
                content=self._columnas_labels[key],
                checked=self._columnas_visibles[key],
                on_click=lambda e, k=key: self._toggle_columna(k, e),
            )
            self._col_menu_items[key] = item
            items.append(item)

        self._btn_columnas = ft.PopupMenuButton(
            icon=ft.Icons.VIEW_COLUMN_ROUNDED,
            icon_color=accent,
            tooltip="Mostrar/ocultar columnas",
            items=items,
        )
        return self._btn_columnas

    def _toggle_columna(self, key: str, e=None):
        visibles_actuales = [k for k in self._columnas_ocultables if self._columnas_visibles.get(k, True)]
        if self._columnas_visibles[key] and len(visibles_actuales) <= 1:
            self._snack("Debe quedar al menos una columna visible.", ft.Colors.AMBER_700, e)
            return
        self._columnas_visibles[key] = not self._columnas_visibles[key]
        self._col_menu_items[key].checked = self._columnas_visibles[key]
        accent = self.get_accent_color()
        text_color = self.get_text_color()
        self._dt.columns = [self._build_columna_header(k, accent, text_color) for k in self._columnas_orden_visible()]
        self._cargar_filas(text_color, accent)
        self._safe_update(e)

    def _build_tabla_panel(self, accent, card_bg, text_color, subtext, border) -> ft.Control:
        self._dt = ft.DataTable(
            columns=[self._build_columna_header(k, accent, text_color) for k in self._columnas_orden_visible()],
            rows=[],
        )
        self._tabla_scroll_row = ft.Row(controls=[self._dt], scroll=ft.ScrollMode.AUTO)
        self._lbl_pag = ft.Text("", color=subtext, size=12)
        self._cargar_filas(text_color, accent)

        btn_prev = ft.IconButton(ft.Icons.CHEVRON_LEFT, on_click=self._pagina_anterior)
        btn_next = ft.IconButton(ft.Icons.CHEVRON_RIGHT, on_click=self._pagina_siguiente)

        return self.create_card(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Icon(ft.Icons.INVENTORY_2_ROUNDED, color=accent),
                            ft.Text("Catálogo de Productos", size=15, weight=ft.FontWeight.BOLD, color=text_color),
                            ft.Container(expand=True),
                            self._build_selector_columnas(accent, text_color),
                        ],
                        spacing=8,
                    ),
                    ft.Container(
                        content=ft.Column(
                            controls=[
                                # Fila con scroll horizontal: evita que las columnas de la
                                # derecha (Exist., Acciones) queden recortadas/ilegibles
                                # cuando la sidebar expandida reduce el ancho disponible.
                                self._tabla_scroll_row,
                                ft.Row(
                                    controls=[
                                        build_scroll_nav(self._tabla_scroll_row, "horizontal", accent, tooltip_prefix="Tabla: "),
                                        ft.Row([
                                            self._lbl_pag,
                                            ft.Row([btn_prev, btn_next], spacing=4),
                                        ], spacing=10),
                                    ],
                                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                ),
                            ],
                        ),
                        padding=10,
                        border_radius=10,
                        bgcolor=card_bg,
                        border=ft.Border.all(1, border),
                    ),
                ],
                spacing=10,
            ),
        )

    def _cargar_filas(self, text_color=None, accent=None):
        if text_color is None:
            text_color = self.get_text_color()
        if accent is None:
            accent = self.get_accent_color()

        # Búsqueda general de texto + filtros avanzados combinables (multi-
        # selección con buscador para categóricos, rango para numéricos y
        # fechas de ingreso/actualización) — todos se combinan con AND.
        busqueda = getattr(self, "_f_busqueda", None) and self._f_busqueda.value or ""
        filtros = {
            "departamento": sorted(self._msf_departamento.selected) if hasattr(self, "_msf_departamento") else [],
            "marca": sorted(self._msf_marca.selected) if hasattr(self, "_msf_marca") else [],
            "proveedor_ids": sorted(self._msf_proveedor.selected) if hasattr(self, "_msf_proveedor") else [],
            "precio_dolares_min": getattr(self, "_rf_precio_efectivo", None) and self._rf_precio_efectivo.vmin,
            "precio_dolares_max": getattr(self, "_rf_precio_efectivo", None) and self._rf_precio_efectivo.vmax,
            "precio_bcv_min": getattr(self, "_rf_precio_bcv", None) and self._rf_precio_bcv.vmin,
            "precio_bcv_max": getattr(self, "_rf_precio_bcv", None) and self._rf_precio_bcv.vmax,
            "existencia_min": getattr(self, "_rf_existencia", None) and self._rf_existencia.vmin,
            "existencia_max": getattr(self, "_rf_existencia", None) and self._rf_existencia.vmax,
            "fecha_ingreso_desde": getattr(self, "_rf_fecha_ingreso", None) and self._rf_fecha_ingreso.vmin,
            "fecha_ingreso_hasta": getattr(self, "_rf_fecha_ingreso", None) and self._rf_fecha_ingreso.vmax,
            "fecha_actualizacion_desde": getattr(self, "_rf_fecha_actualizacion", None) and self._rf_fecha_actualizacion.vmin,
            "fecha_actualizacion_hasta": getattr(self, "_rf_fecha_actualizacion", None) and self._rf_fecha_actualizacion.vmax,
        }

        todos = listar_productos(
            busqueda=busqueda,
            filtros=filtros,
            page=self._page_num,
            per_page=self.ITEMS_PER_PAGE,
        )

        total_all = listar_productos(busqueda=busqueda, filtros=filtros, page=1, per_page=9999)
        total = len(total_all)
        total_pags = max(1, (total + self.ITEMS_PER_PAGE - 1) // self.ITEMS_PER_PAGE)
        self._lbl_pag.value = f"Página {self._page_num} de {total_pags} | {total} productos"

        def celda_acciones(p):
            return ft.Row([
                ft.IconButton(
                    ft.Icons.POINT_OF_SALE, icon_color=ft.Colors.BLUE_400,
                    tooltip="Procesar Venta (abre Ventas con este ítem, cant.=1)",
                    on_click=lambda ev, prod=p: self._procesar_venta_directo(prod, ev),
                ),
                ft.IconButton(
                    ft.Icons.ADD_SHOPPING_CART, icon_color=ft.Colors.GREEN_400,
                    tooltip="Añadir al Carrito de Ventas",
                    on_click=lambda ev, prod=p: self._abrir_modal_agregar_carrito(prod, ev),
                ),
                *([ft.IconButton(
                    ft.Icons.HISTORY_ROUNDED, icon_color=ft.Colors.PURPLE_300,
                    tooltip="Historial Clínico del Producto (ERS 3.6 — admin/gerencia)",
                    on_click=lambda ev, cod=p["codigo"]: self._abrir_modal_historial(cod, ev),
                )] if self.es_admin else []),
                ft.IconButton(
                    ft.Icons.EDIT_OUTLINED, icon_color=accent, tooltip="Editar",
                    on_click=lambda ev, cod=p["codigo"]: self._abrir_flujo_edicion(cod, ev),
                ),
                ft.IconButton(
                    ft.Icons.DELETE_OUTLINED, icon_color=ft.Colors.RED_400,
                    tooltip="Eliminar",
                    on_click=lambda ev, cod=p["codigo"]: self._confirmar_eliminar(cod, ev),
                ),
            ], spacing=0)

        constructores_celda = {
            "codigo": lambda p: ft.Text(p["codigo"], color=accent, weight=ft.FontWeight.W_600),
            "referencia": lambda p: ft.Text(p["referencia"] or "-", color=text_color),
            "descripcion": lambda p: ft.Text((p["descripcion_general"] or "-")[:40], color=text_color),
            "departamento": lambda p: ft.Text(p["departamento"] or "-", color=text_color),
            "marca": lambda p: ft.Text(p["marca"] or "-", color=text_color),
            "precio_efectivo": lambda p: ft.Text(f"${p['precio_dolares']:.2f}", color=ft.Colors.GREEN_400),
            "precio_bcv": lambda p: ft.Text(f"${p.get('precio_bcv', 0):.2f}", color=ft.Colors.CYAN_300),
            "monto_bs": lambda p: ft.Text(f"Bs {p.get('monto_bcv_bolivares', 0):.2f}", color=ft.Colors.AMBER_300),
            "existencia": lambda p: ft.Text(str(p["existencia"]), color=text_color),
            "acciones": celda_acciones,
        }

        columnas = self._columnas_orden_visible()
        rows = []
        for p in todos:
            rows.append(
                ft.DataRow(
                    cells=[ft.DataCell(constructores_celda[k](p)) for k in columnas],
                )
            )
        self._dt.rows = rows

    def _abrir_modal_historial(self, codigo: str, e=None):
        """Historial Clínico de Producto (ERS 3.6): movimientos cronológicos
        de venta y proveedor vigente. Exclusivo admin/gerencia."""
        p = self.get_current_page(e)
        if not p or not self.es_admin:
            return

        try:
            data = obtener_historial_producto(codigo)
        except ValueError as ex:
            self._snack(str(ex), ft.Colors.RED_700, e)
            return

        prod = data["producto"]
        prov = data["proveedor_actual"]
        movimientos = data["movimientos_venta"]

        info_prov = (
            f"{prov['empresa'] or prov['contacto'] or '-'} | Tel: {prov.get('telefono') or 'N/A'}"
            if prov else "Sin proveedor asignado"
        )

        filas_mov = []
        if movimientos:
            for m in movimientos[:50]:
                filas_mov.append(
                    ft.Row([
                        ft.Text(str(m["fecha"]), size=12, color=self.get_text_color(), width=140),
                        ft.Text(m["tipo_venta"], size=12, color=self.get_subtext_color(), width=70),
                        ft.Text(f"Cant: {float(m['cantidad']):.2f}", size=12, color=ft.Colors.AMBER_400, width=90),
                        ft.Text(m.get("cliente_id") or "Mostrador", size=12, color=self.get_subtext_color()),
                    ], spacing=10)
                )
        else:
            filas_mov.append(ft.Text("Sin movimientos de venta registrados.", color=self.get_subtext_color()))

        def cerrar(ev):
            dlg.open = False
            self._safe_update(ev)

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.Icons.HISTORY_ROUNDED, color=ft.Colors.PURPLE_300),
                ft.Text(f"Historial Clínico — {prod.get('nombre_referencia_corto') or codigo}", weight=ft.FontWeight.BOLD),
            ], spacing=10),
            content=ft.Container(
                content=ft.Column([
                    ft.Text(f"Proveedor actual: {info_prov}", size=13, weight=ft.FontWeight.BOLD, color=self.get_text_color()),
                    ft.Text(f"Total histórico vendido: {data['total_vendido']:.2f} uds.", size=12, color=self.get_subtext_color()),
                    ft.Text(
                        "Nota: el esquema no registra aún un historial de compras/reposición por "
                        "proveedor; solo se muestra el proveedor vigente.",
                        size=11, color=self.get_subtext_color(), italic=True,
                    ),
                    ft.Divider(height=10),
                    ft.Text("Movimientos de venta (más reciente primero):", size=12, weight=ft.FontWeight.BOLD, color=self.get_text_color()),
                    ft.Column(controls=filas_mov, spacing=6, scroll=ft.ScrollMode.AUTO, height=260),
                ], spacing=8, tight=True),
                width=520,
            ),
            actions=[ft.TextButton("Cerrar", on_click=cerrar)],
        )
        self._open_dialog(dlg, e)

    def _procesar_venta_directo(self, prod: dict, e=None):
        """Flujo Directo (ERS 3.3): instancia una nueva nota de venta, carga el
        producto con cantidad=1 y navega automáticamente al módulo de Ventas."""
        if float(prod.get("existencia", 0)) <= 0:
            self._snack(
                f"'{prod.get('nombre_referencia_corto') or prod['codigo']}' no tiene existencia disponible.",
                ft.Colors.RED_700, e
            )
            return
        if self.on_procesar_venta:
            self.on_procesar_venta(prod, e)
        else:
            self._snack(
                "Esta acción requiere el Dashboard (navegación a Ventas no disponible en este contexto).",
                ft.Colors.AMBER_700, e
            )

    def _abrir_modal_agregar_carrito(self, prod: dict, e=None):
        """Abre un diálogo emergente para elegir a qué carrito enviar el
        producto: un carrito ya guardado (recuperándolo por su cliente) o uno
        nuevo, en cuyo caso permite buscar/crear al cliente en el mismo paso
        (flujo tipo supermercado: escanear producto -> elegir carrito)."""
        from services.cart_manager import (
            obtener_todos_los_carritos, crear_nuevo_carrito, vincular_cliente_a_carrito,
            agregar_o_actualizar_producto,
        )
        from services.cartera_service import buscar_cliente_por_cedula, crear_cliente, parse_documento, format_documento

        p = self.get_current_page(e)
        if not p:
            return
        sid = self.get_session_id(e)

        NUEVO_CARRITO = "__nuevo__"

        def _etiqueta_carrito(cinfo: dict) -> str:
            cliente = cinfo.get("cliente")
            n_items = len(cinfo.get("items", []))
            quien = cliente["nombre"] if cliente else "Sin cliente"
            return f"{cinfo['nombre']} — {quien} ({n_items} ítem{'s' if n_items != 1 else ''})"

        carritos_dict = obtener_todos_los_carritos(sid)
        opciones_carrito = [
            ft.dropdown.Option(NUEVO_CARRITO, "➕ Crear nuevo carrito")
        ] + [ft.dropdown.Option(cid, _etiqueta_carrito(cinfo)) for cid, cinfo in carritos_dict.items()]

        dd_carrito_destino = ft.Dropdown(
            label="Enviar a Carrito",
            value=NUEVO_CARRITO,
            options=opciones_carrito,
            border_radius=12,
        )

        cant_input = ft.TextField(
            label="Cantidad a agregar",
            value="1",
            width=150,
            keyboard_type=ft.KeyboardType.NUMBER,
            autofocus=True,
            border_radius=12
        )

        # ── Panel de cliente, solo visible al crear un carrito nuevo ────────
        cli_tipo = ft.Dropdown(
            value="V", width=80, border_radius=12,
            options=[ft.dropdown.Option(t) for t in ("V", "E", "J", "G", "P")],
        )
        def _filtrar_digitos_cliente(ev):
            limpio = "".join(filter(str.isdigit, cli_numero.value or ""))
            if limpio != cli_numero.value:
                cli_numero.value = limpio
                p.update()

        cli_numero = ft.TextField(
            label="Cédula/RIF del cliente (opcional)", hint_text="Solo números",
            keyboard_type=ft.KeyboardType.NUMBER, border_radius=12, expand=True,
            on_change=_filtrar_digitos_cliente,
        )
        lbl_cliente_vinculado = ft.Text("", size=12, weight=ft.FontWeight.BOLD)
        cliente_encontrado_state = {"cliente": None}

        def _buscar_o_crear_cliente(ev):
            numero = "".join(filter(str.isdigit, cli_numero.value or ""))
            if not numero:
                cliente_encontrado_state["cliente"] = None
                lbl_cliente_vinculado.value = ""
                p.update()
                return
            cedula = format_documento(cli_tipo.value or "V", numero)
            cliente = buscar_cliente_por_cedula(cedula)
            if cliente:
                cliente_encontrado_state["cliente"] = cliente
                lbl_cliente_vinculado.value = f"✓ Cliente encontrado: {cliente['nombre']}"
                lbl_cliente_vinculado.color = ft.Colors.GREEN_600
                p.update()
            else:
                lbl_cliente_vinculado.value = f"Cliente no registrado. Complete los datos para crearlo:"
                lbl_cliente_vinculado.color = ft.Colors.AMBER_700
                panel_nuevo_cliente.visible = True
                nc_tipo.value, nc_numero.value = cli_tipo.value, numero
                p.update()

        btn_buscar_cli = ft.IconButton(
            icon=ft.Icons.SEARCH, tooltip="Buscar cliente por Cédula/RIF",
            icon_color=self.get_accent_color(), on_click=_buscar_o_crear_cliente,
        )

        nc_tipo = ft.Dropdown(value="V", width=70, border_radius=12, disabled=True, options=[ft.dropdown.Option(t) for t in ("V", "E", "J", "G", "P")])
        nc_numero = ft.TextField(label="Cédula/RIF", width=140, border_radius=12, disabled=True)
        nc_nombre = ft.TextField(label="Nombre / Razón Social *", border_radius=12, expand=True)
        nc_telefono = ft.TextField(label="Teléfono", border_radius=12, width=160)
        panel_nuevo_cliente = ft.Column(
            [ft.Row([nc_tipo, nc_numero, nc_telefono], spacing=8), nc_nombre],
            spacing=8, visible=False,
        )

        panel_cliente = ft.Column([
            ft.Text("CLIENTE PARA EL NUEVO CARRITO", size=12, weight=ft.FontWeight.BOLD, color=self.get_accent_color()),
            ft.Row([cli_tipo, cli_numero, btn_buscar_cli]),
            lbl_cliente_vinculado,
            panel_nuevo_cliente,
        ], spacing=6)

        lbl_err = ft.Text("", color=ft.Colors.RED_500, size=12, weight=ft.FontWeight.BOLD)

        def _cambiar_destino(ev):
            panel_cliente.visible = dd_carrito_destino.value == NUEVO_CARRITO
            p.update()

        dd_carrito_destino.on_change = _cambiar_destino

        def confirmar_agregar(ev_confirm):
            try:
                cant = float(cant_input.value.strip())
                if cant <= 0:
                    raise ValueError("La cantidad debe ser mayor a 0.")
                stock = float(prod.get("existencia", 0))
                if cant > stock:
                    lbl_err.value = f"Existencia insuficiente ({stock:.0f} disponible)."
                    p.update()
                    return

                destino = dd_carrito_destino.value
                if destino == NUEVO_CARRITO:
                    cliente = cliente_encontrado_state["cliente"]
                    if not cliente and panel_nuevo_cliente.visible and (nc_nombre.value or "").strip():
                        cliente = crear_cliente(
                            nombre=nc_nombre.value,
                            cedula_rif=format_documento(nc_tipo.value, nc_numero.value),
                            direccion="", telefono=nc_telefono.value, correo="",
                        )
                    c_carrito = crear_nuevo_carrito(sid)
                    if cliente:
                        vincular_cliente_a_carrito(sid, cliente, c_carrito["id"])
                    else:
                        c_carrito["tipo_venta"] = "Informal"
                else:
                    c_carrito = carritos_dict[destino]
                from services.cart_manager import cambiar_carrito_activo
                c_act, _ = agregar_o_actualizar_producto(sid, prod, cantidad=cant, id_carrito=c_carrito["id"])
                cambiar_carrito_activo(sid, c_carrito["id"])
                dlg.open = False
                p.update()

                quien = c_act["cliente"]["nombre"] if c_act.get("cliente") else "Venta Mostrador"
                
                def ir_a_ventas(ev_go):
                    top_view = p.views[-1] if p.views else None
                    if hasattr(top_view, "handle_nav_change"):
                        top_view.handle_nav_change("Ventas")
                    else:
                        p.go("/ventas")

                s = ft.SnackBar(
                    content=ft.Text(f"✓ {cant:.0f} ud(s) de '{prod.get('nombre_referencia_corto') or prod['codigo']}' agregadas a {c_act['id']} ({quien})", color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD),
                    bgcolor=ft.Colors.GREEN_700,
                    action="IR A VENTAS",
                    on_action=ir_a_ventas,
                    duration=4000
                )
                p.overlay.append(s)
                s.open = True
                p.update()
            except ValueError as ex:
                lbl_err.value = str(ex) if str(ex) else "Ingrese valores válidos."
                p.update()

        def cerrar(ev_close):
            dlg.open = False
            p.update()

        dlg = ft.AlertDialog(
            title=ft.Row([
                ft.Icon(ft.Icons.ADD_SHOPPING_CART, color=ft.Colors.GREEN_400),
                ft.Text("Añadir al Carrito de Ventas", weight=ft.FontWeight.BOLD)
            ], spacing=10),
            content=ft.Container(
                content=ft.Column([
                    ft.Text(f"Producto: {prod.get('nombre_referencia_corto') or prod.get('descripcion_general')}", weight=ft.FontWeight.BOLD),
                    ft.Text(f"Código: {prod['codigo']} | Stock disponible: {prod.get('existencia', 0):.0f} Uds", size=12, color=self.get_subtext_color()),
                    ft.Text(f"Precio Efectivo: ${prod.get('precio_dolares', 0):.2f} | Precio BCV: ${prod.get('precio_bcv', 0):.2f} (Bs {prod.get('monto_bcv_bolivares', 0):.2f})", size=12, color=self.get_subtext_color()),
                    ft.Divider(height=10),
                    dd_carrito_destino,
                    cant_input,
                    ft.Divider(height=6),
                    panel_cliente,
                    lbl_err
                ], spacing=8, tight=True, scroll=ft.ScrollMode.AUTO),
                width=420,
                height=440,
                padding=10
            ),
            actions=[
                ft.TextButton("Cancelar", on_click=cerrar),
                ft.Button(
                    content=ft.Row([ft.Icon(ft.Icons.SHOPPING_CART_CHECKOUT), ft.Text("Agregar")], tight=True),
                    bgcolor=ft.Colors.GREEN_700,
                    color=ft.Colors.WHITE,
                    on_click=confirmar_agregar
                )
            ],
            actions_alignment=ft.MainAxisAlignment.SPACE_BETWEEN
        )

        if dlg not in p.overlay:
            p.overlay.append(dlg)
        dlg.open = True
        p.update()

    def _refrescar_tabla(self, e=None):
        try:
            self._cargar_filas()
        except AttributeError:
            pass
        self._safe_update(e)

    def _pagina_anterior(self, e):
        if self._page_num > 1:
            self._page_num -= 1
            self._refrescar_tabla(e)

    def _pagina_siguiente(self, e):
        self._page_num += 1
        self._refrescar_tabla(e)

    # =========================================================================
    # FLUJO DE INGRESO DE PRODUCTO — 3 PASOS (ERS 3.1)
    # =========================================================================
    def _abrir_flujo_ingreso(self, e):
        """Paso 1: Mostrar campo de código para verificar existencia."""
        self._form_codigo_verificado = False
        self._editing_codigo = None
        self._mostrar_paso1_dialogo(e, codigo_inicial="")

    def _abrir_flujo_edicion(self, codigo: str, e=None):
        """Abre el formulario en modo edición para un producto existente."""
        prod = obtener_producto(codigo)
        if not prod:
            self._snack(f"Producto '{codigo}' no encontrado.", ft.Colors.RED_700, e)
            return
        self._editing_codigo = codigo
        self._form_codigo_verificado = True
        self._mostrar_paso2_dialogo(e, codigo=codigo, datos_iniciales=prod)

    # ─── PASO 1: Verificación de Código ──────────────────────────────────────
    def _mostrar_paso1_dialogo(self, e, codigo_inicial=""):
        accent = self.get_accent_color()
        text_color = self.get_text_color()
        card_bg = self.get_card_bg()

        inp_cod = ft.TextField(
            label="Código del Producto *",
            hint_text="Ej: LAP-DELL-001",
            value=codigo_inicial,
            width=350,
            autofocus=True,
            color=text_color,
            border_color=self.get_border_color(),
            focused_border_color=accent,
            border_radius=12,
            on_submit=lambda ev: _verificar(ev),
        )
        lbl_status = ft.Text("", size=12, color=ft.Colors.AMBER_400)

        def _verificar(ev):
            codigo = (inp_cod.value or "").strip().upper()
            if not codigo:
                lbl_status.value = "⚠ El código no puede estar vacío."
                lbl_status.color = ft.Colors.AMBER_400
                self._safe_update(ev)
                return
            existente = obtener_producto(codigo)
            if existente:
                lbl_status.value = f"⚠ Ya existe un producto con el código '{codigo}'."
                lbl_status.color = ft.Colors.AMBER_400
                self._safe_update(ev)
                _confirmar_duplicado(ev, codigo, existente)
            else:
                self._close_dialog(ev)
                self._form_codigo_verificado = True
                self._mostrar_paso2_dialogo(ev, codigo=codigo)

        def _confirmar_duplicado(ev, codigo, existente):
            dlg_dup = ft.AlertDialog(
                modal=True,
                title=ft.Row([
                    ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, color=ft.Colors.AMBER_400),
                    ft.Text("Código Duplicado Detectado", color=text_color),
                ], spacing=10),
                content=ft.Text(
                    f"El código '{codigo}' ya está registrado como:\n"
                    f"• {existente.get('descripcion_general','')}\n\n"
                    f"¿Desea revisar ese producto?",
                    color=text_color,
                ),
                actions=[
                    ft.TextButton("No — Limpiar Código", on_click=lambda ev2: (
                        _close_dup(ev2),
                        setattr(inp_cod, "value", ""),
                        setattr(lbl_status, "value", ""),
                        self._safe_update(ev2),
                    )),
                    ft.Button(
                        "Sí — Ver Producto",
                        style=ft.ButtonStyle(
                            bgcolor=accent, color=ft.Colors.WHITE,
                            shape=ft.RoundedRectangleBorder(radius=12)
                        ),
                        on_click=lambda ev2: (
                            _close_dup(ev2),
                            self._close_dialog(ev2),
                            self._abrir_flujo_edicion(codigo, ev2),
                        ),
                    ),
                ],
                bgcolor=card_bg,
            )

            def _close_dup(ev2):
                dlg_dup.open = False
                self._safe_update(ev2)

            self._open_dialog(dlg_dup, ev)

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Nuevo Producto", color=text_color),
            content=ft.Column(
                controls=[
                    ft.Text("Ingrese el código único del producto para verificar si ya existe:", color=text_color),
                    inp_cod,
                    lbl_status,
                ],
                spacing=12,
                tight=True,
            ),
            actions=[
                ft.TextButton("Cancelar", on_click=self._close_dialog),
                ft.Button(
                    "Verificar",
                    icon=ft.Icons.SEARCH,
                    style=ft.ButtonStyle(
                        bgcolor=accent, color=ft.Colors.WHITE,
                        shape=ft.RoundedRectangleBorder(radius=12)
                    ),
                    on_click=_verificar,
                ),
            ],
            bgcolor=card_bg,
        )
        self._open_dialog(dlg, e)

    # ─── PASO 2: Formulario completo ──────────────────────────────────────────
    def _mostrar_paso2_dialogo(self, e, codigo: str, datos_iniciales: dict = None):
        accent = self.get_accent_color()
        text_color = self.get_text_color()
        card_bg = self.get_card_bg()
        border = self.get_border_color()
        d = datos_iniciales or {}

        def tf(label, key="", value="", width=260, kb=ft.KeyboardType.TEXT, hint=""):
            return ft.TextField(
                label=label, value=value or d.get(key, ""),
                width=width, hint_text=hint,
                keyboard_type=kb,
                color=text_color, border_color=border, focused_border_color=accent,
                border_radius=12,
            )

        # Controles del formulario
        cod_display = ft.TextField(
            label="Código *", value=codigo,
            width=200, disabled=True,
            color=text_color, border_color=border,
            border_radius=12,
        )
        f_ref = tf("Referencia *", "referencia")
        f_desc = tf("Descripción General *", "descripcion_general", width=520)
        f_depto = tf("Departamento *", "departamento", width=200)
        f_marca = tf("Marca", "marca", width=200)
        f_barras = tf("Código de Barras", "codigo_barras", width=200)
        f_nombre_corto = tf("Nombre Corto (máx 30 car.)", "nombre_referencia_corto", width=260)
        # Venezuela maneja DOS precios en dólares, independientes entre sí:
        # el Precio USD Efectivo (pago con dólares físicos) y el Precio USD
        # BCV (referencia en dólares para pago en Bolívares a la tasa
        # vigente). Ninguno se deriva del otro — ambos son inputs manuales.
        f_precio_usd = tf("Precio USD (Efectivo)", "precio_dolares",
                          value=str(d.get("precio_dolares", "")),
                          width=170, kb=ft.KeyboardType.NUMBER)
        f_precio_bcv = tf("Precio USD (BCV)", "precio_bcv",
                          value=str(d.get("precio_bcv", "")),
                          width=170, kb=ft.KeyboardType.NUMBER)

        tasa_vigente = obtener_estado_tasa().get("tasa", 0.0)

        def _monto_bs_preview(precio_bcv_str: str) -> str:
            try:
                usd_bcv = float((precio_bcv_str or "0").replace(",", "."))
            except ValueError:
                usd_bcv = 0.0
            return f"Bs {round(usd_bcv * tasa_vigente, 2):,.2f}" if tasa_vigente > 0 else "Sin tasa BCV configurada"

        # Solo el monto en Bolívares se calcula en tiempo de ejecución
        # (Precio USD BCV x tasa vigente); es de solo lectura.
        lbl_monto_bs = ft.TextField(
            label="Monto Bs equivalente (calculado)",
            value=_monto_bs_preview(str(d.get("precio_bcv", ""))),
            width=220,
            disabled=True,
            color=text_color, border_color=border,
            border_radius=12,
        )
        f_existencia = tf("Existencia", "existencia",
                          value=str(d.get("existencia", "0")),
                          width=120, kb=ft.KeyboardType.NUMBER)

        # Fila de precios (se oculta si existencia == 0)
        fila_precios = ft.Row([f_precio_usd, f_precio_bcv, lbl_monto_bs], spacing=12, visible=float(d.get("existencia", 1) or 1) != 0)

        def _on_precio_bcv_change(ev):
            lbl_monto_bs.value = _monto_bs_preview(f_precio_bcv.value)
            self._safe_update(ev)

        f_precio_bcv.on_change = _on_precio_bcv_change

        def _on_existencia_change(ev):
            val = (f_existencia.value or "0").strip()
            try:
                fila_precios.visible = float(val) != 0
            except ValueError:
                fila_precios.visible = True
            self._safe_update(ev)

        f_existencia.on_change = _on_existencia_change

        # Dropdown de Proveedores
        proveedores = listar_proveedores()
        prov_options = [ft.dropdown.Option(key="", text="Sin proveedor asignado")]
        for pv in proveedores:
            etiqueta = pv.get("empresa") or pv.get("contacto") or f"ID {pv['id']}"
            prov_options.append(ft.dropdown.Option(key=str(pv["id"]), text=etiqueta))

        prov_id_actual = str(d.get("proveedor_id", "") or "")
        dd_proveedor = ft.Dropdown(
            label="Proveedor",
            value=prov_id_actual if prov_id_actual else "",
            width=300,
            options=prov_options,
            color=text_color,
            border_color=border,
            focused_border_color=accent,
            border_radius=12,
        )

        titulo_paso = "Editar Producto" if self._editing_codigo else "Datos del Producto"

        def _limpiar_errores():
            for campo in (f_ref, f_desc, f_depto, f_precio_usd, f_precio_bcv):
                campo.error_text = None

        def _guardar(ev):
            # ── Requisito de guardado mínimo (ERS 3.1 paso 4) ────────────────
            # Validar ANTES de mostrar la confirmación del paso 3, resaltando
            # en rojo los campos omitidos. Si falla, el diálogo permanece
            # abierto y no se procede.
            _limpiar_errores()
            hay_error = False

            if not (f_ref.value or "").strip():
                f_ref.error_text = "Campo obligatorio"
                hay_error = True
            if not (f_desc.value or "").strip():
                f_desc.error_text = "Campo obligatorio"
                hay_error = True
            if not (f_depto.value or "").strip():
                f_depto.error_text = "Campo obligatorio"
                hay_error = True

            try:
                existencia_val = float((f_existencia.value or "0").replace(",", "."))
            except ValueError:
                existencia_val = 0.0
            try:
                usd_val = float((f_precio_usd.value or "0").replace(",", "."))
            except ValueError:
                usd_val = 0.0
            try:
                bcv_val = float((f_precio_bcv.value or "0").replace(",", "."))
            except ValueError:
                bcv_val = 0.0

            # Stock=0 omite la exigencia de precio; Stock>0 exige al menos
            # uno de los dos precios USD independientes (Efectivo o BCV).
            if existencia_val > 0 and usd_val <= 0 and bcv_val <= 0:
                f_precio_usd.error_text = "Requerido (Efectivo o BCV) si Existencia > 0"
                f_precio_bcv.error_text = "Requerido (Efectivo o BCV) si Existencia > 0"
                hay_error = True

            if hay_error:
                self._snack("Complete los campos obligatorios resaltados en rojo.", ft.Colors.RED_700, ev)
                self._safe_update(ev)
                return

            self._close_dialog(ev)
            datos = {
                "codigo": codigo,
                "referencia": f_ref.value,
                "descripcion_general": f_desc.value,
                "departamento": f_depto.value,
                "marca": f_marca.value,
                "codigo_barras": f_barras.value,
                "nombre_referencia_corto": f_nombre_corto.value,
                "precio_dolares": f_precio_usd.value,
                "precio_bcv": f_precio_bcv.value,
                "existencia": f_existencia.value,
                "proveedor_id": dd_proveedor.value or None,
            }
            self._mostrar_paso3_confirmacion(ev, datos)

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text(titulo_paso, color=text_color),
            content=ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row([cod_display, f_ref, f_depto, f_marca], spacing=12, wrap=True),
                        f_desc,
                        ft.Row([f_existencia, dd_proveedor, f_barras], spacing=12, wrap=True),
                        fila_precios,
                        f_nombre_corto,
                    ],
                    spacing=14,
                    scroll=ft.ScrollMode.AUTO,
                ),
                width=720,
                height=420,
            ),
            actions=[
                ft.TextButton("Cancelar", on_click=self._close_dialog),
                ft.Button(
                    "Revisar y Guardar",
                    icon=ft.Icons.FACT_CHECK_OUTLINED,
                    style=ft.ButtonStyle(
                        bgcolor=accent, color=ft.Colors.WHITE,
                        shape=ft.RoundedRectangleBorder(radius=12)
                    ),
                    on_click=_guardar,
                ),
            ],
            bgcolor=card_bg,
        )
        self._open_dialog(dlg, e)

    # ─── PASO 3: Confirmación ─────────────────────────────────────────────────
    def _mostrar_paso3_confirmacion(self, e, datos: dict):
        accent = self.get_accent_color()
        text_color = self.get_text_color()
        card_bg = self.get_card_bg()

        campos_orden = [
            ("Código", "codigo"),
            ("Referencia", "referencia"),
            ("Descripción General", "descripcion_general"),
            ("Departamento", "departamento"),
            ("Marca", "marca"),
            ("Existencia", "existencia"),
            ("Precio USD (Efectivo)", "precio_dolares"),
            ("Precio USD (BCV)", "precio_bcv"),
            ("Proveedor ID", "proveedor_id"),
            ("Código de Barras", "codigo_barras"),
            ("Nombre Corto", "nombre_referencia_corto"),
        ]

        filas_resumen = []
        for etiqueta, key in campos_orden:
            val = str(datos.get(key) or "").strip()
            mostrar = val if val and val not in ("0", "0.0", "None") else "— no llenado —"
            color_val = text_color if mostrar != "— no llenado —" else self.get_subtext_color()
            filas_resumen.append(
                ft.Row([
                    ft.Text(f"{etiqueta}:", width=200, color=self.get_subtext_color(), size=13),
                    ft.Text(mostrar, color=color_val, size=13, weight=ft.FontWeight.W_600),
                ], spacing=8)
            )

        def _confirmar(ev):
            self._close_dialog(ev)
            self._ejecutar_guardado(ev, datos)

        def _editar(ev):
            self._close_dialog(ev)
            prod_actual = obtener_producto(datos["codigo"]) if self._editing_codigo else None
            self._mostrar_paso2_dialogo(ev, codigo=datos["codigo"], datos_iniciales=prod_actual or datos)

        def _cancelar_todo(ev):
            """Cancelar en el paso 3 descarta todo y vuelve al paso 1 (ERS 3.1 paso 5)."""
            self._close_dialog(ev)
            self._form_codigo_verificado = False
            self._editing_codigo = None

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.Icons.FACT_CHECK_OUTLINED, color=accent),
                ft.Text("¿ESTÁS SEGURO DE REGISTRAR EL SIGUIENTE ÍTEM?", color=text_color, size=15),
            ], spacing=10),
            content=ft.Container(
                content=ft.Column(
                    controls=filas_resumen,
                    spacing=6,
                    scroll=ft.ScrollMode.AUTO,
                ),
                width=640,
                height=350,
                padding=10,
            ),
            actions=[
                ft.TextButton("Cancelar", on_click=_cancelar_todo),
                ft.OutlinedButton(
                    "Editar", icon=ft.Icons.EDIT_OUTLINED,
                    style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=12)),
                    on_click=_editar
                ),
                ft.Button(
                    "Aceptar — Guardar",
                    icon=ft.Icons.SAVE_OUTLINED,
                    style=ft.ButtonStyle(
                        bgcolor=accent, color=ft.Colors.WHITE,
                        shape=ft.RoundedRectangleBorder(radius=12)
                    ),
                    on_click=_confirmar,
                ),
            ],
            bgcolor=card_bg,
        )
        self._open_dialog(dlg, e)

    def _ejecutar_guardado(self, e, datos: dict):
        """Ejecuta el COMMIT a SQLite y refresca la tabla."""
        try:
            def _to_float(v):
                try:
                    return float((str(v) or "0").replace(",", "."))
                except ValueError:
                    return 0.0

            prov_id = None
            if datos.get("proveedor_id") and str(datos["proveedor_id"]).isdigit():
                prov_id = int(datos["proveedor_id"])

            kwargs = dict(
                codigo=datos["codigo"],
                referencia=datos.get("referencia", ""),
                descripcion_general=datos.get("descripcion_general", ""),
                departamento=datos.get("departamento", ""),
                marca=datos.get("marca", ""),
                precio_dolares=_to_float(datos.get("precio_dolares", 0)),
                precio_bcv=_to_float(datos.get("precio_bcv", 0)),
                proveedor_id=prov_id,
                existencia=_to_float(datos.get("existencia", 0)),
                codigo_barras=datos.get("codigo_barras", ""),
                nombre_referencia_corto=datos.get("nombre_referencia_corto", ""),
            )

            if self._editing_codigo:
                actualizar_producto(**kwargs)
                self._snack(f"Producto '{datos['codigo']}' actualizado correctamente.", ft.Colors.GREEN_700, e)
            else:
                crear_producto(**kwargs)
                self._snack(f"Producto '{datos['codigo']}' registrado exitosamente.", ft.Colors.GREEN_700, e)

            self._editing_codigo = None
            self._refrescar_tabla(e)
        except ValueError as ex:
            self._snack(str(ex), ft.Colors.RED_700, e)

    # ─── Eliminar Producto ────────────────────────────────────────────────────
    def _confirmar_eliminar(self, codigo: str, e=None):
        accent = self.get_accent_color()
        text_color = self.get_text_color()
        card_bg = self.get_card_bg()

        def _hacer_eliminar(ev):
            self._close_dialog(ev)
            try:
                eliminar_producto(codigo)
                self._snack(f"Producto '{codigo}' eliminado.", ft.Colors.GREEN_700, ev)
                self._refrescar_tabla(ev)
            except ValueError as ex:
                self._snack(str(ex), ft.Colors.RED_700, ev)

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.Icons.DELETE_FOREVER_ROUNDED, color=ft.Colors.RED_400),
                ft.Text("Confirmar Eliminación", color=text_color),
            ], spacing=10),
            content=ft.Text(
                f"¿Está seguro de eliminar permanentemente el producto '{codigo}'?\n"
                "Esta acción no se puede deshacer.",
                color=text_color,
            ),
            actions=[
                ft.TextButton("Cancelar", on_click=self._close_dialog),
                ft.Button(
                    "Eliminar",
                    style=ft.ButtonStyle(
                        bgcolor=ft.Colors.RED_600, color=ft.Colors.WHITE,
                        shape=ft.RoundedRectangleBorder(radius=12)
                    ),
                    on_click=_hacer_eliminar,
                ),
            ],
            bgcolor=card_bg,
        )
        self._open_dialog(dlg, e)
