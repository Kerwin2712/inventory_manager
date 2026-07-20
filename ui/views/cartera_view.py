import flet as ft
from ui.views.base_view import BaseView
from services.cartera_service import (
    crear_cliente, obtener_cliente, buscar_cliente_por_cedula, actualizar_cliente, eliminar_cliente, listar_clientes,
    crear_proveedor, obtener_proveedor, buscar_proveedores, actualizar_proveedor, eliminar_proveedor, listar_proveedores
)

class CarteraView(BaseView):
    """Vista avanzada para la gestión de la Cartera de Clientes y Proveedores."""

    ITEMS_PER_PAGE = 10

    def __init__(self, on_back_callback=None):
        self.on_back_callback = on_back_callback
        self.adjuntos_temp = []
        self.current_tab = "clientes"
        
        # Estado de paginación
        self.cli_page = 1
        self.prov_page = 1
        
        # Estado de edición
        self.cli_editing_cedula = None
        self.prov_editing_id = None
        
        super().__init__(route="/cartera", title="Cartera de Clientes y Proveedores")

    def get_current_page(self, e=None):
        """Obtiene de manera segura la instancia de page activa desde el evento o el control."""
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
        """Actualiza la interfaz de forma segura evitando RuntimeError en controles secundarios."""
        p = self.get_current_page(e)
        if p:
            p.update()
        else:
            try:
                self.update()
            except (RuntimeError, AttributeError):
                pass

    def handle_tab_change(self, e):
        """Cambia la pestaña activa (Clientes o Proveedores)."""
        if e.control.selected:
            selected_list = list(e.control.selected)
            if selected_list:
                self.current_tab = selected_list[0]
                self.rebuild_ui()
                self.safe_update(e)

    def get_body(self) -> ft.Control:
        accent = self.get_accent_color()
        card_bg = self.get_card_bg()
        text_color = self.get_text_color()
        subtext_color = self.get_subtext_color()
        border_color = self.get_border_color()

        tabs_selector = ft.SegmentedButton(
            selected=[self.current_tab],
            allow_empty_selection=False,
            segments=[
                ft.Segment(
                    value="clientes",
                    label=ft.Text("Clientes", color=text_color, weight=ft.FontWeight.BOLD),
                    icon=ft.Icon(ft.Icons.PEOPLE_ALT_OUTLINED, color=accent),
                ),
                ft.Segment(
                    value="proveedores",
                    label=ft.Text("Proveedores", color=text_color, weight=ft.FontWeight.BOLD),
                    icon=ft.Icon(ft.Icons.BUSINESS_OUTLINED, color=accent),
                ),
            ],
            on_change=self.handle_tab_change,
        )

        if self.current_tab == "clientes":
            content_area = self.build_clientes_tab(accent, card_bg, text_color, subtext_color, border_color)
        else:
            content_area = self.build_proveedores_tab(accent, card_bg, text_color, subtext_color, border_color)

        return ft.Column(
            controls=[
                ft.Row([tabs_selector], alignment=ft.MainAxisAlignment.START),
                ft.Divider(height=10, color=border_color),
                ft.Container(content=content_area, expand=True),
            ],
            spacing=15,
            expand=True,
        )

    # ==========================================
    # PESTAÑA CLIENTES
    # ==========================================
    def build_clientes_tab(self, accent, card_bg, text_color, subtext_color, border_color) -> ft.Control:
        # 1. Barra de Búsqueda
        self.cli_search_input = ft.TextField(
            label="Buscar por Cédula o RIF",
            hint_text="Ej: J-98765432-1",
            width=300,
            color=text_color,
            border_color=border_color,
            focused_border_color=accent,
            on_submit=self.handle_buscar_cliente,
        )

        btn_buscar_cli = ft.Button(
            content="Buscar",
            icon=ft.Icons.SEARCH,
            bgcolor=accent,
            color=ft.Colors.WHITE,
            on_click=self.handle_buscar_cliente,
        )

        btn_nuevo_cli = ft.OutlinedButton(
            content="Nuevo Cliente",
            icon=ft.Icons.ADD,
            on_click=self.handle_mostrar_form_cliente,
        )

        search_bar = ft.Container(
            content=ft.Row([self.cli_search_input, btn_buscar_cli, btn_nuevo_cli], spacing=10, alignment=ft.MainAxisAlignment.START),
            padding=10,
            border_radius=8,
            bgcolor=card_bg,
            border=ft.Border.all(1, border_color),
        )

        # 2. Tarjeta de Resultado de Búsqueda
        self.cli_result_container = ft.Container(visible=False)

        # 3. Formulario (Oculto por defecto)
        self.cli_cedula = ft.TextField(label="Cédula / RIF *", width=250, color=text_color, border_color=border_color, focused_border_color=accent)
        self.cli_nombre = ft.TextField(label="Nombre / Razón Social *", width=300, color=text_color, border_color=border_color, focused_border_color=accent)
        self.cli_telefono = ft.TextField(label="Teléfono", width=250, color=text_color, border_color=border_color, focused_border_color=accent)
        self.cli_correo = ft.TextField(label="Correo", width=300, color=text_color, border_color=border_color, focused_border_color=accent)
        self.cli_direccion = ft.TextField(label="Dirección", width=565, multiline=True, max_lines=2, color=text_color, border_color=border_color, focused_border_color=accent)

        self.btn_guardar_cli_label = ft.Text("Guardar Cliente", color=ft.Colors.WHITE)
        btn_guardar_cli = ft.Button(
            content=self.btn_guardar_cli_label,
            bgcolor=accent,
            color=ft.Colors.WHITE,
            on_click=self.handle_guardar_cliente,
        )
        btn_cancelar_cli = ft.OutlinedButton(
            content="Cancelar",
            on_click=self.handle_ocultar_form_cliente,
        )

        self.cli_form_container = ft.Container(
            content=ft.Column(
                controls=[
                    ft.Text("Formulario de Registro / Edición de Cliente", size=16, weight=ft.FontWeight.BOLD, color=accent),
                    ft.Row([self.cli_cedula, self.cli_nombre], wrap=True, spacing=15),
                    ft.Row([self.cli_telefono, self.cli_correo], wrap=True, spacing=15),
                    self.cli_direccion,
                    ft.Row([btn_cancelar_cli, btn_guardar_cli], alignment=ft.MainAxisAlignment.END, spacing=10),
                ],
                spacing=12,
            ),
            padding=15,
            border_radius=10,
            bgcolor=card_bg,
            border=ft.Border.all(1, border_color),
            visible=False,
        )

        # 4. Tabla DataGrid con Paginación
        self.dt_clientes = ft.DataTable(
            columns=[
                ft.DataColumn(label=ft.Text("Cédula / RIF", weight=ft.FontWeight.BOLD, color=text_color)),
                ft.DataColumn(label=ft.Text("Nombre / Razón Social", weight=ft.FontWeight.BOLD, color=text_color)),
                ft.DataColumn(label=ft.Text("Teléfono", weight=ft.FontWeight.BOLD, color=text_color)),
                ft.DataColumn(label=ft.Text("Correo", weight=ft.FontWeight.BOLD, color=text_color)),
                ft.DataColumn(label=ft.Text("Acciones", weight=ft.FontWeight.BOLD, color=accent)),
            ],
            rows=[],
        )
        self.txt_cli_pagination = ft.Text("", color=subtext_color, size=13)
        self.cargar_tabla_clientes(text_color, accent)

        btn_cli_prev = ft.IconButton(icon=ft.Icons.CHEVRON_LEFT, on_click=self.cli_pagina_anterior)
        btn_cli_next = ft.IconButton(icon=ft.Icons.CHEVRON_RIGHT, on_click=self.cli_pagina_siguiente)

        pagination_bar = ft.Row(
            controls=[
                self.txt_cli_pagination,
                ft.Row([btn_cli_prev, btn_cli_next], spacing=5),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )

        return ft.Column(
            controls=[
                search_bar,
                self.cli_result_container,
                self.cli_form_container,
                ft.Container(height=5),
                ft.Text("Directorio General de Clientes", size=18, weight=ft.FontWeight.BOLD, color=text_color),
                ft.Container(
                    content=ft.Column(
                        controls=[
                            ft.ListView(controls=[self.dt_clientes], expand=True),
                            pagination_bar,
                        ],
                        expand=True,
                    ),
                    height=300,
                    padding=10,
                    border_radius=10,
                    bgcolor=card_bg,
                    border=ft.Border.all(1, border_color),
                ),
            ],
            scroll=ft.ScrollMode.AUTO,
            spacing=10,
            expand=True,
        )

    # ==========================================
    # PESTAÑA PROVEEDORES
    # ==========================================
    def build_proveedores_tab(self, accent, card_bg, text_color, subtext_color, border_color) -> ft.Control:
        # 1. Barra de Búsqueda
        self.prov_search_input = ft.TextField(
            label="Buscar por Empresa o Teléfono",
            hint_text="Ej: TecnoCorp",
            width=300,
            color=text_color,
            border_color=border_color,
            focused_border_color=accent,
            on_submit=self.handle_buscar_proveedor,
        )

        btn_buscar_prov = ft.Button(
            content="Buscar",
            icon=ft.Icons.SEARCH,
            bgcolor=accent,
            color=ft.Colors.WHITE,
            on_click=self.handle_buscar_proveedor,
        )

        btn_nuevo_prov = ft.OutlinedButton(
            content="Nuevo Proveedor",
            icon=ft.Icons.ADD,
            on_click=self.handle_mostrar_form_proveedor,
        )

        search_bar = ft.Container(
            content=ft.Row([self.prov_search_input, btn_buscar_prov, btn_nuevo_prov], spacing=10, alignment=ft.MainAxisAlignment.START),
            padding=10,
            border_radius=8,
            bgcolor=card_bg,
            border=ft.Border.all(1, border_color),
        )

        # 2. Tarjeta de Resultado de Búsqueda
        self.prov_result_container = ft.Container(visible=False)

        # 3. Formulario (Oculto por defecto)
        self.prov_empresa = ft.TextField(label="Nombre de la Empresa", width=300, color=text_color, border_color=border_color, focused_border_color=accent)
        self.prov_contacto = ft.TextField(label="Agente de Contacto", width=250, color=text_color, border_color=border_color, focused_border_color=accent)
        self.prov_telefono = ft.TextField(label="Teléfono *", width=250, color=text_color, border_color=border_color, focused_border_color=accent)
        self.prov_correo = ft.TextField(label="Correo", width=300, color=text_color, border_color=border_color, focused_border_color=accent)
        self.prov_desc = ft.TextField(label="Descripción / Categoría", width=565, color=text_color, border_color=border_color, focused_border_color=accent)

        self.txt_adjuntos_status = ft.Text("Sin archivos adjuntos", size=12, color=subtext_color)
        btn_adjuntar = ft.OutlinedButton(
            content="Adjuntar Catálogo (PDF / Img)",
            icon=ft.Icons.ATTACH_FILE,
            on_click=self.handle_adjuntar_simulado,
        )

        self.btn_guardar_prov_label = ft.Text("Guardar Proveedor", color=ft.Colors.WHITE)
        btn_guardar_prov = ft.Button(
            content=self.btn_guardar_prov_label,
            bgcolor=accent,
            color=ft.Colors.WHITE,
            on_click=self.handle_guardar_proveedor,
        )
        btn_cancelar_prov = ft.OutlinedButton(
            content="Cancelar",
            on_click=self.handle_ocultar_form_proveedor,
        )

        self.prov_form_container = ft.Container(
            content=ft.Column(
                controls=[
                    ft.Text("Formulario de Registro / Edición de Proveedor", size=16, weight=ft.FontWeight.BOLD, color=accent),
                    ft.Row([self.prov_empresa, self.prov_contacto], wrap=True, spacing=15),
                    ft.Row([self.prov_telefono, self.prov_correo], wrap=True, spacing=15),
                    self.prov_desc,
                    ft.Row([btn_adjuntar, self.txt_adjuntos_status], alignment=ft.MainAxisAlignment.START, spacing=10),
                    ft.Row([btn_cancelar_prov, btn_guardar_prov], alignment=ft.MainAxisAlignment.END, spacing=10),
                ],
                spacing=12,
            ),
            padding=15,
            border_radius=10,
            bgcolor=card_bg,
            border=ft.Border.all(1, border_color),
            visible=False,
        )

        # 4. Tabla DataGrid con Paginación
        self.dt_proveedores = ft.DataTable(
            columns=[
                ft.DataColumn(label=ft.Text("ID", weight=ft.FontWeight.BOLD, color=text_color)),
                ft.DataColumn(label=ft.Text("Empresa", weight=ft.FontWeight.BOLD, color=text_color)),
                ft.DataColumn(label=ft.Text("Contacto", weight=ft.FontWeight.BOLD, color=text_color)),
                ft.DataColumn(label=ft.Text("Teléfono", weight=ft.FontWeight.BOLD, color=text_color)),
                ft.DataColumn(label=ft.Text("Correo", weight=ft.FontWeight.BOLD, color=text_color)),
                ft.DataColumn(label=ft.Text("Acciones", weight=ft.FontWeight.BOLD, color=accent)),
            ],
            rows=[],
        )
        self.txt_prov_pagination = ft.Text("", color=subtext_color, size=13)
        self.cargar_tabla_proveedores(text_color, accent)

        btn_prov_prev = ft.IconButton(icon=ft.Icons.CHEVRON_LEFT, on_click=self.prov_pagina_anterior)
        btn_prov_next = ft.IconButton(icon=ft.Icons.CHEVRON_RIGHT, on_click=self.prov_pagina_siguiente)

        pagination_bar = ft.Row(
            controls=[
                self.txt_prov_pagination,
                ft.Row([btn_prov_prev, btn_prov_next], spacing=5),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )

        return ft.Column(
            controls=[
                search_bar,
                self.prov_result_container,
                self.prov_form_container,
                ft.Container(height=5),
                ft.Text("Catálogo General de Proveedores", size=18, weight=ft.FontWeight.BOLD, color=text_color),
                ft.Container(
                    content=ft.Column(
                        controls=[
                            ft.ListView(controls=[self.dt_proveedores], expand=True),
                            pagination_bar,
                        ],
                        expand=True,
                    ),
                    height=300,
                    padding=10,
                    border_radius=10,
                    bgcolor=card_bg,
                    border=ft.Border.all(1, border_color),
                ),
            ],
            scroll=ft.ScrollMode.AUTO,
            spacing=10,
            expand=True,
        )

    # ==========================================
    # MANEJO DE EVENTOS BÚSQUEDA Y ACCIONES CLIENTES
    # ==========================================
    def handle_buscar_cliente(self, e):
        cedula = (self.cli_search_input.value or "").strip()
        if not cedula:
            self.show_alert_info("Ingrese una Cédula o RIF para realizar la búsqueda.", e)
            return

        cliente = buscar_cliente_por_cedula(cedula)
        text_color = self.get_text_color()
        card_bg = self.get_card_bg()
        border_color = self.get_border_color()

        if cliente:
            self.cli_form_container.visible = False
            self.cli_result_container.content = ft.Card(
                content=ft.Container(
                    content=ft.Column(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Row([
                                        ft.Icon(ft.Icons.CHECK_CIRCLE, color=ft.Colors.GREEN_500, size=24),
                                        ft.Text(f"Cliente Encontrado: {cliente['nombre']}", size=16, weight=ft.FontWeight.BOLD, color=text_color),
                                    ], spacing=10),
                                    ft.Row([
                                        ft.OutlinedButton("Editar", icon=ft.Icons.EDIT, on_click=lambda ev, c=cliente: self.preparar_edicion_cliente(c, ev)),
                                        ft.Button("Eliminar", icon=ft.Icons.DELETE_OUTLINED, bgcolor=ft.Colors.RED_600, color=ft.Colors.WHITE, on_click=lambda ev, c=cliente["cedula_rif"]: self.handle_eliminar_cliente(c, ev)),
                                    ], spacing=10),
                                ],
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            ),
                            ft.Text(f"Cédula/RIF: {cliente['cedula_rif']} | Teléfono: {cliente['telefono'] or '-'} | Correo: {cliente['correo'] or '-'}", color=text_color),
                            ft.Text(f"Dirección: {cliente['direccion'] or '-'}", color=self.get_subtext_color()),
                        ],
                        spacing=8,
                    ),
                    padding=15,
                    bgcolor=card_bg,
                    border_radius=8,
                    border=ft.Border.all(1, border_color),
                )
            )
            self.cli_result_container.visible = True
            self.safe_update(e)
        else:
            self.cli_result_container.visible = False
            self.show_alert_info(f"El cliente con Cédula/RIF '{cedula}' no existe. Proceda a registrarlo.", e)
            self.limpiar_form_cliente()
            self.cli_cedula.value = cedula
            self.cli_editing_cedula = None
            self.btn_guardar_cli_label.value = "Guardar Cliente"
            self.cli_form_container.visible = True
            self.safe_update(e)

    def preparar_edicion_cliente(self, cliente: dict, e=None):
        self.cli_result_container.visible = False
        self.cli_editing_cedula = cliente["cedula_rif"]
        self.cli_cedula.value = cliente["cedula_rif"]
        self.cli_cedula.disabled = True
        self.cli_nombre.value = cliente["nombre"]
        self.cli_direccion.value = cliente["direccion"] or ""
        self.cli_telefono.value = cliente["telefono"] or ""
        self.cli_correo.value = cliente["correo"] or ""
        self.btn_guardar_cli_label.value = "Actualizar Cliente"
        self.cli_form_container.visible = True
        self.safe_update(e)

    def handle_guardar_cliente(self, e):
        try:
            if self.cli_editing_cedula:
                actualizar_cliente(
                    cedula_rif=self.cli_editing_cedula,
                    nombre=self.cli_nombre.value,
                    direccion=self.cli_direccion.value,
                    telefono=self.cli_telefono.value,
                    correo=self.cli_correo.value,
                )
                self.show_alert_success("¡Cliente actualizado exitosamente!", e)
            else:
                crear_cliente(
                    nombre=self.cli_nombre.value,
                    cedula_rif=self.cli_cedula.value,
                    direccion=self.cli_direccion.value,
                    telefono=self.cli_telefono.value,
                    correo=self.cli_correo.value,
                )
                self.show_alert_success("¡Cliente registrado exitosamente!", e)

            self.limpiar_form_cliente()
            self.cli_form_container.visible = False
            self.cli_result_container.visible = False
            self.rebuild_ui()
            self.safe_update(e)
        except ValueError as ex:
            self.show_alert_error(str(ex), e)

    def handle_eliminar_cliente(self, cedula_rif: str, e=None):
        try:
            eliminar_cliente(cedula_rif)
            self.show_alert_success(f"Cliente '{cedula_rif}' eliminado correctamente.", e)
            self.cli_result_container.visible = False
            self.rebuild_ui()
            self.safe_update(e)
        except ValueError as ex:
            self.show_alert_error(str(ex), e)

    def handle_mostrar_form_cliente(self, e):
        self.cli_result_container.visible = False
        self.limpiar_form_cliente()
        self.cli_editing_cedula = None
        self.cli_cedula.disabled = False
        self.btn_guardar_cli_label.value = "Guardar Cliente"
        self.cli_form_container.visible = True
        self.safe_update(e)

    def handle_ocultar_form_cliente(self, e):
        self.cli_form_container.visible = False
        self.limpiar_form_cliente()
        self.safe_update(e)

    # ==========================================
    # MANEJO DE EVENTOS BÚSQUEDA Y ACCIONES PROVEEDORES
    # ==========================================
    def handle_buscar_proveedor(self, e):
        criterio = (self.prov_search_input.value or "").strip()
        if not criterio:
            self.show_alert_info("Ingrese el nombre de la empresa o teléfono para buscar.", e)
            return

        proveedores = buscar_proveedores(criterio)
        text_color = self.get_text_color()
        card_bg = self.get_card_bg()
        border_color = self.get_border_color()

        if proveedores:
            prov = proveedores[0]
            self.prov_form_container.visible = False
            self.prov_result_container.content = ft.Card(
                content=ft.Container(
                    content=ft.Column(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Row([
                                        ft.Icon(ft.Icons.CHECK_CIRCLE, color=ft.Colors.GREEN_500, size=24),
                                        ft.Text(f"Proveedor Encontrado: {prov['empresa'] or prov['contacto']}", size=16, weight=ft.FontWeight.BOLD, color=text_color),
                                    ], spacing=10),
                                    ft.Row([
                                        ft.OutlinedButton("Editar", icon=ft.Icons.EDIT, on_click=lambda ev, p=prov: self.preparar_edicion_proveedor(p, ev)),
                                        ft.Button("Eliminar", icon=ft.Icons.DELETE_OUTLINED, bgcolor=ft.Colors.RED_600, color=ft.Colors.WHITE, on_click=lambda ev, pid=prov["id"]: self.handle_eliminar_proveedor(pid, ev)),
                                    ], spacing=10),
                                ],
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            ),
                            ft.Text(f"ID: {prov['id']} | Teléfono: {prov['telefono']} | Correo: {prov['correo'] or '-'}", color=text_color),
                            ft.Text(f"Descripción / Categoría: {prov['descripcion'] or '-'}", color=self.get_subtext_color()),
                        ],
                        spacing=8,
                    ),
                    padding=15,
                    bgcolor=card_bg,
                    border_radius=8,
                    border=ft.Border.all(1, border_color),
                )
            )
            self.prov_result_container.visible = True
            self.safe_update(e)
        else:
            self.prov_result_container.visible = False
            self.show_alert_info(f"Proveedor '{criterio}' no encontrado. Proceda a registrarlo.", e)
            self.limpiar_form_proveedor()
            if criterio.isdigit():
                self.prov_telefono.value = criterio
            else:
                self.prov_empresa.value = criterio
            self.prov_editing_id = None
            self.btn_guardar_prov_label.value = "Guardar Proveedor"
            self.prov_form_container.visible = True
            self.safe_update(e)

    def preparar_edicion_proveedor(self, prov: dict, e=None):
        self.prov_result_container.visible = False
        self.prov_editing_id = prov["id"]
        self.prov_empresa.value = prov["empresa"] or ""
        self.prov_contacto.value = prov["contacto"] or ""
        self.prov_telefono.value = prov["telefono"] or ""
        self.prov_correo.value = prov["correo"] or ""
        self.prov_desc.value = prov["descripcion"] or ""
        self.adjuntos_temp = prov.get("adjuntos", [])
        self.btn_guardar_prov_label.value = "Actualizar Proveedor"
        self.prov_form_container.visible = True
        self.safe_update(e)

    def handle_guardar_proveedor(self, e):
        try:
            if self.prov_editing_id:
                actualizar_proveedor(
                    proveedor_id=self.prov_editing_id,
                    empresa=self.prov_empresa.value,
                    contacto=self.prov_contacto.value,
                    telefono=self.prov_telefono.value,
                    correo=self.prov_correo.value,
                    descripcion=self.prov_desc.value,
                    adjuntos=self.adjuntos_temp,
                )
                self.show_alert_success("¡Proveedor actualizado exitosamente!", e)
            else:
                crear_proveedor(
                    empresa=self.prov_empresa.value,
                    contacto=self.prov_contacto.value,
                    telefono=self.prov_telefono.value,
                    correo=self.prov_correo.value,
                    descripcion=self.prov_desc.value,
                    adjuntos=self.adjuntos_temp,
                )
                self.show_alert_success("¡Proveedor registrado exitosamente!", e)

            self.limpiar_form_proveedor()
            self.prov_form_container.visible = False
            self.prov_result_container.visible = False
            self.rebuild_ui()
            self.safe_update(e)
        except ValueError as ex:
            self.show_alert_error(str(ex), e)

    def handle_eliminar_proveedor(self, proveedor_id: int, e=None):
        try:
            eliminar_proveedor(proveedor_id)
            self.show_alert_success(f"Proveedor ID '{proveedor_id}' eliminado correctamente.", e)
            self.prov_result_container.visible = False
            self.rebuild_ui()
            self.safe_update(e)
        except ValueError as ex:
            self.show_alert_error(str(ex), e)

    def handle_mostrar_form_proveedor(self, e):
        self.prov_result_container.visible = False
        self.limpiar_form_proveedor()
        self.prov_editing_id = None
        self.btn_guardar_prov_label.value = "Guardar Proveedor"
        self.prov_form_container.visible = True
        self.safe_update(e)

    def handle_ocultar_form_proveedor(self, e):
        self.prov_form_container.visible = False
        self.limpiar_form_proveedor()
        self.safe_update(e)

    # ==========================================
    # PAGINACIÓN Y CARGA DE TABLAS
    # ==========================================
    def cargar_tabla_clientes(self, text_color, accent):
        todos = listar_clientes()
        total_items = len(todos)
        total_paginas = max(1, (total_items + self.ITEMS_PER_PAGE - 1) // self.ITEMS_PER_PAGE)
        
        if self.cli_page > total_paginas:
            self.cli_page = total_paginas
        if self.cli_page < 1:
            self.cli_page = 1

        start_idx = (self.cli_page - 1) * self.ITEMS_PER_PAGE
        end_idx = start_idx + self.ITEMS_PER_PAGE
        pagina_items = todos[start_idx:end_idx]

        rows = []
        for c in pagina_items:
            rows.append(
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(c["cedula_rif"], color=text_color)),
                        ft.DataCell(ft.Text(c["nombre"], color=text_color)),
                        ft.DataCell(ft.Text(c["telefono"] or "-", color=text_color)),
                        ft.DataCell(ft.Text(c["correo"] or "-", color=text_color)),
                        ft.DataCell(
                            ft.Row([
                                ft.IconButton(ft.Icons.EDIT_OUTLINED, icon_color=accent, tooltip="Editar", on_click=lambda ev, item=c: self.preparar_edicion_cliente(item, ev)),
                                ft.IconButton(ft.Icons.DELETE_OUTLINED, icon_color=ft.Colors.RED_400, tooltip="Eliminar", on_click=lambda ev, item=c["cedula_rif"]: self.handle_eliminar_cliente(item, ev)),
                            ], spacing=0)
                        ),
                    ]
                )
            )
        self.dt_clientes.rows = rows
        self.txt_cli_pagination.value = f"Página {self.cli_page} de {total_paginas} (Total: {total_items} clientes)"

    def cli_pagina_anterior(self, e):
        if self.cli_page > 1:
            self.cli_page -= 1
            self.rebuild_ui()
            self.safe_update(e)

    def cli_pagina_siguiente(self, e):
        todos = listar_clientes()
        total_paginas = max(1, (len(todos) + self.ITEMS_PER_PAGE - 1) // self.ITEMS_PER_PAGE)
        if self.cli_page < total_paginas:
            self.cli_page += 1
            self.rebuild_ui()
            self.safe_update(e)

    def cargar_tabla_proveedores(self, text_color, accent):
        todos = listar_proveedores()
        total_items = len(todos)
        total_paginas = max(1, (total_items + self.ITEMS_PER_PAGE - 1) // self.ITEMS_PER_PAGE)

        if self.prov_page > total_paginas:
            self.prov_page = total_paginas
        if self.prov_page < 1:
            self.prov_page = 1

        start_idx = (self.prov_page - 1) * self.ITEMS_PER_PAGE
        end_idx = start_idx + self.ITEMS_PER_PAGE
        pagina_items = todos[start_idx:end_idx]

        rows = []
        for p in pagina_items:
            rows.append(
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(str(p["id"]), color=text_color)),
                        ft.DataCell(ft.Text(p["empresa"] or "-", color=text_color)),
                        ft.DataCell(ft.Text(p["contacto"] or "-", color=text_color)),
                        ft.DataCell(ft.Text(p["telefono"], color=text_color)),
                        ft.DataCell(ft.Text(p["correo"] or "-", color=text_color)),
                        ft.DataCell(
                            ft.Row([
                                ft.IconButton(ft.Icons.EDIT_OUTLINED, icon_color=accent, tooltip="Editar", on_click=lambda ev, item=p: self.preparar_edicion_proveedor(item, ev)),
                                ft.IconButton(ft.Icons.DELETE_OUTLINED, icon_color=ft.Colors.RED_400, tooltip="Eliminar", on_click=lambda ev, pid=p["id"]: self.handle_eliminar_proveedor(pid, ev)),
                            ], spacing=0)
                        ),
                    ]
                )
            )
        self.dt_proveedores.rows = rows
        self.txt_prov_pagination.value = f"Página {self.prov_page} de {total_paginas} (Total: {total_items} proveedores)"

    def prov_pagina_anterior(self, e):
        if self.prov_page > 1:
            self.prov_page -= 1
            self.rebuild_ui()
            self.safe_update(e)

    def prov_pagina_siguiente(self, e):
        todos = listar_proveedores()
        total_paginas = max(1, (len(todos) + self.ITEMS_PER_PAGE - 1) // self.ITEMS_PER_PAGE)
        if self.prov_page < total_paginas:
            self.prov_page += 1
            self.rebuild_ui()
            self.safe_update(e)

    # ==========================================
    # ALERTAS FLOTANTES ROBUSTAS
    # ==========================================
    def show_alert_error(self, message: str, e=None):
        """Muestra una alerta flotante de error en pantalla usando SnackBar."""
        p = self.get_current_page(e)
        if p:
            snack = ft.SnackBar(
                content=ft.Text(message, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD),
                bgcolor=ft.Colors.RED_700,
                duration=4000,
            )
            p.overlay.append(snack)
            snack.open = True
            p.update()

    def show_alert_success(self, message: str, e=None):
        """Muestra una alerta flotante de éxito en pantalla usando SnackBar."""
        p = self.get_current_page(e)
        if p:
            snack = ft.SnackBar(
                content=ft.Text(message, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD),
                bgcolor=ft.Colors.GREEN_700,
                duration=3000,
            )
            p.overlay.append(snack)
            snack.open = True
            p.update()

    def show_alert_info(self, message: str, e=None):
        """Muestra una alerta informativa suave en pantalla usando SnackBar."""
        p = self.get_current_page(e)
        if p:
            snack = ft.SnackBar(
                content=ft.Text(message, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD),
                bgcolor=ft.Colors.BLUE_700,
                duration=3000,
            )
            p.overlay.append(snack)
            snack.open = True
            p.update()

    def handle_adjuntar_simulado(self, e):
        """Simula la carga de un archivo adjunto digital."""
        file_name = f"catalogo_prov_{len(self.adjuntos_temp) + 1}.pdf"
        self.adjuntos_temp.append(file_name)
        self.txt_adjuntos_status.value = f"Adjuntos ({len(self.adjuntos_temp)}): {', '.join(self.adjuntos_temp)}"
        self.safe_update(e)

    def limpiar_form_cliente(self):
        self.cli_cedula.value = ""
        self.cli_cedula.disabled = False
        self.cli_nombre.value = ""
        self.cli_direccion.value = ""
        self.cli_telefono.value = ""
        self.cli_correo.value = ""
        self.cli_editing_cedula = None

    def limpiar_form_proveedor(self):
        self.prov_empresa.value = ""
        self.prov_contacto.value = ""
        self.prov_telefono.value = ""
        self.prov_correo.value = ""
        self.prov_desc.value = ""
        self.prov_editing_id = None
        self.adjuntos_temp = []
        self.txt_adjuntos_status.value = "Sin archivos adjuntos"
