import flet as ft
from ui.views.base_view import BaseView
from services.bcv_service import actualizar_tasa, obtener_estado_tasa
from services.inventario_service import (
    crear_producto, obtener_producto, actualizar_producto,
    listar_productos, eliminar_producto,
)
from services.cartera_service import listar_proveedores


class InventarioView(BaseView):
    """Vista avanzada del Módulo de Inventario con motor BCV, filtros en cascada
    y flujo de registro en 3 pasos (ERS 3.1 / 3.2)."""

    ITEMS_PER_PAGE = 15

    def __init__(self, on_back_callback=None):
        self.on_back_callback = on_back_callback
        self._page_num = 1

        # ── Estado del formulario de ingreso ────────────────────────────────
        self._form_codigo_verificado = False
        self._editing_codigo: str | None = None

        # ── Dialogo activo (referencia para cerrarlo) ────────────────────────
        self._dialog: ft.AlertDialog | None = None

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
            on_submit=self._handle_actualizar_tasa,
        )

        btn_act_tasa = ft.Button(
            content="Actualizar Tasa",
            icon=ft.Icons.CURRENCY_EXCHANGE,
            bgcolor=accent,
            color=ft.Colors.WHITE,
            on_click=self._handle_actualizar_tasa,
        )

        return ft.Container(
            content=ft.Row(
                controls=[
                    ft.Row([self._lbl_tasa_icon, self._lbl_tasa], spacing=8),
                    ft.Row([self._inp_nueva_tasa, btn_act_tasa], spacing=10),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                wrap=True,
            ),
            padding=12,
            bgcolor=card_bg,
            border_radius=10,
            border=ft.Border.all(1, border),
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
        def campo(label, width=185):
            tf = ft.TextField(
                label=label, width=width,
                color=text_color, border_color=border, focused_border_color=accent,
                on_change=self._handle_filtro_change,
            )
            return tf

        self._f_codigo = campo("Código")
        self._f_descripcion = campo("Descripción", 250)
        self._f_marca = campo("Marca")
        self._f_departamento = campo("Departamento")

        btn_ingresar = ft.Button(
            content="  Ingresar Producto",
            icon=ft.Icons.ADD_BOX_ROUNDED,
            bgcolor=accent,
            color=ft.Colors.WHITE,
            on_click=self._abrir_flujo_ingreso,
        )

        btn_limpiar = ft.OutlinedButton(
            content="Limpiar filtros",
            icon=ft.Icons.FILTER_ALT_OFF_OUTLINED,
            on_click=self._handle_limpiar_filtros,
        )

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Icon(ft.Icons.SEARCH, color=accent, size=20),
                            ft.Text("Búsqueda y Filtros en Cascada (ERS 3.2)",
                                    size=14, weight=ft.FontWeight.BOLD, color=text_color),
                        ],
                        spacing=8,
                    ),
                    ft.Row(
                        controls=[
                            self._f_codigo,
                            self._f_descripcion,
                            self._f_marca,
                            self._f_departamento,
                            btn_limpiar,
                            btn_ingresar,
                        ],
                        spacing=12,
                        wrap=True,
                    ),
                ],
                spacing=10,
            ),
            padding=12,
            bgcolor=card_bg,
            border_radius=10,
            border=ft.Border.all(1, border),
        )

    def _handle_filtro_change(self, e):
        self._page_num = 1
        self._refrescar_tabla(e)

    def _handle_limpiar_filtros(self, e):
        self._f_codigo.value = ""
        self._f_descripcion.value = ""
        self._f_marca.value = ""
        self._f_departamento.value = ""
        self._page_num = 1
        self._refrescar_tabla(e)

    # ─────────────────────────────────────────────────────────────────────────
    # TABLA PRINCIPAL
    # ─────────────────────────────────────────────────────────────────────────
    def _build_tabla_panel(self, accent, card_bg, text_color, subtext, border) -> ft.Control:
        self._dt = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("Código", color=text_color, weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("Referencia", color=text_color, weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("Descripción", color=text_color, weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("Depto.", color=text_color, weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("Marca", color=text_color, weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("Precio $", color=text_color, weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("Precio Bs", color=text_color, weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("Exist.", color=text_color, weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("Acciones", color=accent, weight=ft.FontWeight.BOLD)),
            ],
            rows=[],
        )
        self._lbl_pag = ft.Text("", color=subtext, size=12)
        self._cargar_filas(text_color, accent)

        btn_prev = ft.IconButton(ft.Icons.CHEVRON_LEFT, on_click=self._pagina_anterior)
        btn_next = ft.IconButton(ft.Icons.CHEVRON_RIGHT, on_click=self._pagina_siguiente)

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Icon(ft.Icons.INVENTORY_2_ROUNDED, color=accent),
                            ft.Text("Catálogo de Productos", size=15, weight=ft.FontWeight.BOLD, color=text_color),
                        ],
                        spacing=8,
                    ),
                    ft.Container(
                        content=ft.Column(
                            controls=[
                                ft.ListView(controls=[self._dt], expand=True),
                                ft.Row(
                                    controls=[
                                        self._lbl_pag,
                                        ft.Row([btn_prev, btn_next], spacing=4),
                                    ],
                                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                ),
                            ],
                            expand=True,
                        ),
                        height=380,
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

        codigo_q = (getattr(self, "_f_codigo", None) and self._f_codigo.value or "").strip()
        desc_q = (getattr(self, "_f_descripcion", None) and self._f_descripcion.value or "").strip()
        marca_q = (getattr(self, "_f_marca", None) and self._f_marca.value or "").strip()
        depto_q = (getattr(self, "_f_departamento", None) and self._f_departamento.value or "").strip()

        # Búsqueda combinada AND — filtros en cascada
        busqueda = " ".join(filter(None, [codigo_q, desc_q, marca_q]))

        todos = listar_productos(
            departamento=depto_q,
            busqueda=busqueda,
            page=self._page_num,
            per_page=self.ITEMS_PER_PAGE,
        )

        # Filtro adicional por código exacto si hay valor
        if codigo_q:
            todos = [p for p in todos if codigo_q.lower() in p["codigo"].lower()]

        total_all = listar_productos(
            departamento=depto_q, busqueda=busqueda, page=1, per_page=9999
        )
        total = len(total_all)
        total_pags = max(1, (total + self.ITEMS_PER_PAGE - 1) // self.ITEMS_PER_PAGE)
        self._lbl_pag.value = f"Página {self._page_num} de {total_pags} | {total} productos"

        rows = []
        for p in todos:
            rows.append(
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(p["codigo"], color=accent, weight=ft.FontWeight.W_600)),
                        ft.DataCell(ft.Text(p["referencia"] or "-", color=text_color)),
                        ft.DataCell(ft.Text((p["descripcion_general"] or "-")[:40], color=text_color)),
                        ft.DataCell(ft.Text(p["departamento"] or "-", color=text_color)),
                        ft.DataCell(ft.Text(p["marca"] or "-", color=text_color)),
                        ft.DataCell(ft.Text(f"${p['precio_dolares']:.2f}", color=ft.Colors.GREEN_400)),
                        ft.DataCell(ft.Text(f"Bs {p['precio_bcv']:.2f}", color=ft.Colors.AMBER_300)),
                        ft.DataCell(ft.Text(str(p["existencia"]), color=text_color)),
                        ft.DataCell(
                            ft.Row([
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
                        ),
                    ]
                )
            )
        self._dt.rows = rows

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
                        bgcolor=accent, color=ft.Colors.WHITE,
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
            title=ft.Text("Ingresar Producto — Paso 1: Verificar Código", color=text_color),
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
                    bgcolor=accent, color=ft.Colors.WHITE,
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
            )

        # Controles del formulario
        cod_display = ft.TextField(
            label="Código *", value=codigo,
            width=200, disabled=True,
            color=text_color, border_color=border,
        )
        f_ref = tf("Referencia *", "referencia")
        f_desc = tf("Descripción General *", "descripcion_general", width=520)
        f_depto = tf("Departamento *", "departamento", width=200)
        f_marca = tf("Marca", "marca", width=200)
        f_barras = tf("Código de Barras", "codigo_barras", width=200)
        f_nombre_corto = tf("Nombre Corto (máx 30 car.)", "nombre_referencia_corto", width=260)
        f_precio_usd = tf("Precio USD ($)", "precio_dolares",
                          value=str(d.get("precio_dolares", "")),
                          width=160, kb=ft.KeyboardType.NUMBER)
        f_precio_bcv = tf("Precio BCV (Bs)", "precio_bcv",
                          value=str(d.get("precio_bcv", "")),
                          width=160, kb=ft.KeyboardType.NUMBER)
        f_existencia = tf("Existencia", "existencia",
                          value=str(d.get("existencia", "0")),
                          width=120, kb=ft.KeyboardType.NUMBER)

        # Fila de precios (se oculta si existencia == 0)
        fila_precios = ft.Row([f_precio_usd, f_precio_bcv], spacing=12, visible=float(d.get("existencia", 1) or 1) != 0)

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
        )

        titulo_paso = "Editar Producto" if self._editing_codigo else "Ingresar Producto — Paso 2: Datos"

        def _guardar(ev):
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
                    bgcolor=accent, color=ft.Colors.WHITE,
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
            ("Precio USD ($)", "precio_dolares"),
            ("Precio BCV (Bs)", "precio_bcv"),
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
                ft.TextButton("Cancelar", on_click=self._close_dialog),
                ft.OutlinedButton("Editar", icon=ft.Icons.EDIT_OUTLINED, on_click=_editar),
                ft.Button(
                    "Aceptar — Guardar",
                    icon=ft.Icons.SAVE_OUTLINED,
                    bgcolor=accent, color=ft.Colors.WHITE,
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
                    "Eliminar", bgcolor=ft.Colors.RED_600, color=ft.Colors.WHITE,
                    on_click=_hacer_eliminar,
                ),
            ],
            bgcolor=card_bg,
        )
        self._open_dialog(dlg, e)
