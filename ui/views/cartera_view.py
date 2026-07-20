import flet as ft
from ui.views.base_view import BaseView
from services.cartera_service import (
    crear_cliente, listar_clientes,
    crear_proveedor, listar_proveedores
)

class CarteraView(BaseView):
    """Vista para la gestión de la Cartera de Clientes y Proveedores."""

    def __init__(self, on_back_callback=None):
        self.on_back_callback = on_back_callback
        self.adjuntos_temp = []
        self.current_tab = "clientes"
        super().__init__(route="/cartera", title="Cartera de Clientes y Proveedores")

    def handle_tab_change(self, e):
        """Cambia la pestaña activa (Clientes o Proveedores)."""
        if e.control.selected:
            selected_list = list(e.control.selected)
            if selected_list:
                self.current_tab = selected_list[0]
                self.rebuild_ui()

    def get_body(self) -> ft.Control:
        accent = self.get_accent_color()
        card_bg = self.get_card_bg()
        text_color = self.get_text_color()
        subtext_color = self.get_subtext_color()
        border_color = self.get_border_color()

        # Selector de pestañas elegante
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

    def build_clientes_tab(self, accent, card_bg, text_color, subtext_color, border_color) -> ft.Control:
        """Construye la vista de la pestaña de Clientes."""
        self.cli_cedula = ft.TextField(
            label="Cédula / RIF *",
            width=250,
            color=text_color,
            border_color=border_color,
            focused_border_color=accent,
            label_style=ft.TextStyle(color=subtext_color),
        )
        self.cli_nombre = ft.TextField(
            label="Nombre / Razón Social *",
            width=300,
            color=text_color,
            border_color=border_color,
            focused_border_color=accent,
            label_style=ft.TextStyle(color=subtext_color),
        )
        self.cli_telefono = ft.TextField(
            label="Teléfono de Contacto",
            width=250,
            color=text_color,
            border_color=border_color,
            focused_border_color=accent,
            label_style=ft.TextStyle(color=subtext_color),
        )
        self.cli_correo = ft.TextField(
            label="Correo Electrónico (Opcional)",
            width=300,
            color=text_color,
            border_color=border_color,
            focused_border_color=accent,
            label_style=ft.TextStyle(color=subtext_color),
        )
        self.cli_direccion = ft.TextField(
            label="Dirección de Habitación o Fiscal",
            width=565,
            multiline=True,
            max_lines=2,
            color=text_color,
            border_color=border_color,
            focused_border_color=accent,
            label_style=ft.TextStyle(color=subtext_color),
        )

        btn_guardar_cliente = ft.Button(
            content="Guardar Cliente",
            bgcolor=accent,
            color=ft.Colors.WHITE,
            on_click=self.handle_guardar_cliente,
        )

        self.dt_clientes = ft.DataTable(
            columns=[
                ft.DataColumn(label=ft.Text("Cédula / RIF", weight=ft.FontWeight.BOLD, color=text_color)),
                ft.DataColumn(label=ft.Text("Nombre / Razón Social", weight=ft.FontWeight.BOLD, color=text_color)),
                ft.DataColumn(label=ft.Text("Teléfono", weight=ft.FontWeight.BOLD, color=text_color)),
                ft.DataColumn(label=ft.Text("Correo", weight=ft.FontWeight.BOLD, color=text_color)),
                ft.DataColumn(label=ft.Text("Dirección", weight=ft.FontWeight.BOLD, color=text_color)),
            ],
            rows=[],
        )
        self.cargar_tabla_clientes(text_color)

        return ft.Column(
            controls=[
                ft.Container(
                    content=ft.Column(
                        controls=[
                            ft.Text("Registro de Nuevo Cliente", size=18, weight=ft.FontWeight.BOLD, color=accent),
                            ft.Row([self.cli_cedula, self.cli_nombre], wrap=True, spacing=15),
                            ft.Row([self.cli_telefono, self.cli_correo], wrap=True, spacing=15),
                            self.cli_direccion,
                            ft.Row([btn_guardar_cliente], alignment=ft.MainAxisAlignment.END),
                        ],
                        spacing=12,
                    ),
                    padding=15,
                    border_radius=10,
                    bgcolor=card_bg,
                    border=ft.Border.all(1, border_color),
                ),
                ft.Container(height=10),
                ft.Text("Directorio de Clientes Registrados", size=18, weight=ft.FontWeight.BOLD, color=text_color),
                ft.Container(
                    content=ft.ListView(
                        controls=[self.dt_clientes],
                        expand=True,
                    ),
                    height=280,
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

    def build_proveedores_tab(self, accent, card_bg, text_color, subtext_color, border_color) -> ft.Control:
        """Construye la vista de la pestaña de Proveedores."""
        self.prov_empresa = ft.TextField(
            label="Nombre de la Empresa / Firma Comercial",
            width=300,
            color=text_color,
            border_color=border_color,
            focused_border_color=accent,
            label_style=ft.TextStyle(color=subtext_color),
        )
        self.prov_contacto = ft.TextField(
            label="Agente de Contacto (Vendedor)",
            width=250,
            color=text_color,
            border_color=border_color,
            focused_border_color=accent,
            label_style=ft.TextStyle(color=subtext_color),
        )
        self.prov_telefono = ft.TextField(
            label="Teléfono de Contacto *",
            width=250,
            color=text_color,
            border_color=border_color,
            focused_border_color=accent,
            label_style=ft.TextStyle(color=subtext_color),
        )
        self.prov_correo = ft.TextField(
            label="Correo Electrónico Corporativo",
            width=300,
            color=text_color,
            border_color=border_color,
            focused_border_color=accent,
            label_style=ft.TextStyle(color=subtext_color),
        )
        self.prov_desc = ft.TextField(
            label="Descripción / Categoría de Productos",
            width=565,
            color=text_color,
            border_color=border_color,
            focused_border_color=accent,
            label_style=ft.TextStyle(color=subtext_color),
        )

        self.txt_adjuntos_status = ft.Text("Sin archivos adjuntos", size=12, color=subtext_color)
        btn_adjuntar = ft.OutlinedButton(
            content="Adjuntar Catálogo / Factura (PDF / Img)",
            icon=ft.Icons.ATTACH_FILE,
            on_click=self.handle_adjuntar_simulado,
        )

        btn_guardar_proveedor = ft.Button(
            content="Guardar Proveedor",
            bgcolor=accent,
            color=ft.Colors.WHITE,
            on_click=self.handle_guardar_proveedor,
        )

        self.dt_proveedores = ft.DataTable(
            columns=[
                ft.DataColumn(label=ft.Text("ID", weight=ft.FontWeight.BOLD, color=text_color)),
                ft.DataColumn(label=ft.Text("Empresa", weight=ft.FontWeight.BOLD, color=text_color)),
                ft.DataColumn(label=ft.Text("Contacto / Vendedor", weight=ft.FontWeight.BOLD, color=text_color)),
                ft.DataColumn(label=ft.Text("Teléfono", weight=ft.FontWeight.BOLD, color=text_color)),
                ft.DataColumn(label=ft.Text("Correo", weight=ft.FontWeight.BOLD, color=text_color)),
                ft.DataColumn(label=ft.Text("Categoría / Descripción", weight=ft.FontWeight.BOLD, color=text_color)),
            ],
            rows=[],
        )
        self.cargar_tabla_proveedores(text_color)

        return ft.Column(
            controls=[
                ft.Container(
                    content=ft.Column(
                        controls=[
                            ft.Text("Registro de Nuevo Proveedor", size=18, weight=ft.FontWeight.BOLD, color=accent),
                            ft.Row([self.prov_empresa, self.prov_contacto], wrap=True, spacing=15),
                            ft.Row([self.prov_telefono, self.prov_correo], wrap=True, spacing=15),
                            self.prov_desc,
                            ft.Row([btn_adjuntar, self.txt_adjuntos_status], alignment=ft.MainAxisAlignment.START, spacing=10),
                            ft.Row([btn_guardar_proveedor], alignment=ft.MainAxisAlignment.END),
                        ],
                        spacing=12,
                    ),
                    padding=15,
                    border_radius=10,
                    bgcolor=card_bg,
                    border=ft.Border.all(1, border_color),
                ),
                ft.Container(height=10),
                ft.Text("Catálogo de Proveedores Registrados", size=18, weight=ft.FontWeight.BOLD, color=text_color),
                ft.Container(
                    content=ft.ListView(
                        controls=[self.dt_proveedores],
                        expand=True,
                    ),
                    height=280,
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
    # MANEJADORES DE EVENTOS Y ALERTAS FLOTANTES
    # ==========================================
    def show_alert_error(self, message: str):
        """Muestra una alerta flotante de error en pantalla utilizando SnackBar."""
        if self.page:
            snack = ft.SnackBar(
                content=ft.Text(message, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD),
                bgcolor=ft.Colors.RED_700,
                duration=4000,
            )
            self.page.overlay.append(snack)
            snack.open = True
            self.page.update()

    def show_alert_success(self, message: str):
        """Muestra una alerta flotante de éxito en pantalla utilizando SnackBar."""
        if self.page:
            snack = ft.SnackBar(
                content=ft.Text(message, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD),
                bgcolor=ft.Colors.GREEN_700,
                duration=3000,
            )
            self.page.overlay.append(snack)
            snack.open = True
            self.page.update()

    def handle_guardar_cliente(self, e):
        """Maneja la creación de clientes capturando excepciones RNO-CLI-01."""
        try:
            crear_cliente(
                nombre=self.cli_nombre.value,
                cedula_rif=self.cli_cedula.value,
                direccion=self.cli_direccion.value,
                telefono=self.cli_telefono.value,
                correo=self.cli_correo.value,
            )
            self.show_alert_success("¡Cliente registrado exitosamente!")
            self.limpiar_form_cliente()
            self.rebuild_ui()
        except ValueError as ex:
            self.show_alert_error(str(ex))

    def handle_guardar_proveedor(self, e):
        """Maneja la creación de proveedores capturando excepciones RNO-PROV-01 / ERR_PROV_INS_INVALID."""
        try:
            crear_proveedor(
                empresa=self.prov_empresa.value,
                contacto=self.prov_contacto.value,
                telefono=self.prov_telefono.value,
                correo=self.prov_correo.value,
                descripcion=self.prov_desc.value,
                adjuntos=self.adjuntos_temp,
            )
            self.show_alert_success("¡Proveedor registrado exitosamente!")
            self.limpiar_form_proveedor()
            self.rebuild_ui()
        except ValueError as ex:
            self.show_alert_error(str(ex))

    def handle_adjuntar_simulado(self, e):
        """Simula la carga de un archivo adjunto digital."""
        file_name = f"catalogo_prov_{len(self.adjuntos_temp) + 1}.pdf"
        self.adjuntos_temp.append(file_name)
        self.txt_adjuntos_status.value = f"Adjuntos ({len(self.adjuntos_temp)}): {', '.join(self.adjuntos_temp)}"
        self.update()

    def limpiar_form_cliente(self):
        self.cli_cedula.value = ""
        self.cli_nombre.value = ""
        self.cli_direccion.value = ""
        self.cli_telefono.value = ""
        self.cli_correo.value = ""

    def limpiar_form_proveedor(self):
        self.prov_empresa.value = ""
        self.prov_contacto.value = ""
        self.prov_telefono.value = ""
        self.prov_correo.value = ""
        self.prov_desc.value = ""
        self.adjuntos_temp = []
        self.txt_adjuntos_status.value = "Sin archivos adjuntos"

    def cargar_tabla_clientes(self, text_color):
        """Carga la lista de clientes desde la BD a la DataTable."""
        clientes = listar_clientes()
        rows = []
        for c in clientes:
            rows.append(
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(c["cedula_rif"], color=text_color)),
                        ft.DataCell(ft.Text(c["nombre"], color=text_color)),
                        ft.DataCell(ft.Text(c["telefono"] or "-", color=text_color)),
                        ft.DataCell(ft.Text(c["correo"] or "-", color=text_color)),
                        ft.DataCell(ft.Text(c["direccion"] or "-", color=text_color)),
                    ]
                )
            )
        self.dt_clientes.rows = rows

    def cargar_tabla_proveedores(self, text_color):
        """Carga la lista de proveedores desde la BD a la DataTable."""
        proveedores = listar_proveedores()
        rows = []
        for p in proveedores:
            rows.append(
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(str(p["id"]), color=text_color)),
                        ft.DataCell(ft.Text(p["empresa"] or "-", color=text_color)),
                        ft.DataCell(ft.Text(p["contacto"] or "-", color=text_color)),
                        ft.DataCell(ft.Text(p["telefono"], color=text_color)),
                        ft.DataCell(ft.Text(p["correo"] or "-", color=text_color)),
                        ft.DataCell(ft.Text(p["descripcion"] or "-", color=text_color)),
                    ]
                )
            )
        self.dt_proveedores.rows = rows
