import flet as ft
from ui.views.base_view import BaseView
from ui.components.dialogo_clave import DialogoClave
from ui.components.seleccion_lista import SeleccionLista
from ui.components.teclado_nav import (
    ControlTeclado,
    RegistroFoco,
    etiqueta_atajo,
    tooltip_con_atajo,
)
from services.cartera_service import (
    crear_cliente, obtener_cliente, buscar_cliente_por_cedula, actualizar_cliente, eliminar_cliente, listar_clientes,
    crear_proveedor, obtener_proveedor, buscar_proveedores, actualizar_proveedor, eliminar_proveedor, listar_proveedores,
    parse_documento, format_documento,
)
from services import deudas_service
# La clave que autoriza el borrado de una deuda es la de la cuenta con la
# sesión abierta. `authenticate_user` ya la compara con
# `core.security.verify_password` contra el `password_hash` almacenado: aquí no
# se vuelve a comparar ningún hash, para que exista una sola implementación de
# esa comprobación en todo el proyecto.
from services.user_service import authenticate_user


class CarteraView(BaseView):
    """Vista avanzada para la gestión de la Cartera de Clientes y Proveedores."""

    ITEMS_PER_PAGE = 10

    # Orden de columnas del boceto del PDF del 17/10/2026 (Nueva Función 2):
    # Fecha Límite | Monto a Cobrar | Cédula/Rif | Nombre Razón Social |
    # Teléfono | Etc. Los datos del cliente van AGRUPADOS de dos en dos por
    # celda, no una columna por campo: con una columna por dato la lista
    # obligaba a deslizar horizontalmente, que es justo lo que el PDF pide
    # evitar en las listas nuevas.
    COLUMNAS_DEUDAS = (
        "Fecha Límite",
        "Monto a Cobrar",
        "Cédula/RIF / Nombre o Razón Social",
        "Teléfono / Correo",
        "Dirección / Contacto Secundario",
        "Ítem Acreditado",
        "Creada / Usuario",
    )

    # Encabezado de la casilla marcadora de la izquierda. Vive aparte de
    # COLUMNAS_DEUDAS porque es ESTRUCTURAL: no es un dato del boceto del PDF,
    # es el control con el que el usuario señala el renglón sobre el que va a
    # trabajar.
    ENCABEZADO_MARCADOR = "Sel."

    # Las tres acciones que tiene un renglón de esta lista. Los nombres son los
    # del mapeo canónico de `teclado_nav.ATAJOS_ITEM`, así que la misma tecla
    # hace lo mismo aquí y en el Inventario. Las acciones del mapeo que esta
    # lista no tiene ("info", "carrito", "historial") quedan INERTES: no se les
    # inventa un equivalente, porque una tecla que significa una cosa en una
    # lista y otra en la de al lado es una trampa para quien aprende los atajos.
    ACCIONES_DEUDA = ("cobrar", "editar", "borrar")

    def __init__(self, on_back_callback=None, on_iniciar_venta=None, user_data=None):
        self.on_back_callback = on_back_callback
        # Callback (ERS 3.3): recibe el cliente seleccionado y navega
        # automáticamente a Ventas con ese cliente ya vinculado al carrito.
        self.on_iniciar_venta = on_iniciar_venta
        # Usuario de la sesión, igual que en Ventas y el Dashboard: su nombre
        # viaja a cada abono (`deuda_abonos.usuario_nombre`) para que quede
        # constancia de quién cobró. Si la vista se instancia sin él, el abono
        # se registra sin firma antes que impedir el cobro.
        self.user_data = user_data or {}
        self.adjuntos_temp = []
        self.current_tab = "clientes"

        # Estado de paginación
        self.cli_page = 1
        self.prov_page = 1
        self.deu_page = 1

        # Estado de edición
        self.cli_editing_cedula = None
        self.prov_editing_id = None

        # Pila de diálogos de la pestaña de Deudas. En Flet 0.86 los diálogos
        # se manejan con `page.show_dialog()` / `page.pop_dialog()`: el patrón
        # heredado (`page.overlay` + bandera `open`) no llega a dibujar el
        # cierre y el diálogo queda pegado —o activo pero invisible—.
        self._dialog_stack: list[ft.AlertDialog] = []

        # ── Marcador de la lista de Deudas por Cobrar ───────────────────────
        # El sombreado y el permiso para accionar los botones se derivan de
        # ESTE modelo y no de una bandera guardada en el control que recibió el
        # clic: la tabla se reconstruye en cada repintado y al desplazarse en
        # horizontal, y un flag local se perdería en el camino. La clave de
        # selección es el `id` de la deuda.
        self._seleccion_deudas = SeleccionLista(on_cambio=self._al_cambiar_seleccion_deudas)

        # Contabilidad del foco: las flechas navegan SOLO si ningún campo de
        # texto tiene el cursor. Flet no expone un "¿quién tiene el foco?"
        # global, así que cada `TextField` de la vista avisa al tomarlo y al
        # soltarlo (ver `_enlazar_foco`).
        self._registro_foco = RegistroFoco()

        # Atajos de teclado. Se instancia headless —al construir la vista
        # todavía no hay `page`— y se monta en `_asegurar_teclado()`, que es
        # idempotente y respeta el handler que ya tuviera la página: esta vista
        # comparte la página con el Dashboard y no debe quedarse el teclado.
        self._teclado = ControlTeclado(
            obtener_pagina=self.get_current_page,
            # Invocables, no controles: la pestaña visible cambia y la tabla se
            # reconstruye, así que el destino se resuelve en el momento de la
            # pulsación (ver `_destinos_scroll_pestana`).
            destino_vertical=lambda: self._destinos_scroll_pestana()[0],
            destino_horizontal=lambda: self._destinos_scroll_pestana()[1],
            seleccion=self._seleccion_deudas,
            ejecutar_accion=self.ejecutar_accion_sobre_seleccionada,
            al_limpiar=self.limpiar_seleccion_deuda,
            registro_foco=self._registro_foco,
            # Identidad logica de la vista: el Dashboard la reemplaza en cada
            # repintado, asi que el control nuevo RELEVA al de la instancia
            # anterior en vez de encadenarse a el. Sin esto la cadena de
            # handlers crece sin tope y las instancias viejas siguen actuando
            # sobre controles que ya no estan en pantalla.
            identidad="cartera",
        )

        super().__init__(route="/cartera", title="Cartera de Clientes y Proveedores")

    @property
    def usuario_nombre(self):
        """Nombre de usuario de la sesión, o `None` si la vista se construyó
        sin `user_data` (p. ej. instanciada de forma aislada en pruebas)."""
        datos = self.user_data or {}
        return datos.get("username") or datos.get("nombre") or None

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
        """Alterna la pestaña activa cambiando visibilidad sin reconstruir controles."""
        if e.control.selected:
            selected_list = list(e.control.selected)
            if selected_list:
                self.current_tab = selected_list[0]
                self._clientes_area.visible = self.current_tab == "clientes"
                self._proveedores_area.visible = self.current_tab == "proveedores"
                self._deudas_area.visible = self.current_tab == "deudas"
                # Cambiar de pestaña es el primer evento que casi siempre llega
                # con `page`: buen momento para tomar el teclado.
                self._asegurar_teclado(e)
                self.safe_update(e)

    # ─────────────────────────────────────────────────────────────────────────
    # ATAJOS DE TECLADO (flechas para navegar, F1–F6 sobre el renglón marcado)
    # ─────────────────────────────────────────────────────────────────────────
    def did_mount(self):
        """Flet avisa cuando la vista ya está montada: es el primer instante en
        que existe `self.page`, así que es el sitio natural para enganchar el
        teclado. Se envuelve porque no todas las versiones de `ft.View` lo
        definen, y porque una vista headless (pruebas) nunca lo recibe."""
        try:
            super().did_mount()
        except AttributeError:
            pass
        self._asegurar_teclado()

    def _asegurar_teclado(self, e=None) -> bool:
        """Instala los atajos si todavía no lo están. Idempotente.

        No se hace en `__init__` porque ahí no hay `page` (la vista se
        instancia y se monta después), y se llama desde varios puntos —montaje,
        cambio de pestaña, búsqueda, clic en un renglón— porque cualquiera de
        ellos puede ser el primer evento que traiga la página.
        """
        return self._teclado.instalar(e)

    def _destinos_scroll_pestana(self):
        """Controles con scroll de la pestaña ACTIVA, como `(vertical, horizontal)`.

        Se resuelven en el momento de la pulsación: la pestaña visible cambia y
        la lista se reconstruye en cada repintado, así que un control guardado
        al instalar el teclado desplazaría algo que el usuario ya no mira. Si
        una pestaña no tiene dueño de un eje se devuelve `None` para ese eje —
        una flecha que no hace nada es preferible a una que desplaza el
        contenedor equivocado.
        """
        por_pestana = {
            "clientes": ("_cli_scroll_vertical", "_cli_scroll_horizontal"),
            "proveedores": ("_prov_scroll_vertical", "_prov_scroll_horizontal"),
            "deudas": ("_deu_scroll_vertical", "_deu_scroll_horizontal"),
        }
        nombres = por_pestana.get(self.current_tab)
        if nombres is None:
            return None, None
        return getattr(self, nombres[0], None), getattr(self, nombres[1], None)

    def _enlazar_foco(self, campo, nombre):
        """Conecta un `TextField` al registro de foco y lo devuelve.

        TODOS los campos de texto de la vista pasan por aquí. Si uno se queda
        sin enlazar, al usuario se le desplaza la pantalla mientras escribe en
        él, que es exactamente lo que la regla del foco evita.
        """
        return self._registro_foco.enlazar(campo, nombre)

    # ─────────────────────────────────────────────────────────────────────────
    # MARCADOR Y SOMBREADO DE LA LISTA DE DEUDAS POR COBRAR
    # ─────────────────────────────────────────────────────────────────────────
    # Mecánica pedida por el usuario del proyecto (Nueva Función 3 del PDF,
    # extendida a esta lista):
    #   - Un clic en cualquier parte del renglón lo marca: se sombrea y la
    #     casilla de la izquierda queda marcada, y sigue marcado al desplazarse
    #     a la derecha de la lista.
    #   - Solo hay DOS formas de deseleccionar: volver a la izquierda y hacer
    #     clic DENTRO de la casilla marcada (`alternar`), o pulsar [Esc]
    #     (`limpiar`).
    #   - Con un renglón marcado, solo ese renglón puede accionar sus botones;
    #     los de los demás quedan deshabilitados VISIBLEMENTE.
    #   - SIN NADA MARCADO TODO FUNCIONA COMO ANTES: los tres botones de todos
    #     los renglones siguen activos. Es la regla más fácil de romper al
    #     cablear la vista, y la que `SeleccionLista.puede_accionar` garantiza.
    def _al_cambiar_seleccion_deudas(self):
        """Repinta la lista cuando la selección cambió de verdad.

        Lo llama el modelo (`SeleccionLista.on_cambio`), así que cualquier
        camino que altere la selección —clic, casilla, [Esc], una deuda
        borrada— termina repintando por aquí y no hay que acordarse en cada
        handler.
        """
        if not hasattr(self, "dt_deudas"):
            return  # vista aún sin construir (durante `__init__`)
        self.cargar_tabla_deudas(
            self.get_text_color(), self.get_accent_color(), self.get_subtext_color()
        )
        self.safe_update()

    def seleccionar_deuda(self, deuda_id, e=None):
        """Clic en cualquier parte del renglón: marca (nunca desmarca)."""
        self._asegurar_teclado(e)
        self._seleccion_deudas.seleccionar(deuda_id)

    def alternar_deuda(self, deuda_id, e=None):
        """Clic DENTRO de la casilla marcadora: marca o desmarca."""
        self._asegurar_teclado(e)
        self._seleccion_deudas.alternar(deuda_id)

    def limpiar_seleccion_deuda(self, e=None):
        """Quita la marca (tecla [Esc]). El repintado lo dispara el modelo."""
        self._seleccion_deudas.limpiar()
        self.safe_update(e)

    # ─────────────────────────────────────────────────────────────────────────
    # ACCIONES DE UN RENGLÓN DE DEUDAS (los tres botones y F2 / F5 / F6)
    # ─────────────────────────────────────────────────────────────────────────
    def _handlers_accion_deuda(self) -> dict:
        """Mapeo canónico → handler de esta lista. Las claves ausentes son las
        teclas inertes aquí (F1 info, F3 carrito, F4 historial)."""
        return {
            "cobrar": self.handle_abrir_cobro,
            "editar": self.handle_abrir_edicion_deuda,
            "borrar": self.handle_confirmar_borrado_deuda,
        }

    def _deuda_por_id(self, deuda_id) -> dict | None:
        """Relee la deuda del servicio por su `id`.

        La clave del marcador viaja como texto (`SeleccionLista` normaliza a
        `str` para que `1` y `"1"` no sean dos renglones), así que aquí se
        devuelve al entero que entiende SQLite. Releer —en vez de confiar en el
        `dict` de la fila— es lo que hace que una deuda ya cobrada o ya borrada
        por otra ventana no rompa la vista.
        """
        try:
            clave = int(str(deuda_id).strip())
        except (TypeError, ValueError):
            return None
        return deudas_service.obtener_deuda(clave)

    def ejecutar_accion_deuda(self, accion: str, deuda_id, e=None) -> bool:
        """Punto de entrada ÚNICO de los tres botones del renglón y de F2/F5/F6.

        Que la tecla y el ratón recorran exactamente el mismo camino es
        deliberado: con dos caminos, un día uno valida algo que el otro no.
        Devuelve `False` —sin efecto visible salvo el aviso— cuando la acción
        no aplica: tecla sin equivalente en esta lista, renglón distinto del
        marcado, deuda ya pagada o deuda que ya no existe.

        `puede_accionar` se vuelve a consultar aunque el botón llegue ya
        deshabilitado: la regla del marcador tiene que valer también para quien
        entre por teclado o por código.
        """
        handler = self._handlers_accion_deuda().get(accion)
        if handler is None:
            return False

        if not self._seleccion_deudas.puede_accionar(deuda_id):
            self.show_alert_info(
                "Hay otra deuda marcada. Haga clic en su casilla o pulse Esc para liberarla.",
                e,
            )
            return False

        actual = self._deuda_por_id(deuda_id)
        if actual is None:
            # Otra ventana la borró entre el repintado y la pulsación.
            self.show_alert_error("Esta deuda ya no existe. Actualice la lista.", e)
            self._seleccion_deudas.descartar([deuda_id])
            self.refrescar_deudas(e)
            return False

        if accion == "cobrar" and (actual.get("estado") or "") == deudas_service.ESTADO_PAGADA:
            # El servicio lo rechazaría con ERR_DEUDA_PAGADA; se avisa antes de
            # abrir un diálogo de cobro que no puede terminar en nada.
            self.show_alert_info("Esta deuda ya está pagada por completo.", e)
            return False

        handler(actual, e)
        return True

    def ejecutar_accion_sobre_seleccionada(self, accion: str, e=None) -> bool:
        """La misma acción, aplicada a la deuda MARCADA (base de F2/F5/F6).

        Sin nada marcado no hace nada: adivinar un renglón sería disparar una
        acción —incluido un borrado— sobre algo que el usuario no eligió.
        """
        deuda_id = self._seleccion_deudas.seleccionado
        if not deuda_id:
            return False
        return self.ejecutar_accion_deuda(accion, deuda_id, e)

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
                ft.Segment(
                    value="deudas",
                    label=ft.Text("Deudas por Cobrar", color=text_color, weight=ft.FontWeight.BOLD),
                    icon=ft.Icon(ft.Icons.REQUEST_QUOTE_OUTLINED, color=accent),
                ),
            ],
            on_change=self.handle_tab_change,
        )

        # Construir las tres areas al inicio; alternar con visible
        clientes_content = self.build_clientes_tab(accent, card_bg, text_color, subtext_color, border_color)
        proveedores_content = self.build_proveedores_tab(accent, card_bg, text_color, subtext_color, border_color)
        deudas_content = self.build_deudas_tab(accent, card_bg, text_color, subtext_color, border_color)

        self._clientes_area = ft.Container(content=clientes_content, expand=True, visible=self.current_tab == "clientes")
        self._proveedores_area = ft.Container(content=proveedores_content, expand=True, visible=self.current_tab == "proveedores")
        self._deudas_area = ft.Container(content=deudas_content, expand=True, visible=self.current_tab == "deudas")

        return ft.Column(
            controls=[
                ft.Row([tabs_selector], alignment=ft.MainAxisAlignment.START),
                ft.Divider(height=10, color=border_color),
                self._clientes_area,
                self._proveedores_area,
                self._deudas_area,
            ],
            spacing=15,
            expand=True,
        )

    # ==========================================
    # PESTAÑA CLIENTES
    # ==========================================
    def build_clientes_tab(self, accent, card_bg, text_color, subtext_color, border_color) -> ft.Control:
        # 1. Barra de Búsqueda con Dropdown de Tipo de Documento + Número
        self.cli_search_tipo = ft.Dropdown(
            value="V",
            width=85,
            color=text_color,
            border_color=border_color,
            focused_border_color=accent,
            border_radius=12,
            options=[
                ft.dropdown.Option("V"),
                ft.dropdown.Option("E"),
                ft.dropdown.Option("J"),
                ft.dropdown.Option("G"),
                ft.dropdown.Option("P"),
            ],
        )
        # Todos los campos de texto de la vista se enlazan al registro de foco:
        # mientras el cursor esté en uno, las flechas mueven el cursor y no la
        # pantalla.
        self.cli_search_numero = self._enlazar_foco(ft.TextField(
            label="Número de Cédula / RIF",
            hint_text="Ej: 12345678",
            width=220,
            keyboard_type=ft.KeyboardType.NUMBER,
            color=text_color,
            border_color=border_color,
            focused_border_color=accent,
            border_radius=12,
            on_submit=self.handle_buscar_cliente,
        ), "cli_busqueda")

        btn_buscar_cli = ft.Button(
            content="Buscar",
            icon=ft.Icons.SEARCH,
            style=ft.ButtonStyle(
                bgcolor=accent,
                color=ft.Colors.WHITE,
                shape=ft.RoundedRectangleBorder(radius=12)
            ),
            on_click=self.handle_buscar_cliente,
        )

        btn_nuevo_cli = ft.OutlinedButton(
            content="Nuevo Cliente",
            icon=ft.Icons.ADD,
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=12)
            ),
            on_click=self.handle_mostrar_form_cliente,
        )

        search_bar = self.create_card(
            content=ft.Row([
                ft.Row([self.cli_search_tipo, self.cli_search_numero], spacing=5),
                btn_buscar_cli,
                btn_nuevo_cli
            ], spacing=15, alignment=ft.MainAxisAlignment.START),
            padding=10,
            border_radius=16
        )

        # 2. Tarjeta de Resultado de Búsqueda
        self.cli_result_container = ft.Container(visible=False)

        # 3. Formulario con Dropdown + TextField para Cédula / RIF
        self.cli_tipo_doc = ft.Dropdown(
            value="V",
            width=85,
            color=text_color,
            border_color=border_color,
            focused_border_color=accent,
            border_radius=12,
            options=[
                ft.dropdown.Option("V"),
                ft.dropdown.Option("E"),
                ft.dropdown.Option("J"),
                ft.dropdown.Option("G"),
                ft.dropdown.Option("P"),
            ],
        )
        self.cli_num_doc = self._enlazar_foco(ft.TextField(
            label="Número de Cédula / RIF *",
            hint_text="Solo números",
            width=200,
            keyboard_type=ft.KeyboardType.NUMBER,
            color=text_color,
            border_color=border_color,
            focused_border_color=accent,
            border_radius=12,
        ), "cli_num_doc")
        self.cli_nombre = self._enlazar_foco(ft.TextField(label="Nombre / Razón Social *", width=300, color=text_color, border_color=border_color, focused_border_color=accent, border_radius=12), "cli_nombre")
        self.cli_telefono = self._enlazar_foco(ft.TextField(label="Teléfono", width=250, color=text_color, border_color=border_color, focused_border_color=accent, border_radius=12), "cli_telefono")
        self.cli_correo = self._enlazar_foco(ft.TextField(label="Correo", width=300, color=text_color, border_color=border_color, focused_border_color=accent, border_radius=12), "cli_correo")
        self.cli_direccion = self._enlazar_foco(ft.TextField(label="Dirección", width=595, multiline=True, max_lines=2, color=text_color, border_color=border_color, focused_border_color=accent, border_radius=12), "cli_direccion")

        self.btn_guardar_cli_label = ft.Text("Guardar Cliente", color=ft.Colors.WHITE)
        btn_guardar_cli = ft.Button(
            content=self.btn_guardar_cli_label,
            style=ft.ButtonStyle(
                bgcolor=accent,
                color=ft.Colors.WHITE,
                shape=ft.RoundedRectangleBorder(radius=12)
            ),
            on_click=self.handle_guardar_cliente,
        )
        btn_cancelar_cli = ft.OutlinedButton(
            content="Cancelar",
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=12)
            ),
            on_click=self.handle_ocultar_form_cliente,
        )

        self.cli_form_container = self.create_card(
            content=ft.Column(
                controls=[
                    ft.Text("Formulario de Registro / Edición de Cliente", size=16, weight=ft.FontWeight.BOLD, color=accent),
                    ft.Row([
                        ft.Row([self.cli_tipo_doc, self.cli_num_doc], spacing=5),
                        self.cli_nombre
                    ], wrap=True, spacing=15),
                    ft.Row([self.cli_telefono, self.cli_correo], wrap=True, spacing=15),
                    self.cli_direccion,
                    ft.Row([btn_cancelar_cli, btn_guardar_cli], alignment=ft.MainAxisAlignment.END, spacing=10),
                ],
                spacing=12,
            ),
            padding=15,
            border_radius=16,
        )
        self.cli_form_container.visible = False

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

        # Fila con scroll horizontal: evita columnas recortadas (p.ej.
        # Nombre/Correo) cuando la sidebar expandida reduce el ancho
        # disponible, y ft.Row nunca corta filas a la mitad como sí ocurría con
        # ft.ListView de altura no acotada. Queda con nombre porque es el
        # destino de las flechas izquierda/derecha en esta pestaña (un solo
        # dueño por eje).
        self._cli_scroll_horizontal = ft.Row(controls=[self.dt_clientes], scroll=ft.ScrollMode.AUTO)
        self._cli_scroll_vertical = ft.Column(
            controls=[
                search_bar,
                self.cli_result_container,
                self.cli_form_container,
                ft.Container(height=5),
                ft.Text("Directorio General de Clientes", size=18, weight=ft.FontWeight.BOLD, color=text_color),
                self.create_card(
                    content=ft.Column(
                        controls=[
                            self._cli_scroll_horizontal,
                            pagination_bar,
                        ],
                    ),
                    padding=10,
                    border_radius=18,
                ),
            ],
            scroll=ft.ScrollMode.AUTO,
            spacing=10,
            expand=True,
        )
        return self._cli_scroll_vertical

    # ==========================================
    # PESTAÑA PROVEEDORES
    # ==========================================
    def build_proveedores_tab(self, accent, card_bg, text_color, subtext_color, border_color) -> ft.Control:
        # 1. Barra de Búsqueda con opción de Dropdown para RIF/Cédula o Texto
        self.prov_search_tipo = ft.Dropdown(
            value="J",
            width=85,
            color=text_color,
            border_color=border_color,
            focused_border_color=accent,
            border_radius=12,
            options=[
                ft.dropdown.Option("J"),
                ft.dropdown.Option("G"),
                ft.dropdown.Option("V"),
                ft.dropdown.Option("E"),
                ft.dropdown.Option("P"),
            ],
        )
        self.prov_search_input = self._enlazar_foco(ft.TextField(
            label="Buscar por RIF / Empresa / Teléfono",
            hint_text="Ej: 12345678 o TecnoCorp",
            width=250,
            color=text_color,
            border_color=border_color,
            focused_border_color=accent,
            border_radius=12,
            on_submit=self.handle_buscar_proveedor,
        ), "prov_busqueda")

        btn_buscar_prov = ft.Button(
            content="Buscar",
            icon=ft.Icons.SEARCH,
            style=ft.ButtonStyle(
                bgcolor=accent,
                color=ft.Colors.WHITE,
                shape=ft.RoundedRectangleBorder(radius=12)
            ),
            on_click=self.handle_buscar_proveedor,
        )

        btn_nuevo_prov = ft.OutlinedButton(
            content="Nuevo Proveedor",
            icon=ft.Icons.ADD,
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=12)
            ),
            on_click=self.handle_mostrar_form_proveedor,
        )

        search_bar = self.create_card(
            content=ft.Row([
                ft.Row([self.prov_search_tipo, self.prov_search_input], spacing=5),
                btn_buscar_prov,
                btn_nuevo_prov
            ], spacing=15, alignment=ft.MainAxisAlignment.START),
            padding=10,
            border_radius=16
        )

        # 2. Tarjeta de Resultado de Búsqueda
        self.prov_result_container = ft.Container(visible=False)

        # 3. Formulario de Proveedores con RIF / Cédula (Dropdown + TextField)
        self.prov_tipo_doc = ft.Dropdown(
            value="J",
            width=85,
            color=text_color,
            border_color=border_color,
            focused_border_color=accent,
            border_radius=12,
            options=[
                ft.dropdown.Option("J"),
                ft.dropdown.Option("G"),
                ft.dropdown.Option("V"),
                ft.dropdown.Option("E"),
                ft.dropdown.Option("P"),
            ],
        )
        self.prov_num_doc = self._enlazar_foco(ft.TextField(
            label="Número RIF / Cédula *",
            hint_text="Solo números",
            width=200,
            keyboard_type=ft.KeyboardType.NUMBER,
            color=text_color,
            border_color=border_color,
            focused_border_color=accent,
            border_radius=12,
        ), "prov_num_doc")

        self.prov_empresa = self._enlazar_foco(ft.TextField(label="Nombre de la Empresa *", width=290, color=text_color, border_color=border_color, focused_border_color=accent, border_radius=12), "prov_empresa")
        self.prov_contacto = self._enlazar_foco(ft.TextField(label="Agente de Contacto", width=250, color=text_color, border_color=border_color, focused_border_color=accent, border_radius=12), "prov_contacto")
        self.prov_telefono = self._enlazar_foco(ft.TextField(label="Teléfono *", width=250, color=text_color, border_color=border_color, focused_border_color=accent, border_radius=12), "prov_telefono")
        self.prov_correo = self._enlazar_foco(ft.TextField(label="Correo", width=300, color=text_color, border_color=border_color, focused_border_color=accent, border_radius=12), "prov_correo")
        self.prov_desc = self._enlazar_foco(ft.TextField(label="Descripción / Categoría", width=595, color=text_color, border_color=border_color, focused_border_color=accent, border_radius=12), "prov_desc")

        self.txt_adjuntos_status = ft.Text("Sin archivos adjuntos", size=12, color=subtext_color)
        btn_adjuntar = ft.OutlinedButton(
            content="Adjuntar Catálogo (PDF / Img)",
            icon=ft.Icons.ATTACH_FILE,
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=12)
            ),
            on_click=self.handle_adjuntar_simulado,
        )

        self.btn_guardar_prov_label = ft.Text("Guardar Proveedor", color=ft.Colors.WHITE)
        btn_guardar_prov = ft.Button(
            content=self.btn_guardar_prov_label,
            style=ft.ButtonStyle(
                bgcolor=accent,
                color=ft.Colors.WHITE,
                shape=ft.RoundedRectangleBorder(radius=12)
            ),
            on_click=self.handle_guardar_proveedor,
        )
        btn_cancelar_prov = ft.OutlinedButton(
            content="Cancelar",
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=12)
            ),
            on_click=self.handle_ocultar_form_proveedor,
        )

        self.prov_form_container = self.create_card(
            content=ft.Column(
                controls=[
                    ft.Text("Formulario de Registro / Edición de Proveedor", size=16, weight=ft.FontWeight.BOLD, color=accent),
                    ft.Row([
                        ft.Row([self.prov_tipo_doc, self.prov_num_doc], spacing=5),
                        self.prov_empresa
                    ], wrap=True, spacing=15),
                    ft.Row([self.prov_contacto, self.prov_telefono, self.prov_correo], wrap=True, spacing=15),
                    self.prov_desc,
                    ft.Row([btn_adjuntar, self.txt_adjuntos_status], alignment=ft.MainAxisAlignment.START, spacing=10),
                    ft.Row([btn_cancelar_prov, btn_guardar_prov], alignment=ft.MainAxisAlignment.END, spacing=10),
                ],
                spacing=12,
            ),
            padding=15,
            border_radius=16,
        )
        self.prov_form_container.visible = False

        # 4. Tabla DataGrid con Paginación
        self.dt_proveedores = ft.DataTable(
            columns=[
                ft.DataColumn(label=ft.Text("ID", weight=ft.FontWeight.BOLD, color=text_color)),
                ft.DataColumn(label=ft.Text("RIF / Cédula", weight=ft.FontWeight.BOLD, color=text_color)),
                ft.DataColumn(label=ft.Text("Empresa", weight=ft.FontWeight.BOLD, color=text_color)),
                ft.DataColumn(label=ft.Text("Contacto", weight=ft.FontWeight.BOLD, color=text_color)),
                ft.DataColumn(label=ft.Text("Teléfono", weight=ft.FontWeight.BOLD, color=text_color)),
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

        # Dueños de cada eje de esta pestaña, con nombre para que las flechas
        # sepan a quién desplazar.
        self._prov_scroll_horizontal = ft.Row(
            controls=[self.dt_proveedores], scroll=ft.ScrollMode.AUTO
        )
        self._prov_scroll_vertical = ft.Column(
            controls=[
                search_bar,
                self.prov_result_container,
                self.prov_form_container,
                ft.Container(height=5),
                ft.Text("Catálogo General de Proveedores", size=18, weight=ft.FontWeight.BOLD, color=text_color),
                self.create_card(
                    content=ft.Column(
                        controls=[
                            self._prov_scroll_horizontal,
                            pagination_bar,
                        ],
                    ),
                    padding=10,
                    border_radius=18,
                ),
            ],
            scroll=ft.ScrollMode.AUTO,
            spacing=10,
            expand=True,
        )
        return self._prov_scroll_vertical

    # ==========================================
    # PESTAÑA DEUDAS POR COBRAR
    # ==========================================
    def build_deudas_tab(self, accent, card_bg, text_color, subtext_color, border_color) -> ft.Control:
        """Lista de Deudas por Cobrar (PDF del 17/10/2026, Nueva Función 2).

        Muestra la misma información del Directorio General de Clientes más el
        ítem acreditado, la fecha de creación de la deuda, la fecha límite de
        pago y el usuario que la creó. El orden de filas es el que entrega
        `listar_deudas()` —fecha límite ascendente, las más urgentes primero,
        que es el orden en que hay que salir a cobrar— y no se reordena aquí.
        """
        # 1. Barra de búsqueda y filtro. La búsqueda la resuelve el servicio
        # (cédula, nombre o ítem acreditado en una sola consulta), de modo que
        # la vista nunca filtra listas en memoria.
        self.deu_search = self._enlazar_foco(ft.TextField(
            label="Buscar por Cédula/RIF, nombre o ítem acreditado",
            hint_text="Ej: 12345678, Fulano o Filtro de aceite",
            width=340,
            color=text_color,
            border_color=border_color,
            focused_border_color=accent,
            border_radius=12,
            on_submit=self.handle_buscar_deudas,
        ), "deu_busqueda")
        btn_buscar_deu = ft.Button(
            content="Buscar",
            icon=ft.Icons.SEARCH,
            style=ft.ButtonStyle(
                bgcolor=accent,
                color=ft.Colors.WHITE,
                shape=ft.RoundedRectangleBorder(radius=12)
            ),
            on_click=self.handle_buscar_deudas,
        )
        btn_limpiar_deu = ft.OutlinedButton(
            content="Limpiar",
            icon=ft.Icons.CLEAR,
            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=12)),
            on_click=self.handle_limpiar_busqueda_deudas,
        )
        # Arranca encendido: la ventana se llama "Deudas por Cobrar", y lo ya
        # cobrado solo interesa como consulta puntual.
        self.deu_solo_abiertas = ft.Switch(
            label="Solo deudas abiertas",
            value=True,
            active_color=accent,
            on_change=self.handle_filtro_deudas,
        )

        search_bar = self.create_card(
            content=ft.Row([
                self.deu_search,
                btn_buscar_deu,
                btn_limpiar_deu,
                self.deu_solo_abiertas,
            ], spacing=15, wrap=True, alignment=ft.MainAxisAlignment.START),
            padding=10,
            border_radius=16,
        )

        # 2. Total por cobrar: la cifra que el dueño quiere ver de un golpe.
        self.txt_deu_total = ft.Text("", size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_400)
        self.txt_deu_vencidas = ft.Text("", size=13, color=ft.Colors.RED_400, weight=ft.FontWeight.W_600)
        total_card = self.create_card(
            content=ft.Row([
                ft.Row([
                    ft.Icon(ft.Icons.ACCOUNT_BALANCE_WALLET_OUTLINED, color=ft.Colors.GREEN_400, size=28),
                    ft.Column([
                        ft.Text("Total por Cobrar (saldos abiertos)", size=12, color=subtext_color),
                        self.txt_deu_total,
                    ], spacing=0, tight=True),
                ], spacing=12),
                self.txt_deu_vencidas,
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            padding=15,
            border_radius=16,
        )

        # 3. Tabla agrupada con paginación.
        self.dt_deudas = ft.DataTable(
            columns=self._columnas_deudas(accent, text_color),
            rows=[],
            data_row_min_height=72,
            data_row_max_height=110,
            # Explícito aunque sea el valor por omisión: todos los renglones
            # llevan `on_select_change` (el clic en cualquier parte del
            # renglón), y con la columna de casillas propia de la tabla
            # activada Flet dibujaría una SEGUNDA casilla junto al marcador.
            show_checkbox_column=False,
        )
        self.txt_deu_pagination = ft.Text("", color=subtext_color, size=13)
        self.cargar_tabla_deudas(text_color, accent, subtext_color)

        btn_deu_prev = ft.IconButton(icon=ft.Icons.CHEVRON_LEFT, on_click=self.deu_pagina_anterior)
        btn_deu_next = ft.IconButton(icon=ft.Icons.CHEVRON_RIGHT, on_click=self.deu_pagina_siguiente)

        pagination_bar = ft.Row(
            controls=[
                self.txt_deu_pagination,
                ft.Row([btn_deu_prev, btn_deu_next], spacing=5),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )

        # La tabla ya agrupa los datos por celda para que entre a lo ancho; el
        # `ScrollMode.AUTO` queda como red de seguridad para pantallas muy
        # angostas. Los dos controles llevan nombre porque son los destinos de
        # las flechas: la Row es la única dueña del eje HORIZONTAL y la Column
        # externa la del VERTICAL.
        self._deu_scroll_horizontal = ft.Row(controls=[self.dt_deudas], scroll=ft.ScrollMode.AUTO)
        self._deu_scroll_vertical = ft.Column(
            controls=[
                search_bar,
                total_card,
                ft.Container(height=5),
                ft.Text("Deudas por Cobrar", size=18, weight=ft.FontWeight.BOLD, color=text_color),
                self.create_card(
                    content=ft.Column(
                        controls=[
                            self._deu_scroll_horizontal,
                            pagination_bar,
                        ],
                    ),
                    padding=10,
                    border_radius=18,
                ),
            ],
            scroll=ft.ScrollMode.AUTO,
            spacing=10,
            expand=True,
        )
        return self._deu_scroll_vertical

    def _columnas_deudas(self, accent, text_color) -> list[ft.DataColumn]:
        """Encabezados en el orden exacto del boceto del PDF, con la casilla
        marcadora delante y la columna de acciones al final."""
        return [
            ft.DataColumn(
                label=ft.Text(self.ENCABEZADO_MARCADOR, weight=ft.FontWeight.BOLD, color=accent)
            )
        ] + [
            ft.DataColumn(label=ft.Text(titulo, weight=ft.FontWeight.BOLD, color=text_color))
            for titulo in self.COLUMNAS_DEUDAS
        ] + [
            ft.DataColumn(label=ft.Text("Acciones", weight=ft.FontWeight.BOLD, color=accent))
        ]

    def _celda_marcador_deuda(self, deuda: dict, accent, subtext_color) -> ft.Control:
        """La casilla de la izquierda, dibujada a partir del ESTADO DEL MODELO.

        Por eso la marca sobrevive al repintado y al desplazamiento horizontal:
        no hay ninguna bandera guardada en el control que recibió el clic.
        """
        marcada = self._seleccion_deudas.esta_seleccionado(deuda.get("id"))
        return ft.Container(
            content=ft.Icon(
                ft.Icons.RADIO_BUTTON_CHECKED if marcada else ft.Icons.RADIO_BUTTON_UNCHECKED,
                color=accent if marcada else subtext_color,
                size=20,
            ),
            width=34,
            alignment=ft.Alignment.CENTER,
            tooltip=(
                "Clic para quitar la marca de esta deuda (o pulse Esc)"
                if marcada else "Clic para marcar esta deuda"
            ),
        )

    def _celda_marcador_deuda_dc(self, deuda: dict, accent, subtext_color) -> ft.DataCell:
        """La casilla atiende su propio toque: es la única celda del renglón que
        DESMARCA (`alternar`), mientras el resto del renglón solo marca."""
        return ft.DataCell(
            self._celda_marcador_deuda(deuda, accent, subtext_color),
            on_tap=lambda ev, i=deuda.get("id"): self.alternar_deuda(i, ev),
        )

    def _boton_accion_deuda(
        self, accion: str, deuda: dict, icono, color, descripcion: str,
        subtext_color, bloqueado: bool = False, motivo_bloqueo: str = "",
    ) -> ft.Control:
        """Un botón del renglón, con su atajo A LA VISTA y cableado al punto de
        entrada único.

        Dos razones para la etiqueta en pantalla y no solo en el tooltip: el
        PDF pide que los atajos estén visibles "para siempre ser consciente de
        ellos", y un tooltip hay que ir a buscarlo con el ratón.

        `disabled` es la mitad VISIBLE de la regla del marcador: con otra deuda
        marcada el botón se ve apagado y el tooltip dice por qué, en vez de
        aceptar el clic y no hacer nada (un botón que ignora en silencio se lee
        como un cuelgue de la aplicación).
        """
        deuda_id = deuda.get("id")
        habilitado = self._seleccion_deudas.puede_accionar(deuda_id)
        activo = habilitado and not bloqueado

        if bloqueado:
            tooltip = motivo_bloqueo
        elif habilitado:
            tooltip = tooltip_con_atajo(descripcion, accion)
        else:
            tooltip = (
                f"{tooltip_con_atajo(descripcion, accion)} — hay otra deuda marcada; "
                "haga clic en su casilla o pulse Esc para liberarla"
            )

        return ft.Column([
            ft.IconButton(
                icono,
                icon_color=color,
                icon_size=20,
                tooltip=tooltip,
                disabled=not activo,
                on_click=lambda ev, a=accion, i=deuda_id: self.ejecutar_accion_deuda(a, i, ev),
            ),
            # El color del icono funciona en claro y en oscuro (son tonos medios
            # de la paleta de Material); apagado cae al gris de texto
            # secundario, que también está definido para los dos temas.
            ft.Text(
                etiqueta_atajo(accion),
                size=9,
                weight=ft.FontWeight.BOLD,
                color=color if activo else subtext_color,
                text_align=ft.TextAlign.CENTER,
            ),
        ], spacing=0, tight=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER)

    def _celda_acciones_deuda(self, deuda: dict, accent, subtext_color=None) -> ft.Control:
        """Los tres botones del renglón: Cobrar (F2), Editar (F5) y Borrar (F6).

        Una deuda ya pagada no admite otro cobro (el servicio lo rechaza con
        ERR_DEUDA_PAGADA), así que ese botón se deshabilita en vez de ofrecer
        una acción que va a fallar.

        El ancho sigue acotado y los botones van con `icon_size` reducido para
        que el renglón entre sin deslizable horizontal, que es un requisito
        explícito de esta lista.
        """
        subtext_color = subtext_color or self.get_subtext_color()
        pagada = (deuda.get("estado") or "") == deudas_service.ESTADO_PAGADA
        return ft.Container(
            content=ft.Row([
                self._boton_accion_deuda(
                    "cobrar", deuda, ft.Icons.PAYMENTS_OUTLINED, ft.Colors.GREEN_500,
                    "Cobrar (registrar abono)", subtext_color,
                    bloqueado=pagada, motivo_bloqueo="Deuda ya pagada por completo",
                ),
                self._boton_accion_deuda(
                    "editar", deuda, ft.Icons.EDIT_OUTLINED, accent,
                    "Editar fecha límite y monto total", subtext_color,
                ),
                self._boton_accion_deuda(
                    "borrar", deuda, ft.Icons.DELETE_OUTLINED, ft.Colors.RED_400,
                    "Borrar la deuda con sus renglones y abonos", subtext_color,
                ),
            ], spacing=0, tight=True),
            width=160,
            padding=ft.Padding.symmetric(vertical=6),
        )

    # ─── Pila de diálogos de la pestaña de Deudas ────────────────────────────
    @property
    def _dialog(self) -> "ft.AlertDialog | None":
        """Diálogo activo (tope de la pila) o `None` si no hay ninguno."""
        return self._dialog_stack[-1] if self._dialog_stack else None

    def _abrir_dialogo(self, dialog: ft.AlertDialog, e=None):
        """Apila un diálogo y lo muestra sobre el que hubiera debajo."""
        if dialog not in self._dialog_stack:
            self._dialog_stack.append(dialog)
        dialog.open = True

        p = self.get_current_page(e)
        if p is None:
            return
        if hasattr(p, "show_dialog"):
            try:
                p.show_dialog(dialog)
            except RuntimeError:
                pass  # ya estaba montado en la pila de la página
        else:  # respaldo para páginas que no exponen la API de diálogos
            if dialog not in p.overlay:
                p.overlay.append(dialog)
            p.update()

    def _cerrar_dialogo(self, e=None, dialog: ft.AlertDialog = None):
        """Descarta el diálogo del tope y deja activo el que estaba debajo.

        El renderizado se delega en `page.pop_dialog()`, la API de pila de
        Flet 0.86: el patrón heredado (meter el control en `page.overlay` y
        alternar `open`) no llega a dibujar el cierre, y el diálogo se queda
        pegado en pantalla o activo pero invisible, recibiendo clics sobre
        botones que el usuario ya no ve.
        """
        if dialog is None:
            dialog = self._dialog
        if dialog is None:
            return
        if dialog in self._dialog_stack:
            self._dialog_stack.remove(dialog)

        # Un campo de texto que desaparece con su diálogo NO recibe `on_blur`,
        # así que su foco quedaría registrado para siempre y las flechas no
        # volverían a navegar nunca. Al cerrar un diálogo no hay nada
        # enfocado, así que soltar todo es exacto además de seguro.
        self._registro_foco.limpiar()

        p = self.get_current_page(e)
        if p is not None and hasattr(p, "pop_dialog"):
            # `pop_dialog()` cierra el diálogo más alto que siga abierto, así
            # que se llama ANTES de bajar la bandera: bajándola primero, el
            # que Flet encuentra como tope es el de ABAJO y cierra el
            # equivocado.
            p.pop_dialog()
            dialog.open = False
            return

        dialog.open = False
        if p is None:
            return
        if dialog in getattr(p, "overlay", []):
            p.overlay.remove(dialog)
        p.update()

    # ─── Botón Cobrar: abonos parciales ──────────────────────────────────────
    def handle_abrir_cobro(self, deuda: dict, e=None):
        """Diálogo de cobro: abonos PARCIALES contra el saldo vivo.

        La deuda se vuelve a leer del servicio en lugar de confiar en el dict
        de la fila: entre que se pintó la lista y el clic pudo haberse
        registrado otro abono, y cobrar contra un saldo viejo es cobrar de
        más. El saldo y el estado no se tocan nunca desde aquí: los deriva
        `deudas_service` a partir del historial de abonos.
        """
        actual = deudas_service.obtener_deuda(deuda.get("id"))
        if actual is None:
            self.show_alert_error("Esta deuda ya no existe. Actualice la lista.", e)
            self.refrescar_deudas(e)
            return

        accent = self.get_accent_color()
        text_color = self.get_text_color()
        subtext_color = self.get_subtext_color()
        saldo = float(actual.get("saldo_usd") or 0)

        campo_monto = self._enlazar_foco(ft.TextField(
            label="Monto a Abonar (USD) *",
            # Sin pre-cargar el saldo a propósito: un campo ya lleno con el
            # total invita a confirmar de un clic y cerrar como "pagada" una
            # deuda que el cliente solo abonó en parte, y el servicio no
            # ofrece deshacer un abono. Quien cobra el total completo lo pide
            # con el botón de al lado.
            hint_text=f"Saldo pendiente: {saldo:.2f}",
            width=200,
            autofocus=True,
            keyboard_type=ft.KeyboardType.NUMBER,
            color=text_color,
            border_radius=12,
        ), "cobro_monto")
        dd_metodo = ft.Dropdown(
            label="Método de Pago",
            value="Efectivo",
            width=220,
            border_radius=12,
            options=[
                ft.dropdown.Option("Efectivo", "Efectivo ($)"),
                ft.dropdown.Option("Binance", "Binance ($)"),
                ft.dropdown.Option("Pago Móvil", "Pago Móvil (Bs)"),
                ft.dropdown.Option("Transferencia", "Transferencia (Bs)"),
                ft.dropdown.Option("Punto", "Punto de Venta (Bs)"),
            ],
        )
        campo_referencia = self._enlazar_foco(ft.TextField(
            label="Referencia del Pago (opcional)",
            hint_text="Nº de confirmación, últimos dígitos…",
            width=250,
            color=text_color,
            border_radius=12,
        ), "cobro_referencia")

        def abonar_todo(ev):
            campo_monto.value = f"{float(deudas_service.obtener_deuda(actual['id'])['saldo_usd']):.2f}"
            self.safe_update(ev)

        btn_todo = ft.OutlinedButton(
            content="Abonar todo el saldo",
            icon=ft.Icons.DONE_ALL,
            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=12)),
            on_click=abonar_todo,
        )

        historial = [
            ft.Text(
                f"{self._fecha_legible(a.get('fecha'))}  ·  "
                f"${float(a.get('monto_usd') or 0):,.2f}  ·  {a.get('metodo_pago') or '-'}"
                + (f"  ·  Ref: {a['referencia_pago']}" if a.get("referencia_pago") else "")
                + (f"  ·  {a['usuario_nombre']}" if a.get("usuario_nombre") else ""),
                size=12,
                color=text_color,
            )
            for a in actual.get("abonos", [])
        ] or [ft.Text("Sin abonos registrados todavía.", size=12, color=subtext_color)]

        def registrar(ev):
            try:
                resultado = deudas_service.registrar_abono(
                    actual["id"],
                    campo_monto.value,
                    metodo_pago=dd_metodo.value,
                    referencia_pago=campo_referencia.value,
                    # Constancia de quién cobró, que es lo que vuelve
                    # auditable la caja chica de los fiados.
                    usuario_nombre=self.usuario_nombre,
                )
            except ValueError as ex:
                # Los errores del servicio llegan con prefijo ERR_DEUDA_*. Se
                # muestran y el diálogo queda ABIERTO con lo que el usuario
                # escribió, para que corrija el monto sin rehacer el cobro.
                self.show_alert_error(str(ex), ev)
                return

            self._cerrar_dialogo(ev, dialog=dlg)
            nuevo_saldo = float(resultado.get("saldo_usd") or 0)
            if (resultado.get("estado") or "") == deudas_service.ESTADO_PAGADA:
                self.show_alert_success(
                    f"Abono registrado. La deuda de {resultado.get('cliente_nombre') or 'el cliente'} "
                    f"quedó PAGADA por completo.", ev,
                )
            else:
                self.show_alert_success(
                    f"Abono registrado. Saldo pendiente: ${nuevo_saldo:,.2f}.", ev,
                )
            self.refrescar_deudas(ev)

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.Icons.PAYMENTS_OUTLINED, color=ft.Colors.GREEN_500),
                ft.Text("Cobrar Deuda", weight=ft.FontWeight.BOLD, color=text_color),
            ], spacing=10),
            content=ft.Container(
                content=ft.Column([
                    ft.Text(
                        f"{actual.get('cliente_nombre') or '-'}  ({actual.get('cliente_id') or '-'})",
                        size=14, weight=ft.FontWeight.BOLD, color=text_color,
                    ),
                    ft.Row([
                        ft.Column([
                            ft.Text("Saldo pendiente", size=11, color=subtext_color),
                            ft.Text(f"${saldo:,.2f}", size=22, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_400),
                        ], spacing=0, tight=True),
                        ft.Column([
                            ft.Text("Fecha límite de pago", size=11, color=subtext_color),
                            ft.Text(
                                self._fecha_legible(actual.get("fecha_limite_pago"))
                                + ("  !  VENCIDA" if actual.get("vencida") else ""),
                                size=14, weight=ft.FontWeight.BOLD,
                                color=ft.Colors.RED_500 if actual.get("vencida") else text_color,
                            ),
                        ], spacing=0, tight=True),
                    ], spacing=30, alignment=ft.MainAxisAlignment.START),
                    ft.Text(
                        f"Ítem acreditado: {actual.get('items_descripcion') or '(sin detalle)'}",
                        size=12, color=subtext_color,
                    ),
                    ft.Divider(height=10),
                    ft.Row([campo_monto, btn_todo], spacing=10, wrap=True),
                    ft.Row([dd_metodo, campo_referencia], spacing=10, wrap=True),
                    ft.Divider(height=10),
                    ft.Text("Historial de abonos de esta deuda", size=13, weight=ft.FontWeight.BOLD, color=accent),
                    # El historial es el único scroll del diálogo: anidar dos
                    # dueños del eje vertical rompe el desplazamiento en 0.86.
                    ft.Column(historial, spacing=4, tight=True, height=90, scroll=ft.ScrollMode.AUTO),
                ], spacing=10, tight=True),
                width=520,
                padding=10,
            ),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda ev: self._cerrar_dialogo(ev, dialog=dlg)),
                ft.Button(
                    content="Registrar Abono",
                    icon=ft.Icons.SAVE_OUTLINED,
                    style=ft.ButtonStyle(
                        bgcolor=ft.Colors.GREEN_700,
                        color=ft.Colors.WHITE,
                        shape=ft.RoundedRectangleBorder(radius=12),
                    ),
                    on_click=registrar,
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )
        self._abrir_dialogo(dlg, e)
        return dlg

    # ─── Botón Editar: solo fecha límite y monto total ───────────────────────
    def handle_abrir_edicion_deuda(self, deuda: dict, e=None):
        """Diálogo de corrección de una deuda.

        Lo único editable es la fecha límite de pago (una prórroga) y el monto
        total (un error de tipeo al acreditar). El saldo y el estado NO se
        ofrecen: `deudas_service` los deriva del historial de abonos, y un
        campo para escribirlos a mano dejaría la lista mintiendo sobre lo que
        de verdad se cobró.
        """
        actual = deudas_service.obtener_deuda(deuda.get("id"))
        if actual is None:
            self.show_alert_error("Esta deuda ya no existe. Actualice la lista.", e)
            self.refrescar_deudas(e)
            return

        accent = self.get_accent_color()
        text_color = self.get_text_color()
        subtext_color = self.get_subtext_color()

        campo_fecha = self._enlazar_foco(ft.TextField(
            label="Fecha Límite de Pago *",
            # Se muestra y se acepta en Día/Mes/Año, que es como la escribe el
            # usuario; `normalizar_fecha` del servicio la lleva al ISO.
            value=self._fecha_legible(actual.get("fecha_limite_pago")),
            hint_text="31/12/2026",
            width=200,
            autofocus=True,
            color=text_color,
            border_radius=12,
        ), "edicion_fecha")
        campo_total = self._enlazar_foco(ft.TextField(
            label="Monto Total de la Deuda (USD) *",
            value=f"{float(actual.get('monto_total_usd') or 0):.2f}",
            width=230,
            keyboard_type=ft.KeyboardType.NUMBER,
            color=text_color,
            border_radius=12,
        ), "edicion_total")

        def guardar(ev):
            try:
                resultado = deudas_service.actualizar_deuda(
                    actual["id"],
                    fecha_limite_pago=campo_fecha.value,
                    monto_total_usd=campo_total.value,
                )
            except ValueError as ex:
                self.show_alert_error(str(ex), ev)
                return

            self._cerrar_dialogo(ev, dialog=dlg)
            self.show_alert_success(
                f"Deuda actualizada. Saldo pendiente: "
                f"${float(resultado.get('saldo_usd') or 0):,.2f}.", ev,
            )
            self.refrescar_deudas(ev)

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.Icons.EDIT_OUTLINED, color=accent),
                ft.Text("Editar Deuda", weight=ft.FontWeight.BOLD, color=text_color),
            ], spacing=10),
            content=ft.Container(
                content=ft.Column([
                    ft.Text(
                        f"{actual.get('cliente_nombre') or '-'}  ({actual.get('cliente_id') or '-'})",
                        size=14, weight=ft.FontWeight.BOLD, color=text_color,
                    ),
                    ft.Text(
                        f"Ítem acreditado: {actual.get('items_descripcion') or '(sin detalle)'}",
                        size=12, color=subtext_color,
                    ),
                    ft.Divider(height=10),
                    ft.Row([campo_fecha, campo_total], spacing=10, wrap=True),
                    ft.Text(
                        "El saldo y el estado no se editan: se recalculan a partir de los "
                        f"abonos ya registrados (${float(actual.get('total_abonado_usd') or 0):,.2f} "
                        "abonado hasta ahora).",
                        size=11, color=subtext_color,
                    ),
                ], spacing=10, tight=True),
                width=480,
                padding=10,
            ),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda ev: self._cerrar_dialogo(ev, dialog=dlg)),
                ft.Button(
                    content="Guardar Cambios",
                    icon=ft.Icons.SAVE_OUTLINED,
                    style=ft.ButtonStyle(
                        bgcolor=accent,
                        color=ft.Colors.WHITE,
                        shape=ft.RoundedRectangleBorder(radius=12),
                    ),
                    on_click=guardar,
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )
        self._abrir_dialogo(dlg, e)
        return dlg

    # ─── Botón Borrar: confirmación de la cascada y DESPUÉS la clave ─────────
    # Decisión del usuario del proyecto: borrar una deuda exige la clave de la
    # cuenta con la sesión abierta, igual que borrar un ítem del inventario. El
    # criterio es que el borrado arrastra en cascada el historial de abonos, o
    # sea destruye el registro de cuánto se cobró y quién cobró.
    #
    # El ORDEN de los dos pasos también es deliberado: primero la confirmación
    # que enuncia la cascada y recién después la clave. Primero se entiende qué
    # se va a destruir y entonces se firma; pedir la clave antes de explicar
    # qué se pierde invierte el orden natural de la decisión.
    def _paleta_dialogo(self) -> dict:
        return {
            "texto": self.get_text_color(),
            "subtexto": self.get_subtext_color(),
            "acento": self.get_accent_color(),
            "fondo": self.get_card_bg(),
            "borde": self.get_border_color(),
        }

    def _verificar_clave_sesion(self, clave: str) -> bool:
        """¿`clave` es la de la cuenta con la que está abierta la sesión?

        Delega en `authenticate_user`, que la compara con
        `core.security.verify_password` contra el `password_hash` almacenado:
        aquí no se duplica ninguna comparación de hashes. Sin usuario en sesión
        devuelve False (fail-closed): es preferible no poder borrar a borrar sin
        autorización comprobable.

        La clave tecleada NO se registra en ningún lado —ni log, ni snackbar,
        ni texto de error— y el mensaje de fallo es el genérico de
        `DialogoClave` ("Clave incorrecta"), sin distinguir casos: cada
        distinción le dice algo a quien está probando claves ajenas.
        """
        if not self.usuario_nombre or not clave:
            return False
        return authenticate_user(self.usuario_nombre, clave) is not None

    def _pedir_clave_para_borrar_deuda(self, deuda: dict, e=None):
        """Segundo paso: la firma. Apila el diálogo de clave genérico
        (`DialogoClave`), que es quien verifica y quien decide el texto del
        error."""
        comp = DialogoClave(
            titulo="Autorizar el Borrado",
            # El mensaje nombra el objeto exacto para que nadie entregue su
            # clave a ciegas.
            mensaje=(
                f"Se borrará la deuda de {deuda.get('cliente_nombre') or '-'} "
                f"({deuda.get('cliente_id') or '-'}) por "
                f"${float(deuda.get('monto_total_usd') or 0):,.2f}, con sus renglones "
                "acreditados y todo su historial de abonos."
            ),
            verificar_clave=self._verificar_clave_sesion,
            on_exito=lambda ev=None: self._borrar_deuda_autorizada(deuda, ev),
            on_cerrar=lambda ev=None: self._cerrar_dialogo(ev, dialog=comp.dialogo),
            paleta=self._paleta_dialogo(),
            etiqueta_confirmar="Borrar Deuda",
            icono=ft.Icons.DELETE_FOREVER_OUTLINED,
        )
        self._abrir_dialogo(comp.dialogo, e)
        return comp

    def _borrar_deuda_autorizada(self, deuda: dict, e=None) -> bool:
        """Borrado ya autorizado por la clave.

        El id borrado se descarta del modelo de selección: si quedara marcado,
        una selección fantasma dejaría inertes los botones de todos los
        renglones vivos.
        """
        borrada = deudas_service.eliminar_deuda(deuda.get("id"))
        self._seleccion_deudas.descartar([deuda.get("id")])
        if borrada:
            self.show_alert_success("Deuda eliminada con sus renglones y abonos.", e)
        else:
            self.show_alert_error("La deuda ya no existía.", e)
        self.refrescar_deudas(e)
        return bool(borrada)

    def handle_confirmar_borrado_deuda(self, deuda: dict, e=None):
        """Primer paso: pide confirmación ANTES de pedir la clave.

        El borrado arrastra en cascada los renglones acreditados y todo el
        historial de abonos de la deuda: destruye la constancia de los cobros
        ya hechos y no hay forma de reconstruirla. El texto nombra lo que se va
        a perder y la cifra ya abonada, y solo después se pide la firma.
        """
        actual = deudas_service.obtener_deuda(deuda.get("id"))
        if actual is None:
            self.show_alert_error("Esta deuda ya no existe. Actualice la lista.", e)
            self.refrescar_deudas(e)
            return

        text_color = self.get_text_color()
        subtext_color = self.get_subtext_color()
        abonado = float(actual.get("total_abonado_usd") or 0)
        cantidad_abonos = len(actual.get("abonos", []))

        def confirmar(ev):
            """Confirmar NO borra: cierra este diálogo y pide la clave."""
            self._cerrar_dialogo(ev, dialog=dlg)
            self._pedir_clave_para_borrar_deuda(actual, ev)

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, color=ft.Colors.RED_500),
                ft.Text("¿Borrar esta deuda?", weight=ft.FontWeight.BOLD, color=text_color),
            ], spacing=10),
            content=ft.Container(
                content=ft.Column([
                    ft.Text(
                        f"{actual.get('cliente_nombre') or '-'}  ({actual.get('cliente_id') or '-'})",
                        size=14, weight=ft.FontWeight.BOLD, color=text_color,
                    ),
                    ft.Text(
                        f"Monto total ${float(actual.get('monto_total_usd') or 0):,.2f}  ·  "
                        f"Saldo ${float(actual.get('saldo_usd') or 0):,.2f}  ·  "
                        f"Fecha límite {self._fecha_legible(actual.get('fecha_limite_pago'))}",
                        size=12, color=subtext_color,
                    ),
                    ft.Divider(height=10),
                    ft.Text(
                        "Esta acción borra también, en cascada, los renglones acreditados "
                        f"({actual.get('cantidad_items') or 0}) y el historial de abonos "
                        f"({cantidad_abonos} abono(s) por ${abonado:,.2f}) de esta deuda. "
                        "No se puede deshacer.",
                        size=13, weight=ft.FontWeight.W_600, color=ft.Colors.RED_400,
                    ),
                    ft.Text(
                        "Al confirmar se le pedirá la clave de su usuario para autorizar "
                        "el borrado.",
                        size=12, color=subtext_color,
                    ),
                ], spacing=8, tight=True),
                width=480,
                padding=10,
            ),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda ev: self._cerrar_dialogo(ev, dialog=dlg)),
                ft.Button(
                    content="Sí, Borrar Deuda",
                    icon=ft.Icons.DELETE_FOREVER_OUTLINED,
                    style=ft.ButtonStyle(
                        bgcolor=ft.Colors.RED_700,
                        color=ft.Colors.WHITE,
                        shape=ft.RoundedRectangleBorder(radius=12),
                    ),
                    on_click=confirmar,
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )
        self._abrir_dialogo(dlg, e)
        return dlg

    @staticmethod
    def _fecha_legible(iso: str) -> str:
        """Convierte el ISO que ordena en SQLite al Día/Mes/Año que lee el
        usuario venezolano."""
        crudo = (iso or "").strip()[:10]
        partes = crudo.split("-")
        if len(partes) == 3 and len(partes[0]) == 4:
            return f"{partes[2]}/{partes[1]}/{partes[0]}"
        return crudo or "-"

    def _celda_fecha_limite(self, deuda: dict, text_color, subtext_color) -> ft.Control:
        """Fecha límite con el signo de exclamación (!) de la nota del PDF.

        La marca de vencimiento se toma del campo `vencida` que ya calcula
        `deudas_service`: la vista no vuelve a comparar fechas, para que no
        existan dos reglas de vencimiento que puedan discrepar.
        """
        vencida = bool(deuda.get("vencida"))
        pagada = (deuda.get("estado") or "") == deudas_service.ESTADO_PAGADA

        encabezado = []
        if vencida:
            encabezado = [
                ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, color=ft.Colors.RED_500, size=20),
                ft.Text("!", size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.RED_500),
            ]
        encabezado.append(
            ft.Text(
                self._fecha_legible(deuda.get("fecha_limite_pago")),
                size=13,
                weight=ft.FontWeight.BOLD,
                color=ft.Colors.RED_500 if vencida else text_color,
            )
        )

        if vencida:
            leyenda, color_leyenda = "VENCIDA", ft.Colors.RED_400
        elif pagada:
            leyenda, color_leyenda = "Pagada", ft.Colors.GREEN_400
        else:
            leyenda, color_leyenda = "Al día", subtext_color

        return ft.Container(
            content=ft.Column([
                ft.Row(encabezado, spacing=4),
                ft.Text(leyenda, size=11, weight=ft.FontWeight.W_600, color=color_leyenda),
            ], spacing=2, tight=True),
            width=150,
            padding=ft.Padding.symmetric(vertical=6),
        )

    def cargar_tabla_deudas(self, text_color, accent, subtext_color=None):
        """Recarga las filas de la lista de Deudas por Cobrar.

        "Monto a Cobrar" es el **saldo vivo** (`saldo_usd`), no el monto
        original: lo que hay que cobrarle hoy al cliente es lo que queda
        después de los abonos.
        """
        subtext_color = subtext_color or self.get_subtext_color()
        todas = deudas_service.listar_deudas(
            solo_abiertas=bool(getattr(self.deu_solo_abiertas, "value", True)),
            busqueda=(getattr(self.deu_search, "value", "") or ""),
        )

        total_items = len(todas)
        total_paginas = max(1, (total_items + self.ITEMS_PER_PAGE - 1) // self.ITEMS_PER_PAGE)
        if self.deu_page > total_paginas:
            self.deu_page = total_paginas
        if self.deu_page < 1:
            self.deu_page = 1

        start_idx = (self.deu_page - 1) * self.ITEMS_PER_PAGE
        pagina_items = todas[start_idx:start_idx + self.ITEMS_PER_PAGE]

        rows = []
        for d in pagina_items:
            celda_monto = ft.Container(
                content=ft.Column([
                    ft.Text(
                        f"${float(d.get('saldo_usd') or 0):,.2f}",
                        size=15, weight=ft.FontWeight.BOLD,
                        color=ft.Colors.RED_400 if d.get("vencida") else ft.Colors.GREEN_400,
                    ),
                    ft.Text(
                        f"de ${float(d.get('monto_total_usd') or 0):,.2f} | abonado "
                        f"${float(d.get('total_abonado_usd') or 0):,.2f}",
                        size=11, color=subtext_color,
                    ),
                ], spacing=2, tight=True),
                width=165,
                padding=ft.Padding.symmetric(vertical=6),
            )

            celda_cliente = ft.Container(
                content=ft.Column([
                    ft.Container(
                        content=ft.Text(d.get("cliente_id") or "-", size=11, weight=ft.FontWeight.W_600, color=accent),
                        bgcolor=ft.Colors.with_opacity(0.12, accent),
                        padding=ft.Padding.symmetric(horizontal=6, vertical=2),
                        border_radius=6,
                    ),
                    ft.Text(
                        d.get("cliente_nombre") or "-",
                        size=13, weight=ft.FontWeight.BOLD, color=text_color,
                        max_lines=2, overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                ], spacing=4, tight=True),
                width=230,
                padding=ft.Padding.symmetric(vertical=6),
            )

            celda_contacto = ft.Container(
                content=ft.Column([
                    ft.Text(d.get("cliente_telefono") or "-", size=12, weight=ft.FontWeight.W_600, color=text_color),
                    ft.Text(
                        d.get("cliente_correo") or "-",
                        size=11, color=subtext_color,
                        max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                ], spacing=2, tight=True),
                width=170,
                padding=ft.Padding.symmetric(vertical=6),
            )

            celda_ubicacion = ft.Container(
                content=ft.Column([
                    ft.Text(
                        d.get("cliente_direccion") or "-",
                        size=12, color=text_color,
                        max_lines=2, overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                    ft.Text(
                        d.get("cliente_contacto_secundario") or "-",
                        size=11, color=subtext_color,
                        max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                ], spacing=2, tight=True),
                # 166 y no 200: la casilla marcadora añadió ancho al renglón y
                # el requisito de esta lista es que entre sin deslizable
                # horizontal. Esta celda es la que mejor lo tolera porque sus
                # dos líneas ya venían recortadas con elipsis.
                width=166,
                padding=ft.Padding.symmetric(vertical=6),
            )

            celda_item = ft.Container(
                content=ft.Column([
                    ft.Text(
                        d.get("items_descripcion") or "(sin detalle)",
                        size=12, weight=ft.FontWeight.W_600, color=text_color,
                        max_lines=2, overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                    ft.Text(f"{d.get('cantidad_items') or 0} renglón(es)", size=11, color=subtext_color),
                ], spacing=2, tight=True),
                width=200,
                padding=ft.Padding.symmetric(vertical=6),
            )

            celda_origen = ft.Container(
                content=ft.Column([
                    ft.Text(self._fecha_legible(d.get("fecha_creacion")), size=12, color=text_color),
                    ft.Text(d.get("usuario_nombre") or "-", size=11, weight=ft.FontWeight.W_600, color=subtext_color),
                ], spacing=2, tight=True),
                width=140,
                padding=ft.Padding.symmetric(vertical=6),
            )

            marcada = self._seleccion_deudas.esta_seleccionado(d.get("id"))
            rows.append(
                ft.DataRow(
                    cells=[
                        self._celda_marcador_deuda_dc(d, accent, subtext_color),
                        ft.DataCell(self._celda_fecha_limite(d, text_color, subtext_color)),
                        ft.DataCell(celda_monto),
                        ft.DataCell(celda_cliente),
                        ft.DataCell(celda_contacto),
                        ft.DataCell(celda_ubicacion),
                        ft.DataCell(celda_item),
                        ft.DataCell(celda_origen),
                        ft.DataCell(self._celda_acciones_deuda(d, accent, subtext_color)),
                    ],
                    selected=marcada,
                    # Sombreado derivado del modelo: sobrevive a los repintados
                    # y al desplazamiento horizontal de la lista.
                    color=ft.Colors.with_opacity(0.22, accent) if marcada else None,
                    # Hace sensible al clic el renglón COMPLETO ("no importa si
                    # es fuera de la casilla"); la celda del marcador tiene su
                    # propio `on_tap` y por eso no cae aquí.
                    on_select_change=lambda ev, i=d.get("id"): self.seleccionar_deuda(i, ev),
                    data=d.get("id"),
                )
            )

        self.dt_deudas.rows = rows
        self.txt_deu_pagination.value = (
            f"Página {self.deu_page} de {total_paginas} (Total: {total_items} deudas)"
        )
        self.txt_deu_total.value = f"${deudas_service.total_por_cobrar():,.2f}"
        vencidas = sum(1 for d in todas if d.get("vencida"))
        self.txt_deu_vencidas.value = (
            f"! {vencidas} deuda(s) pasada(s) de su fecha límite" if vencidas else ""
        )

    def handle_buscar_deudas(self, e):
        """Cualquier búsqueda nueva vuelve a la página 1: el usuario espera ver
        el primer resultado, no la página en la que quedó."""
        self.deu_page = 1
        self.refrescar_deudas(e)

    def handle_limpiar_busqueda_deudas(self, e):
        self.deu_search.value = ""
        self.deu_page = 1
        self.refrescar_deudas(e)

    def handle_filtro_deudas(self, e):
        self.deu_page = 1
        self.refrescar_deudas(e)

    def refrescar_deudas(self, e=None):
        """Recarga solo la lista de deudas, sin reconstruir ningún control."""
        # Casi todo lo que pasa en esta pestaña termina aquí, así que es el
        # punto más barato para asegurar que el teclado ya esté enganchado.
        self._asegurar_teclado(e)
        self.cargar_tabla_deudas(self.get_text_color(), self.get_accent_color(), self.get_subtext_color())
        self.safe_update(e)

    def deu_pagina_anterior(self, e):
        if self.deu_page > 1:
            self.deu_page -= 1
            self.refrescar_deudas(e)

    def deu_pagina_siguiente(self, e):
        total = len(deudas_service.listar_deudas(
            solo_abiertas=bool(self.deu_solo_abiertas.value),
            busqueda=(self.deu_search.value or ""),
        ))
        total_paginas = max(1, (total + self.ITEMS_PER_PAGE - 1) // self.ITEMS_PER_PAGE)
        if self.deu_page < total_paginas:
            self.deu_page += 1
            self.refrescar_deudas(e)

    # ==========================================
    # MANEJO DE EVENTOS BÚSQUEDA Y ACCIONES CLIENTES
    # ==========================================
    def handle_buscar_cliente(self, e):
        numero_raw = (self.cli_search_numero.value or "").strip()
        if not numero_raw:
            numero_raw = (self.cli_num_doc.value or "").strip()

        num_digits = "".join(filter(str.isdigit, numero_raw))

        if not num_digits:
            self.show_alert_info("Ingrese el número de Cédula o RIF para realizar la búsqueda.", e)
            return

        self.cli_search_numero.value = num_digits
        cedula_completa = format_documento(self.cli_search_tipo.value, num_digits)
        
        cliente = buscar_cliente_por_cedula(cedula_completa)
        if not cliente:
            cliente = buscar_cliente_por_cedula(num_digits)

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
                                        ft.Button("🛒 Iniciar Venta", icon=ft.Icons.SHOPPING_CART_CHECKOUT, bgcolor=ft.Colors.GREEN_700, color=ft.Colors.WHITE, on_click=lambda ev, c=cliente: self.handle_iniciar_venta_con_cliente(c, ev)),
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
            self.show_alert_info(f"El cliente '{cedula_completa}' no existe. Se ha pre-cargado la Cédula/RIF automáticamente.", e)
            self.limpiar_form_cliente()
            tipo, num = parse_documento(cedula_completa, default_tipo=self.cli_search_tipo.value)
            self.cli_tipo_doc.value = tipo
            self.cli_num_doc.value = num
            self.cli_tipo_doc.disabled = True
            self.cli_num_doc.disabled = True
            self.cli_editing_cedula = None
            self.btn_guardar_cli_label.value = "Guardar Cliente"
            self.cli_form_container.visible = True
            self.safe_update(e)

    def handle_iniciar_venta_con_cliente(self, cliente: dict, e=None):
        """ERS 3.3 — Flujo Directo Cartera→Ventas: instancia una nota de venta
        nueva, vincula este cliente y navega automáticamente a Ventas."""
        if self.on_iniciar_venta:
            self.on_iniciar_venta(cliente, e)
        else:
            self.show_alert_error(
                "Esta acción requiere el Dashboard (navegación a Ventas no disponible en este contexto).",
                e,
            )

    def preparar_edicion_cliente(self, cliente: dict, e=None):
        self.cli_result_container.visible = False
        self.cli_editing_cedula = cliente["cedula_rif"]
        tipo, num = parse_documento(cliente["cedula_rif"])
        self.cli_tipo_doc.value = tipo
        self.cli_num_doc.value = num
        self.cli_tipo_doc.disabled = True
        self.cli_num_doc.disabled = True
        self.cli_nombre.value = cliente["nombre"]
        self.cli_direccion.value = cliente["direccion"] or ""
        self.cli_telefono.value = cliente["telefono"] or ""
        self.cli_correo.value = cliente["correo"] or ""
        self.btn_guardar_cli_label.value = "Actualizar Cliente"
        self.cli_form_container.visible = True
        self.safe_update(e)

    def handle_guardar_cliente(self, e):
        try:
            num_limpio = "".join(filter(str.isdigit, (self.cli_num_doc.value or "").strip()))
            if not num_limpio:
                self.show_alert_error("Debe ingresar un número de Cédula o RIF válido.", e)
                return

            cedula_completa = format_documento(self.cli_tipo_doc.value, num_limpio)

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
                    cedula_rif=cedula_completa,
                    direccion=self.cli_direccion.value,
                    telefono=self.cli_telefono.value,
                    correo=self.cli_correo.value,
                )
                self.show_alert_success("¡Cliente registrado exitosamente!", e)

            self.limpiar_form_cliente()
            self.cli_form_container.visible = False
            self.cli_result_container.visible = False
            self.refrescar_datos(e)
        except ValueError as ex:
            self.show_alert_error(str(ex), e)

    def handle_eliminar_cliente(self, cedula_rif: str, e=None):
        try:
            eliminar_cliente(cedula_rif)
            self.show_alert_success(f"Cliente '{cedula_rif}' eliminado correctamente.", e)
            self.cli_result_container.visible = False
            self.refrescar_datos(e)
        except ValueError as ex:
            self.show_alert_error(str(ex), e)

    def handle_mostrar_form_cliente(self, e):
        self.cli_result_container.visible = False
        self.limpiar_form_cliente()
        self.cli_editing_cedula = None
        self.cli_tipo_doc.disabled = False
        self.cli_num_doc.disabled = False
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
        input_val = (self.prov_search_input.value or "").strip()
        if not input_val:
            input_val = (self.prov_num_doc.value or "").strip() or (self.prov_empresa.value or "").strip()

        if not input_val:
            self.show_alert_info("Ingrese el RIF, nombre de la empresa o teléfono para buscar.", e)
            return

        criterio = input_val
        if input_val.isdigit():
            criterio = format_documento(self.prov_search_tipo.value, input_val)

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
                            ft.Text(f"ID: {prov['id']} | RIF: {prov.get('rif') or '-'} | Teléfono: {prov['telefono']} | Correo: {prov['correo'] or '-'}", color=text_color),
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
            self.show_alert_info(f"El proveedor '{criterio}' no existe. Se ha pre-cargado la información automáticamente.", e)
            self.limpiar_form_proveedor()
            if input_val.isdigit():
                self.prov_num_doc.value = input_val
                self.prov_tipo_doc.value = self.prov_search_tipo.value
                self.prov_tipo_doc.disabled = True
                self.prov_num_doc.disabled = True
            else:
                self.prov_empresa.value = input_val
                self.prov_tipo_doc.disabled = False
                self.prov_num_doc.disabled = False
            self.prov_editing_id = None
            self.btn_guardar_prov_label.value = "Guardar Proveedor"
            self.prov_form_container.visible = True
            self.safe_update(e)

    def preparar_edicion_proveedor(self, prov: dict, e=None):
        self.prov_result_container.visible = False
        self.prov_editing_id = prov["id"]
        
        # Extraer RIF/Cédula desde el campo rif o descripcion como fallback
        rif_val = prov.get("rif") or ""
        if rif_val:
            tipo, num = parse_documento(rif_val, default_tipo="J")
            self.prov_tipo_doc.value = tipo
            self.prov_num_doc.value = num
        else:
            desc = prov["descripcion"] or ""
            tipo, num = parse_documento(desc, default_tipo="J")
            self.prov_tipo_doc.value = tipo
            self.prov_num_doc.value = num
        
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
            num_limpio = "".join(filter(str.isdigit, (self.prov_num_doc.value or "").strip()))
            if not num_limpio:
                raise ValueError("El campo Cédula / RIF es obligatorio.")
            empresa_val = (self.prov_empresa.value or "").strip()
            if not empresa_val:
                raise ValueError("El Nombre / Razón Social de la Empresa es obligatorio.")

            rif_formateado = format_documento(self.prov_tipo_doc.value, num_limpio)
            desc_final = self.prov_desc.value or ""

            if self.prov_editing_id:
                actualizar_proveedor(
                    proveedor_id=self.prov_editing_id,
                    empresa=empresa_val,
                    contacto=self.prov_contacto.value,
                    telefono=self.prov_telefono.value,
                    correo=self.prov_correo.value,
                    rif=rif_formateado,
                    descripcion=desc_final,
                    adjuntos=self.adjuntos_temp,
                )
                self.show_alert_success("¡Proveedor actualizado exitosamente!", e)
            else:
                crear_proveedor(
                    empresa=empresa_val,
                    contacto=self.prov_contacto.value,
                    telefono=self.prov_telefono.value,
                    correo=self.prov_correo.value,
                    rif=rif_formateado,
                    descripcion=desc_final,
                    adjuntos=self.adjuntos_temp,
                )
                self.show_alert_success("¡Proveedor registrado exitosamente!", e)

            self.limpiar_form_proveedor()
            self.prov_form_container.visible = False
            self.prov_result_container.visible = False
            self.refrescar_datos(e)
        except ValueError as ex:
            self.show_alert_error(str(ex), e)

    def handle_eliminar_proveedor(self, proveedor_id: int, e=None):
        try:
            eliminar_proveedor(proveedor_id)
            self.show_alert_success("¡Proveedor eliminado exitosamente!", e)
            self.prov_result_container.visible = False
            self.refrescar_datos(e)
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
    def refrescar_datos(self, e=None):
        """Recarga las filas de ambos DataTable sin reconstruir ningún control."""
        accent = self.get_accent_color()
        text_color = self.get_text_color()
        try:
            self.cargar_tabla_clientes(text_color, accent)
        except AttributeError:
            pass
        try:
            self.cargar_tabla_proveedores(text_color, accent)
        except AttributeError:
            pass
        try:
            self.cargar_tabla_deudas(text_color, accent, self.get_subtext_color())
        except AttributeError:
            pass
        self.safe_update(e)

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
                                ft.IconButton(ft.Icons.SHOPPING_CART_CHECKOUT, icon_color=ft.Colors.GREEN_600, tooltip="Iniciar Venta con este Cliente", on_click=lambda ev, item=c: self.handle_iniciar_venta_con_cliente(item, ev)),
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
            self.refrescar_datos(e)

    def cli_pagina_siguiente(self, e):
        todos = listar_clientes()
        total_paginas = max(1, (len(todos) + self.ITEMS_PER_PAGE - 1) // self.ITEMS_PER_PAGE)
        if self.cli_page < total_paginas:
            self.cli_page += 1
            self.refrescar_datos(e)

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
            rif_display = p.get("rif")
            if not rif_display and p.get("descripcion"):
                tipo, num = parse_documento(p["descripcion"], default_tipo="J")
                rif_display = format_documento(tipo, num) if num else "-"
            elif not rif_display:
                rif_display = "-"

            rows.append(
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(str(p["id"]), color=text_color)),
                        ft.DataCell(ft.Text(rif_display, color=text_color)),
                        ft.DataCell(ft.Text(p["empresa"] or "-", color=text_color)),
                        ft.DataCell(ft.Text(p["contacto"] or "-", color=text_color)),
                        ft.DataCell(ft.Text(p["telefono"], color=text_color)),
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
            self.refrescar_datos(e)

    def prov_pagina_siguiente(self, e):
        todos = listar_proveedores()
        total_paginas = max(1, (len(todos) + self.ITEMS_PER_PAGE - 1) // self.ITEMS_PER_PAGE)
        if self.prov_page < total_paginas:
            self.prov_page += 1
            self.refrescar_datos(e)

    # ==========================================
    # ALERTAS HEREDADAS DE BASEVIEW
    # ==========================================

    def handle_adjuntar_simulado(self, e):
        """Simula la carga de un archivo adjunto digital."""
        file_name = f"catalogo_prov_{len(self.adjuntos_temp) + 1}.pdf"
        self.adjuntos_temp.append(file_name)
        self.txt_adjuntos_status.value = f"Adjuntos ({len(self.adjuntos_temp)}): {', '.join(self.adjuntos_temp)}"
        self.safe_update(e)

    def limpiar_form_cliente(self):
        self.cli_tipo_doc.value = "V"
        self.cli_tipo_doc.disabled = False
        self.cli_num_doc.value = ""
        self.cli_num_doc.disabled = False
        self.cli_nombre.value = ""
        self.cli_direccion.value = ""
        self.cli_telefono.value = ""
        self.cli_correo.value = ""
        self.cli_editing_cedula = None

    def limpiar_form_proveedor(self):
        self.prov_tipo_doc.value = "J"
        self.prov_tipo_doc.disabled = False
        self.prov_num_doc.value = ""
        self.prov_num_doc.disabled = False
        self.prov_empresa.value = ""
        self.prov_contacto.value = ""
        self.prov_telefono.value = ""
        self.prov_correo.value = ""
        self.prov_desc.value = ""
        self.prov_editing_id = None
        self.adjuntos_temp = []
        self.txt_adjuntos_status.value = "Sin archivos adjuntos"
