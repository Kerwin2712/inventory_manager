import flet as ft
from ui.views.base_view import BaseView
from ui.components.multi_select_filter import MultiSelectFilter, RangeFilter
from ui.components.scroll_nav import build_inline_h_nav, build_floating_v_nav
from ui.components.selector_departamentos import SelectorDepartamentos
from ui.components.producto_detalle_modal import construir_modal_detalle_producto
from ui.components.seleccion_lista import SeleccionLista
from ui.components.dialogo_clave import DialogoClave
from services.bcv_service import actualizar_tasa, obtener_estado_tasa
# La clave que autoriza un borrado es la de la cuenta con la sesión abierta:
# `authenticate_user` ya la compara con `core.security.verify_password` contra
# el `password_hash` almacenado, así que se reutiliza en vez de escribir aquí
# una segunda copia de la verificación (dos copias = dos criterios que se
# pueden desincronizar).
from services.user_service import authenticate_user
from services.inventario_service import (
    crear_producto, obtener_producto, actualizar_producto,
    listar_productos, eliminar_producto,
    obtener_opciones_filtro, obtener_opciones_proveedor_filtro,
)
from services.cartera_service import listar_proveedores
from services.reportes_service import obtener_historial_producto
from services.departamentos_service import (
    listar_departamentos, listar_sub_departamentos,
    crear_departamento, crear_sub_departamento,
)
from services.preferencias_service import (
    obtener_vista_inventario, guardar_vista_inventario,
)


class InventarioView(BaseView):
    """Vista avanzada del Módulo de Inventario con motor BCV, filtros en cascada
    y flujo de registro en 3 pasos (ERS 3.1 / 3.2)."""

    ITEMS_PER_PAGE = 15

    # Alto reservado al pie de la tabla para que el cluster flotante de
    # navegación vertical no se dibuje encima de la última fila.
    _HOLGURA_NAV_FLOTANTE = 44

    # ── Resumen del paso 3 (previsualización antes de guardar) ───────────────
    # "Descripción General" es la ÚNICA casilla del resumen con espacio
    # reservado: admite textos largos (unos 300 caracteres como mínimo) y debe
    # envolverse dentro del ancho del diálogo. Con 640 px de ancho de ventana y
    # tamaño 12, entran ~65 caracteres por línea, así que seis líneas cubren los
    # 300 caracteres con margen; el alto es ese mismo cálculo en píxeles.
    _LINEAS_DESCRIPCION_RESUMEN = 6
    _ALTO_DESCRIPCION_RESUMEN = 104

    def __init__(self, on_back_callback=None, on_procesar_venta=None, es_admin: bool = False,
                 username: str | None = None, rol_usuario: str | None = None):
        self.on_back_callback = on_back_callback
        # Callback (ERS 3.3 — Flujo Directo Inventario→Ventas): recibe el
        # producto seleccionado y navega automáticamente a Ventas cargándolo.
        self.on_procesar_venta = on_procesar_venta
        # ERS 3.6: el historial clínico de producto es exclusivo admin/gerencia.
        self.es_admin = es_admin
        # `username` namespacea las preferencias de interfaz (modo de vista) y
        # `rol_usuario` es el rol nombrado que exigen los servicios para los
        # campos de costo. Ambos llegan desde `DashboardView`.
        self.username = username
        self._rol_usuario = rol_usuario
        self._page_num = 1

        # ── Estado del formulario de ingreso ────────────────────────────────
        self._form_codigo_verificado = False
        self._editing_codigo: str | None = None

        # ── Pila de diálogos abiertos (el tope es el activo) ─────────────────
        # Es una PILA y no una única referencia porque un diálogo puede abrir
        # otro encima (p. ej. el aviso de código duplicado sobre el paso 1): al
        # cerrar el de arriba hay que volver a apuntar al de abajo, no perderlo
        # (con una sola referencia, "Cancelar" del paso 1 cerraba el aviso ya
        # cerrado y dejaba al usuario atrapado en el paso 1).
        self._dialog_stack: list[ft.AlertDialog] = []

        # ── Marcador de selección de la lista (Nueva Función 3) ─────────────
        # El modelo vive en `ui.components.seleccion_lista` y no aquí porque
        # Ventas y Deudas por Cobrar van a reutilizar la misma mecánica. La
        # vista solo traduce clics y teclas a sus operaciones y repinta.
        self._seleccion = SeleccionLista(on_cambio=self._al_cambiar_seleccion)
        # Handler de teclado que había antes de que esta vista capturara [Esc]
        # (se conserva para seguir invocándolo; ver `_asegurar_captura_escape`).
        self._keyboard_previo = None
        # Índice de los productos de la página en pantalla, por código: permite
        # que las acciones por nombre (y los atajos de teclado que vendrán)
        # trabajen con un código, sin depender del `dict` capturado en un clic.
        self._productos_en_pantalla: dict[str, dict] = {}

        # ── Visibilidad de columnas de la tabla (mostrar/ocultar) ───────────
        # "acciones" es estructural (íconos de edición/venta) y no se puede ocultar.
        self._columnas_ocultables = [
            "codigo", "referencia", "descripcion", "departamento", "marca",
            "precio_efectivo", "precio_bcv", "monto_bs", "existencia",
        ]
        self._columnas_labels = {
            # "marcador" es la casilla izquierda de selección: estructural como
            # "acciones", por eso no figura entre las ocultables.
            "marcador": "Sel.",
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
        # Última vista elegida por este usuario ("separado", "agrupado" o
        # "tarjetas"); cae al modo por defecto si no hay preferencia guardada.
        self._modo_vista = obtener_vista_inventario(self.username)

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

    @property
    def _dialog(self) -> "ft.AlertDialog | None":
        """Diálogo activo (tope de la pila) o `None` si no hay ninguno."""
        return self._dialog_stack[-1] if self._dialog_stack else None

    def _close_dialog(self, e=None, dialog: ft.AlertDialog = None):
        """Descarta el diálogo del tope y deja activo el que estaba debajo.

        El renderizado se delega en `page.pop_dialog()`, la API de pila de
        diálogos de Flet 0.86. El patrón heredado (meter el control en
        `page.overlay` y alternar `open`) no llega a dibujar el cierre: el
        diálogo se quedaba pegado en pantalla —el aviso de código duplicado
        no se podía descartar— o seguía activo pero invisible, recibiendo
        clics sobre botones que el usuario ya no veía.
        """
        if dialog is None:
            dialog = self._dialog
        if dialog is None:
            return
        if dialog in self._dialog_stack:
            self._dialog_stack.remove(dialog)

        p = self._get_page(e)
        if p is not None and hasattr(p, "pop_dialog"):
            # `pop_dialog()` cierra el diálogo más alto que siga abierto, así
            # que se llama ANTES de bajar la bandera: si se baja primero, el
            # que Flet encuentra como tope es el de ABAJO y se cierra el
            # equivocado (el aviso quedaba visible y el paso 1 desaparecía).
            p.pop_dialog()
            dialog.open = False
            return

        dialog.open = False
        if p is None:
            return
        # Respaldo para páginas que no exponen la API de diálogos.
        if dialog in getattr(p, "overlay", []):
            p.overlay.remove(dialog)
        p.update()

    def _cerrar_todos_los_dialogos(self, e=None):
        """Vacía la pila cerrando de arriba hacia abajo (cancelación total)."""
        while self._dialog_stack:
            self._close_dialog(e, dialog=self._dialog_stack[-1])

    def _open_dialog(self, dialog: ft.AlertDialog, e=None):
        """Apila un diálogo y lo muestra sobre el que hubiera debajo."""
        if dialog not in self._dialog_stack:
            self._dialog_stack.append(dialog)
        dialog.open = True

        p = self._get_page(e)
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

        # ── Dueño único del scroll VERTICAL de la página ─────────────────────
        # Antes coexistían dos scrolls verticales anidados (este Column con
        # AUTO y el contenedor de la tabla con ALWAYS + altura fija): sobre la
        # tabla, la rueda no propagaba al padre y el desplazamiento se
        # bloqueaba. Ahora el eje vertical es de este Column y el eje
        # HORIZONTAL es exclusivo de `_tabla_scroll_row` (tabla ancha).
        # Se crea antes de construir los paneles porque el panel de tabla lo
        # necesita como destino de los botones flotantes de scroll vertical.
        self._body_scroll_col = ft.Column(
            controls=[],
            spacing=10,
            expand=True,
            scroll=ft.ScrollMode.AUTO,
        )
        self._body_scroll_col.controls = [
            self._build_bcv_panel(accent, card_bg, text_color, subtext, border),
            ft.Divider(height=6, color=border),
            self._build_filtros_panel(accent, card_bg, text_color, border),
            ft.Divider(height=6, color=border),
            self._build_tabla_panel(accent, card_bg, text_color, subtext, border),
        ]
        return self._body_scroll_col

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
        """Orden fijo de columnas, filtrando las ocultables que el usuario desactivó.

        El "marcador" abre SIEMPRE la lista (y "acciones" la cierra): su razón
        de ser es que, al desplazarse a la derecha de la tabla, el usuario deje
        de confundir las filas entre sí, así que tiene que ser la primera
        columna y no puede ocultarse.
        """
        return (
            ["marcador"]
            + [k for k in self._columnas_ocultables if self._columnas_visibles.get(k, True)]
            + ["acciones"]
        )

    def _build_columna_header(self, key: str, accent, text_color) -> ft.DataColumn:
        color = accent if key in ("acciones", "marcador") else text_color
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

    def _handle_cambio_modo_vista(self, e):
        if e.control.selected:
            self._modo_vista = list(e.control.selected)[0]
            # La elección sobrevive al cierre de la aplicación (por usuario);
            # un modo desconocido no debe tumbar la interfaz.
            try:
                guardar_vista_inventario(self.username, self._modo_vista)
            except ValueError:
                pass
            self._cargar_filas()
            self._safe_update(e)

    # ─────────────────────────────────────────────────────────────────────────
    # MARCADOR Y SOMBREADO DE LA FILA (Nueva Función 3)
    # ─────────────────────────────────────────────────────────────────────────
    # Mecánica, tal como la pidió el usuario:
    #   - Un clic en cualquier parte de la fila (no solo en la casilla) marca
    #     el ítem: se sombrea y la casilla izquierda queda marcada. El marcado
    #     sobrevive al desplazamiento horizontal porque es estado del modelo,
    #     no del control que recibió el clic.
    #   - Solo hay DOS formas de deseleccionar: volver a la izquierda y hacer
    #     clic DENTRO de la casilla marcada (`alternar`), o pulsar [Esc]
    #     (`limpiar`).
    #   - Con un ítem marcado, solo ese ítem puede accionar sus seis botones;
    #     los de las demás filas quedan deshabilitados VISIBLEMENTE.
    #   - Sin nada marcado, todo funciona como en versiones anteriores.
    def _al_cambiar_seleccion(self):
        """Repinta la tabla y la barra cuando la selección cambió de verdad.

        Lo llama el modelo (`SeleccionLista.on_cambio`), así que cualquier
        camino que altere la selección —clic, casilla, Esc, borrado del lote—
        termina repintando por aquí y no hay que acordarse en cada handler.
        """
        if not hasattr(self, "_dt"):
            return  # vista aún sin construir (p. ej. durante `__init__`)
        self._actualizar_barra_seleccion()
        self._cargar_filas()
        self._safe_update()

    def seleccionar_item(self, codigo: str, e=None):
        """Clic en cualquier parte de la fila: marca (nunca desmarca)."""
        self._asegurar_captura_escape(e)
        self._seleccion.seleccionar(codigo)

    def alternar_item(self, codigo: str, e=None):
        """Clic DENTRO de la casilla marcadora: marca o desmarca."""
        self._asegurar_captura_escape(e)
        self._seleccion.alternar(codigo)

    def limpiar_seleccion(self, e=None):
        """Quita la selección (tecla [Esc] o botón de la barra)."""
        self._seleccion.limpiar()
        self._actualizar_barra_seleccion()
        self._safe_update(e)

    def alternar_modo_seleccion(self, e=None):
        """Entra o sale del modo de selección múltiple (borrado por lote)."""
        self._asegurar_captura_escape(e)
        self._seleccion.alternar_modo()
        self._actualizar_barra_seleccion()
        self._cargar_filas()
        self._safe_update(e)

    # ── Captura de [Esc] ────────────────────────────────────────────────────
    def _asegurar_captura_escape(self, e=None):
        """Engancha el teclado de la página la primera vez que se marca algo.

        No se engancha al construir la vista porque entonces todavía no hay
        `page` (la vista se instancia headless y se monta después), y porque
        [Esc] solo tiene sentido cuando hay algo marcado. El handler que
        estuviera puesto se guarda y se sigue invocando: esta vista comparte la
        página con el resto del Dashboard y no debe quedarse con el teclado.
        """
        p = self._get_page(e)
        if p is None:
            return
        try:
            actual = getattr(p, "on_keyboard_event", None)
            if actual is self._handle_tecla:
                return
            self._keyboard_previo = actual
            p.on_keyboard_event = self._handle_tecla
        except (AttributeError, RuntimeError):
            pass  # página sin soporte de teclado: el botón de la barra suple a [Esc]

    def _handle_tecla(self, e=None):
        """[Esc] deselecciona; cualquier otra tecla sigue su curso."""
        tecla = str(getattr(e, "key", "") or "")
        if tecla.strip().lower() == "escape":
            self.limpiar_seleccion(e)
        previo = self._keyboard_previo
        if previo is not None and previo is not self._handle_tecla:
            previo(e)

    # ── Barra de estado de la selección ─────────────────────────────────────
    def _build_barra_seleccion(self, accent, subtext) -> ft.Row:
        """Controles para ver y manejar la selección sin adivinar.

        El usuario necesita una forma evidente de entrar y salir del modo de
        lote y de saber cuántos ítems lleva marcados; si eso no está a la
        vista, el modo múltiple se vuelve un estado invisible que deshabilita
        botones sin explicación.
        """
        self._lbl_seleccion = ft.Text(
            self._seleccion.descripcion_estado(), size=11, color=subtext,
        )
        self._btn_modo_seleccion = ft.IconButton(
            ft.Icons.CHECKLIST_ROUNDED,
            icon_color=subtext,
            tooltip="Activar selección múltiple (para borrar varios ítems)",
            on_click=self.alternar_modo_seleccion,
        )
        self._btn_limpiar_seleccion = ft.IconButton(
            ft.Icons.HIGHLIGHT_OFF_ROUNDED,
            icon_color=subtext,
            tooltip="Quitar la selección (equivale a pulsar Esc)",
            visible=False,
            on_click=self.limpiar_seleccion,
        )
        self._btn_borrar_lote = ft.Button(
            content=ft.Text("Borrar marcados", size=11, weight=ft.FontWeight.BOLD),
            icon=ft.Icons.DELETE_SWEEP_ROUNDED,
            style=ft.ButtonStyle(
                bgcolor=ft.Colors.RED_600, color=ft.Colors.WHITE,
                shape=ft.RoundedRectangleBorder(radius=12),
            ),
            visible=False,
            on_click=self._confirmar_eliminar_lote,
        )
        self._barra_seleccion = ft.Row(
            controls=[
                self._btn_modo_seleccion,
                self._lbl_seleccion,
                self._btn_limpiar_seleccion,
                self._btn_borrar_lote,
            ],
            spacing=4,
        )
        return self._barra_seleccion

    def _actualizar_barra_seleccion(self):
        """Sincroniza etiqueta, iconos y visibilidad con el estado del modelo."""
        if not hasattr(self, "_lbl_seleccion"):
            return
        accent = self.get_accent_color()
        subtext = self.get_subtext_color()
        multiple = self._seleccion.es_multiple

        self._lbl_seleccion.value = self._seleccion.descripcion_estado()
        self._lbl_seleccion.color = accent if self._seleccion.hay_seleccion else subtext
        self._btn_modo_seleccion.icon_color = accent if multiple else subtext
        self._btn_modo_seleccion.tooltip = (
            "Salir de la selección múltiple"
            if multiple
            else "Activar selección múltiple (para borrar varios ítems)"
        )
        self._btn_limpiar_seleccion.visible = self._seleccion.hay_seleccion
        # Borrar en lote solo se ofrece en el modo múltiple: en modo marcador,
        # el borrado del ítem señalado ya está en su propio botón de la fila.
        self._btn_borrar_lote.visible = multiple and self._seleccion.hay_seleccion
        if self._btn_borrar_lote.visible:
            self._btn_borrar_lote.content = ft.Text(
                f"Borrar marcados ({self._seleccion.cantidad})",
                size=11, weight=ft.FontWeight.BOLD,
            )

    # ─────────────────────────────────────────────────────────────────────────
    # ACCIONES DE UN ÍTEM (los seis botones de la fila)
    # ─────────────────────────────────────────────────────────────────────────
    # Cada botón entra por aquí, con un nombre estable y un solo argumento (el
    # código del ítem): así la próxima ola puede enlazar F1..F6 al ítem marcado
    # sin tener que alcanzar closures anónimas enterradas en `_cargar_filas`.
    ACCIONES_ITEM = ("info", "cobrar", "carrito", "historial", "editar", "borrar")

    def _producto_en_pantalla(self, codigo: str) -> dict | None:
        """Producto de la página actual por su código (relee la base si hace
        falta, para que una acción por teclado funcione aunque la fila ya no
        esté en el índice)."""
        codigo = (codigo or "").strip()
        if not codigo:
            return None
        prod = self._productos_en_pantalla.get(codigo)
        if prod is not None:
            return prod
        return obtener_producto(codigo, rol_usuario=self._rol_para_costos())

    def accion_info(self, codigo: str, e=None):
        prod = self._producto_en_pantalla(codigo)
        if prod:
            self._abrir_modal_detalle(prod, e)

    def accion_cobrar(self, codigo: str, e=None):
        prod = self._producto_en_pantalla(codigo)
        if prod:
            self._procesar_venta_directo(prod, e)

    def accion_carrito(self, codigo: str, e=None):
        prod = self._producto_en_pantalla(codigo)
        if prod:
            self._abrir_modal_agregar_carrito(prod, e)

    def accion_historial(self, codigo: str, e=None):
        self._abrir_modal_historial(codigo, e)

    def accion_editar(self, codigo: str, e=None):
        self._abrir_flujo_edicion(codigo, e)

    def accion_borrar(self, codigo: str, e=None):
        self._confirmar_eliminar(codigo, e)

    def _handlers_accion(self) -> dict:
        return {
            "info": self.accion_info,
            "cobrar": self.accion_cobrar,
            "carrito": self.accion_carrito,
            "historial": self.accion_historial,
            "editar": self.accion_editar,
            "borrar": self.accion_borrar,
        }

    def ejecutar_accion_item(self, accion: str, codigo: str, e=None) -> bool:
        """Punto de entrada único de los seis botones (y de los futuros atajos).

        Vuelve a comprobar `puede_accionar` aunque el botón ya venga
        deshabilitado: la regla tiene que valer también para quien invoque la
        acción por teclado o por código, no solo para quien hace clic.
        """
        handler = self._handlers_accion().get(accion)
        if handler is None:
            raise ValueError(f"Acción de ítem desconocida: {accion!r}")
        if accion == "historial" and not self.es_admin:
            return False
        if not self._seleccion.puede_accionar(codigo):
            self._snack(
                "Hay otro ítem marcado. Haga clic en su casilla o pulse Esc para liberarlo.",
                ft.Colors.AMBER_700, e,
            )
            return False
        handler(codigo, e)
        return True

    def ejecutar_accion_sobre_seleccionado(self, accion: str, e=None) -> bool:
        """Misma acción, aplicada al ítem marcado (base de los atajos F1..F6)."""
        codigo = self._seleccion.seleccionado
        if not codigo:
            return False
        return self.ejecutar_accion_item(accion, codigo, e)

    def _build_tabla_panel(self, accent, card_bg, text_color, subtext, border) -> ft.Control:
        self._dt = ft.DataTable(
            columns=[self._build_columna_header(k, accent, text_color) for k in self._columnas_orden_visible()],
            rows=[],
        )
        # Separación de ejes (ver nota en `get_body`): la Row scrollea en
        # HORIZONTAL (única dueña de ese eje, la tabla es más ancha que la
        # pantalla) y la Column contenedora NO scrollea — crece con su
        # contenido y el desplazamiento vertical lo maneja el cuerpo de la
        # página. Ambos atributos conservan su nombre porque son los targets
        # de los botones de navegación rápida (`ui.components.scroll_nav`).
        self._tabla_scroll_row = ft.Row(controls=[self._dt], scroll=ft.ScrollMode.ALWAYS)
        self._tabla_scroll_col = ft.Column(controls=[self._tabla_scroll_row], tight=True)
        # El cluster HORIZONTAL va en la barra de herramientas de la tarjeta:
        # flotando en la esquina superior derecha del `Stack` tapaba la fila de
        # encabezados de columna. El VERTICAL sí sigue flotando abajo a la
        # derecha, donde no cubre nada.
        self._nav_h = build_inline_h_nav(self._tabla_scroll_row, accent)
        self._nav_v = build_floating_v_nav(
            getattr(self, "_body_scroll_col", None) or self._tabla_scroll_col,
            accent,
        )
        # El cluster vertical flota sobre la esquina inferior derecha del
        # `Stack`, así que sin esta holgura se dibujaba encima del texto de la
        # última fila de la tabla. Reservarla al pie deja al cluster sobre
        # espacio vacío sin alterar el scroll (el eje sigue siendo del cuerpo).
        self._tabla_con_holgura = ft.Container(
            content=self._tabla_scroll_col,
            padding=ft.Padding.only(bottom=self._HOLGURA_NAV_FLOTANTE),
        )
        self._vista_container = ft.Container()
        self._lbl_pag = ft.Text("", color=subtext, size=12)

        self._btn_modo_vista = ft.SegmentedButton(
            selected=[self._modo_vista],
            segments=[
                ft.Segment(
                    value="separado",
                    label=ft.Text("Separado", size=11, weight=ft.FontWeight.W_600),
                    icon=ft.Icon(ft.Icons.VIEW_COLUMN_ROUNDED, size=16),
                ),
                ft.Segment(
                    value="agrupado",
                    label=ft.Text("Agrupado", size=11, weight=ft.FontWeight.W_600),
                    icon=ft.Icon(ft.Icons.VIEW_LIST_ROUNDED, size=16),
                ),
                ft.Segment(
                    value="tarjetas",
                    label=ft.Text("Tarjetas", size=11, weight=ft.FontWeight.W_600),
                    icon=ft.Icon(ft.Icons.GRID_VIEW_ROUNDED, size=16),
                ),
            ],
            on_change=self._handle_cambio_modo_vista,
        )

        # Se construye ANTES de cargar las filas para que el estado de la
        # selección ya tenga dónde mostrarse en el primer pintado.
        self._build_barra_seleccion(accent, subtext)
        self._actualizar_barra_seleccion()

        self._cargar_filas(text_color, accent)

        btn_prev = ft.IconButton(ft.Icons.CHEVRON_LEFT, on_click=self._pagina_anterior)
        btn_next = ft.IconButton(ft.Icons.CHEVRON_RIGHT, on_click=self._pagina_siguiente)

        self._tabla_panel = self.create_card(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Row([
                                ft.Icon(ft.Icons.INVENTORY_2_ROUNDED, color=accent),
                                ft.Text("Catálogo de Productos", size=15, weight=ft.FontWeight.BOLD, color=text_color),
                            ], spacing=8),
                            ft.Row([
                                self._barra_seleccion,
                                self._nav_h,
                                self._btn_modo_vista,
                                self._build_selector_columnas(accent, text_color),
                            ], spacing=8),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        wrap=True,
                    ),
                    ft.Container(
                        content=ft.Column(
                            controls=[
                                self._vista_container,
                                ft.Row(
                                    controls=[
                                        self._lbl_pag,
                                        ft.Row([btn_prev, btn_next], spacing=4),
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
        return self._tabla_panel

    def _cargar_filas(self, text_color=None, accent=None):
        if text_color is None:
            text_color = self.get_text_color()
        if accent is None:
            accent = self.get_accent_color()
        subtext = self.get_subtext_color()
        card_bg = self.get_card_bg()
        border = self.get_border_color()

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

        # Índice por código de lo que hay en pantalla: las acciones por nombre
        # (y los atajos de teclado que vienen después) reciben un código y
        # resuelven el producto aquí, sin depender del `dict` de un clic.
        self._productos_en_pantalla = {p["codigo"]: p for p in todos}

        # Selector de columnas visible solo en modo separado
        if hasattr(self, "_btn_columnas"):
            self._btn_columnas.visible = (self._modo_vista == "separado")

        def _boton_accion(accion: str, codigo: str, icono, color, tooltip: str, size=None):
            """Botón de la fila cableado a `ejecutar_accion_item`.

            `disabled` es la mitad visible de la regla del marcador: con otro
            ítem seleccionado, el botón se ve apagado en vez de aceptar el clic
            y no hacer nada (un botón que ignora en silencio se lee como un
            cuelgue de la aplicación).
            """
            habilitado = self._seleccion.puede_accionar(codigo)
            return ft.IconButton(
                icono,
                icon_color=color,
                icon_size=size,
                tooltip=tooltip if habilitado else f"{tooltip} (hay otro ítem marcado)",
                disabled=not habilitado,
                on_click=lambda ev, a=accion, c=codigo: self.ejecutar_accion_item(a, c, ev),
            )

        def botones_accion(p, size=None) -> list[ft.Control]:
            """Los seis botones del ítem, en el orden que usarán F1..F6."""
            cod = p["codigo"]
            botones = [
                _boton_accion("info", cod, ft.Icons.INFO_OUTLINE_ROUNDED, accent, "Ver detalle del ítem", size),
                _boton_accion("cobrar", cod, ft.Icons.POINT_OF_SALE, ft.Colors.BLUE_400, "Procesar Venta", size),
                _boton_accion("carrito", cod, ft.Icons.ADD_SHOPPING_CART, ft.Colors.GREEN_400, "Añadir al Carrito", size),
            ]
            if self.es_admin:
                botones.append(
                    _boton_accion("historial", cod, ft.Icons.HISTORY_ROUNDED, ft.Colors.PURPLE_300, "Historial Clínico", size)
                )
            botones.append(_boton_accion("editar", cod, ft.Icons.EDIT_OUTLINED, accent, "Editar", size))
            botones.append(_boton_accion("borrar", cod, ft.Icons.DELETE_OUTLINED, ft.Colors.RED_400, "Eliminar", size))
            return botones

        def celda_acciones_lineal(p):
            return ft.Row(botones_accion(p), spacing=0)

        def celda_acciones_grid(p):
            botones = botones_accion(p, size=18)
            corte = 3
            return ft.Column([
                ft.Row(botones[:corte], spacing=0, tight=True),
                ft.Row(botones[corte:], spacing=0, tight=True),
            ], spacing=0, tight=True)

        # ── Casilla marcadora y sombreado de la fila ─────────────────────────
        def celda_marcador(p) -> ft.Control:
            marcado = self._seleccion.esta_seleccionado(p["codigo"])
            if self._seleccion.es_multiple:
                icono = ft.Icons.CHECK_BOX_ROUNDED if marcado else ft.Icons.CHECK_BOX_OUTLINE_BLANK_ROUNDED
            else:
                icono = ft.Icons.RADIO_BUTTON_CHECKED if marcado else ft.Icons.RADIO_BUTTON_UNCHECKED
            return ft.Container(
                content=ft.Icon(icono, color=accent if marcado else subtext, size=20),
                width=34,
                alignment=ft.Alignment.CENTER,
                tooltip=(
                    "Clic para quitar la marca de este ítem"
                    if marcado else "Clic para marcar este ítem"
                ),
            )

        def celda_marcador_dc(p) -> ft.DataCell:
            """La casilla atiende su propio toque: es la única de la fila que
            DESMARCA (`alternar`), mientras el resto de la fila solo marca."""
            return ft.DataCell(
                celda_marcador(p),
                on_tap=lambda ev, cod=p["codigo"]: self.alternar_item(cod, ev),
            )

        def construir_fila(p, celdas: list[ft.DataCell]) -> ft.DataRow:
            marcado = self._seleccion.esta_seleccionado(p["codigo"])
            return ft.DataRow(
                cells=celdas,
                selected=marcado,
                # Sombreado persistente: es estado del modelo, así que sobrevive
                # al desplazamiento horizontal y a los repintados.
                color=ft.Colors.with_opacity(0.22, accent) if marcado else None,
                # Hace la fila COMPLETA sensible al clic ("no importa si es
                # fuera de la casilla"); la celda del marcador tiene su propio
                # `on_tap` y por eso no cae aquí.
                on_select_change=lambda ev, cod=p["codigo"]: self.seleccionar_item(cod, ev),
                data=p["codigo"],
            )

        # Limpiar filas primero para evitar descalce de conteo entre celdas y columnas durante el diff de Flet al alternar modos
        self._dt.rows = []

        if self._modo_vista == "separado":
            self._dt.data_row_min_height = 48
            self._dt.data_row_max_height = 48
            self._dt.columns = [self._build_columna_header(k, accent, text_color) for k in self._columnas_orden_visible()]
            constructores_celda = {
                "marcador": celda_marcador,
                "codigo": lambda p: ft.Text(p["codigo"], color=accent, weight=ft.FontWeight.W_600),
                "referencia": lambda p: ft.Text(p["referencia"] or "-", color=text_color),
                "descripcion": lambda p: ft.Text((p["descripcion_general"] or "-")[:40], color=text_color),
                "departamento": lambda p: ft.Text(p["departamento"] or "-", color=text_color),
                "marca": lambda p: ft.Text(p["marca"] or "-", color=text_color),
                "precio_efectivo": lambda p: ft.Text(f"${p['precio_dolares']:.2f}", color=ft.Colors.GREEN_400),
                "precio_bcv": lambda p: ft.Text(f"${p.get('precio_bcv', 0):.2f}", color=ft.Colors.CYAN_300),
                "monto_bs": lambda p: ft.Text(f"Bs {p.get('monto_bcv_bolivares', 0):.2f}", color=ft.Colors.AMBER_300),
                "existencia": lambda p: ft.Text(str(p["existencia"]), color=text_color),
                "acciones": celda_acciones_lineal,
            }
            columnas = self._columnas_orden_visible()
            self._dt.rows = [
                construir_fila(p, [
                    celda_marcador_dc(p) if k == "marcador"
                    else ft.DataCell(constructores_celda[k](p))
                    for k in columnas
                ])
                for p in todos
            ]
            self._nav_h.visible = True
            self._nav_v.visible = True
            # Sin altura fija: el Stack se ajusta a la tabla y el scroll
            # vertical lo aporta el cuerpo de la página (un solo dueño del eje).
            # Solo flota el cluster VERTICAL: el horizontal vive en la barra de
            # herramientas y ya no se solapa con los encabezados de columna.
            self._vista_container.content = ft.Stack(
                controls=[
                    self._tabla_con_holgura,
                    self._nav_v,
                ],
            )

        elif self._modo_vista == "agrupado":
            self._dt.data_row_min_height = 72
            self._dt.data_row_max_height = 95
            self._dt.columns = [
                # El marcador también abre la lista agrupada: la confusión de
                # filas al moverse a la derecha es la misma en los dos formatos.
                self._build_columna_header("marcador", accent, text_color),
                ft.DataColumn(ft.Text("Producto (Descripción / Cód / Ref)", color=text_color, weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("Depto / Marca", color=text_color, weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("Precios (Efvo / BCV / Bs)", color=text_color, weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("Exist.", color=text_color, weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("Acciones", color=accent, weight=ft.FontWeight.BOLD)),
            ]
            rows = []
            for p in todos:
                celda_prod = ft.Container(
                    content=ft.Column([
                        ft.Text(
                            p["descripcion_general"] or "-",
                            size=13, weight=ft.FontWeight.BOLD, color=text_color,
                            max_lines=2, overflow=ft.TextOverflow.ELLIPSIS,
                        ),
                        ft.Row([
                            ft.Container(
                                content=ft.Text(f"Cód: {p['codigo']}", size=11, weight=ft.FontWeight.W_600, color=accent),
                                bgcolor=ft.Colors.with_opacity(0.12, accent),
                                padding=ft.Padding.symmetric(horizontal=6, vertical=2),
                                border_radius=6,
                            ),
                            ft.Container(
                                content=ft.Text(f"Ref: {p['referencia'] or '-'}", size=11, color=subtext),
                                bgcolor=ft.Colors.with_opacity(0.08, subtext),
                                padding=ft.Padding.symmetric(horizontal=6, vertical=2),
                                border_radius=6,
                            ),
                        ], spacing=6),
                    ], spacing=4, tight=True),
                    width=450,
                    padding=ft.Padding.symmetric(vertical=6),
                )

                celda_clasif = ft.Container(
                    content=ft.Column([
                        ft.Text(p["departamento"] or "-", size=12, weight=ft.FontWeight.W_600, color=text_color),
                        ft.Text(p["marca"] or "-", size=11, color=subtext),
                    ], spacing=2, tight=True),
                    width=180,
                    padding=ft.Padding.symmetric(vertical=6),
                )

                celda_precios = ft.Container(
                    content=ft.Column([
                        ft.Row([
                            ft.Text(f"${p['precio_dolares']:.2f}", size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_400),
                            ft.Text(f"${p.get('precio_bcv', 0):.2f}", size=11, color=ft.Colors.CYAN_300),
                        ], spacing=6),
                        ft.Text(f"Bs {p.get('monto_bcv_bolivares', 0):.2f}", size=11, color=ft.Colors.AMBER_300, weight=ft.FontWeight.W_600),
                    ], spacing=2, tight=True),
                    width=220,
                    padding=ft.Padding.symmetric(vertical=6),
                )

                celda_stock = ft.Container(
                    content=ft.Text(str(p["existencia"]), color=text_color, weight=ft.FontWeight.BOLD, size=13),
                    width=80,
                    alignment=ft.Alignment.CENTER,
                )

                celda_acc = ft.Container(
                    content=celda_acciones_lineal(p),
                    width=250,
                    padding=ft.Padding.symmetric(vertical=6),
                )

                rows.append(
                    construir_fila(p, [
                        celda_marcador_dc(p),
                        ft.DataCell(celda_prod),
                        ft.DataCell(celda_clasif),
                        ft.DataCell(celda_precios),
                        ft.DataCell(celda_stock),
                        ft.DataCell(celda_acc),
                    ])
                )
            self._dt.rows = rows
            self._nav_h.visible = True
            self._nav_v.visible = True
            # Sin altura fija: el Stack se ajusta a la tabla y el scroll
            # vertical lo aporta el cuerpo de la página (un solo dueño del eje).
            # Solo flota el cluster VERTICAL: el horizontal vive en la barra de
            # herramientas y ya no se solapa con los encabezados de columna.
            self._vista_container.content = ft.Stack(
                controls=[
                    self._tabla_con_holgura,
                    self._nav_v,
                ],
            )

        elif self._modo_vista == "tarjetas":
            self._nav_h.visible = False
            self._nav_v.visible = False
            tarjetas = []
            for p in todos:
                tarjeta = ft.Container(
                    content=ft.Column([
                        ft.Row([
                            ft.Text(f"Código: {p['codigo']}", size=12, weight=ft.FontWeight.BOLD, color=accent),
                            ft.Container(
                                content=ft.Text(f"Stock: {p['existencia']:.0f}", size=11, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                                bgcolor=ft.Colors.GREEN_700 if p['existencia'] > 0 else ft.Colors.RED_700,
                                padding=ft.Padding.symmetric(horizontal=8, vertical=2),
                                border_radius=10,
                            )
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        ft.Divider(height=4),
                        ft.Text(p["descripcion_general"] or "-", size=14, weight=ft.FontWeight.BOLD, color=text_color, max_lines=2),
                        ft.Row([
                            ft.Text(f"Ref: {p['referencia'] or '-'}", size=11, color=subtext),
                            ft.Text(f"{p['departamento'] or '-'} / {p['marca'] or '-'}", size=11, color=subtext),
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        ft.Divider(height=4),
                        ft.Row([
                            ft.Column([
                                ft.Text("Efvo ($)", size=10, color=subtext),
                                ft.Text(f"${p['precio_dolares']:.2f}", size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_400),
                            ], spacing=1),
                            ft.Column([
                                ft.Text("BCV ($)", size=10, color=subtext),
                                ft.Text(f"${p.get('precio_bcv', 0):.2f}", size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.CYAN_300),
                            ], spacing=1),
                            ft.Column([
                                ft.Text("Monto (Bs)", size=10, color=subtext),
                                ft.Text(f"Bs {p.get('monto_bcv_bolivares', 0):.2f}", size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.AMBER_300),
                            ], spacing=1),
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        ft.Divider(height=4),
                        celda_acciones_lineal(p),
                    ], spacing=6),
                    padding=12, border_radius=14, width=320,
                    bgcolor=card_bg,
                    border=ft.Border.all(1, border),
                )
                tarjetas.append(tarjeta)

            if not tarjetas:
                self._vista_container.content = ft.Container(
                    content=ft.Text("No se encontraron productos.", color=subtext),
                    alignment=ft.Alignment.CENTER, height=180,
                )
            else:
                # Sin scroll propio ni altura fija: las tarjetas envuelven y el
                # eje vertical sigue siendo del cuerpo de la página.
                self._vista_container.content = ft.Column(
                    controls=[ft.Row(controls=tarjetas, wrap=True, spacing=10)],
                    tight=True,
                )

    def _rol_para_costos(self) -> str | None:
        """Rol nombrado que exigen los servicios para devolver los costos. La
        vista recibe `es_admin` como bandera, así que cuando no llega un rol
        explícito se traduce a un rol administrativo equivalente."""
        return self._rol_usuario or ("administrador" if self.es_admin else None)

    def _abrir_modal_detalle(self, prod: dict, e=None):
        """Resumen completo del ítem en el modal reutilizable. Se relee el
        producto con el rol para que los COSTOS lleguen solo si corresponde
        (las filas de la tabla se cargan sin ellos)."""
        codigo = (prod or {}).get("codigo", "")
        completo = obtener_producto(codigo, rol_usuario=self._rol_para_costos()) or dict(prod or {})

        def _cerrar(ev):
            self._close_dialog(ev, dialog=dlg)

        def _editar(ev):
            self._close_dialog(ev, dialog=dlg)
            self._abrir_flujo_edicion(codigo, ev)

        dlg = construir_modal_detalle_producto(
            completo,
            es_admin=self.es_admin,
            paleta={
                "texto": self.get_text_color(),
                "subtexto": self.get_subtext_color(),
                "acento": self.get_accent_color(),
                "fondo": self.get_card_bg(),
                "borde": self.get_border_color(),
            },
            on_cerrar=_cerrar,
            on_editar=_editar,
        )
        self._open_dialog(dlg, e)

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
            self._close_dialog(ev, dialog=dlg)

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
    def _resetear_estado_formulario(self):
        """Deja el flujo de ingreso/edición en su estado inicial. Se invoca
        desde TODOS los puntos de salida (cancelar, guardar, reabrir) para que
        ningún registro herede el código verificado ni el modo edición del
        anterior."""
        self._form_codigo_verificado = False
        self._editing_codigo = None

    def _cancelar_flujo_formulario(self, e=None):
        """Cancelación desde cualquier paso: cierra los diálogos del flujo que
        queden abiertos (incluido un aviso superpuesto) y limpia el estado."""
        self._cerrar_todos_los_dialogos(e)
        self._resetear_estado_formulario()

    def _abrir_flujo_ingreso(self, e):
        """Paso 1: Mostrar campo de código para verificar existencia."""
        self._cerrar_todos_los_dialogos(e)
        self._resetear_estado_formulario()
        self._mostrar_paso1_dialogo(e, codigo_inicial="")

    def _abrir_flujo_edicion(self, codigo: str, e=None):
        """Abre el formulario en modo edición para un producto existente. Se
        lee con el rol para que un administrador vea los costos ya registrados
        (un vendedor los recibe filtrados y no puede alterarlos)."""
        prod = obtener_producto(codigo, rol_usuario=self._rol_para_costos())
        if not prod:
            self._snack(f"Producto '{codigo}' no encontrado.", ft.Colors.RED_700, e)
            return
        self._cerrar_todos_los_dialogos(e)
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
            """Aviso superpuesto al paso 1 (queda encima en la pila): al
            descartarlo, el paso 1 sigue abierto y operativo."""

            async def _limpiar_codigo(ev2):
                """Botón "No — Limpiar Código": cierra SOLO el aviso y devuelve
                el paso 1 usable, con el campo vacío y el foco dentro. Es `async`
                porque `Control.focus()` es una coroutine en Flet 0.86 (un
                handler sync la descartaría sin ejecutarla)."""
                _close_dup(ev2)
                inp_cod.value = ""
                lbl_status.value = ""
                self._safe_update(ev2)
                try:
                    await inp_cod.focus()
                except Exception:
                    pass  # sin page viva (o control desmontado) no hay foco que dar.

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
                    ft.TextButton("No — Limpiar Código", on_click=_limpiar_codigo),
                    ft.Button(
                        "Sí — Ver Producto",
                        style=ft.ButtonStyle(
                            bgcolor=accent, color=ft.Colors.WHITE,
                            shape=ft.RoundedRectangleBorder(radius=12)
                        ),
                        on_click=lambda ev2: (
                            _close_dup(ev2),
                            self._abrir_flujo_edicion(codigo, ev2),
                        ),
                    ),
                ],
                bgcolor=card_bg,
            )

            def _close_dup(ev2):
                """Cierra SOLO el aviso; el paso 1 vuelve a ser el tope."""
                self._close_dialog(ev2, dialog=dlg_dup)

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
                ft.TextButton("Cancelar", on_click=self._cancelar_flujo_formulario),
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
        # El departamento ya no es texto libre: dos dropdowns jerárquicos
        # alimentados por el catálogo, con la opción de registrar valores
        # nuevos al final de cada lista. La lógica vive en el componente.
        selector_depto = SelectorDepartamentos(
            obtener_departamentos=listar_departamentos,
            obtener_sub_departamentos=listar_sub_departamentos,
            on_crear_departamento=crear_departamento,
            on_crear_sub_departamento=crear_sub_departamento,
            on_cambio=self._safe_update,
            ancho=230,
            color_texto=text_color, color_borde=border, color_acento=accent,
        )
        selector_depto.set_valores(d.get("departamento", ""), d.get("sub_departamento", ""))
        self._selector_depto = selector_depto
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

        def _numero_o_vacio(valor) -> str:
            """Texto para un campo numérico opcional (`None` → vacío)."""
            return "" if valor is None else str(valor)

        # Umbral de alerta propio del producto (no es un dato restringido).
        f_alerta_stock = tf("Alerta de Stock Mínimo", "alerta_stock_minimo",
                            value=_numero_o_vacio(d.get("alerta_stock_minimo")),
                            width=200, kb=ft.KeyboardType.NUMBER,
                            hint="Entero; vacío = sin alerta")

        # ── COSTOS del negocio (solo administración) ─────────────────────────
        # Distintos de los precios de venta: es lo que cuesta adquirir el
        # producto. Con existencia >= 1 el Costo USD Efectivo es obligatorio
        # (ERR_PROD_COSTO), así que sin estos campos el formulario no podía
        # guardar ningún producto con stock.
        f_costo_usd = tf("Costo USD (Efectivo)" + (" *" if self.es_admin else ""), "costo_usd_efectivo",
                         value=_numero_o_vacio(d.get("costo_usd_efectivo")),
                         width=190, kb=ft.KeyboardType.NUMBER)
        f_costo_bcv = tf("Costo USD (BCV)", "costo_usd_bcv",
                         value=_numero_o_vacio(d.get("costo_usd_bcv")),
                         width=190, kb=ft.KeyboardType.NUMBER)
        fila_costos = ft.Row([f_costo_usd, f_costo_bcv], spacing=12, wrap=True,
                             visible=self.es_admin)

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
            for campo in (f_ref, f_desc, f_precio_usd, f_precio_bcv, f_costo_usd, f_alerta_stock):
                campo.error_text = None
            selector_depto.limpiar_errores()

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
            if not selector_depto.valor_departamento():
                selector_depto.marcar_error()
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

            # Con stock, el Costo USD Efectivo es obligatorio (ERR_PROD_COSTO).
            # Se avisa aquí, junto al campo, en vez de dejar que el servicio
            # rechace el guardado con un snack genérico al final del flujo.
            if self.es_admin and existencia_val >= 1 and not (f_costo_usd.value or "").strip():
                f_costo_usd.error_text = "Requerido si Existencia >= 1"
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
                "departamento": selector_depto.valor_departamento(),
                "sub_departamento": selector_depto.valor_sub_departamento(),
                "marca": f_marca.value,
                "codigo_barras": f_barras.value,
                "nombre_referencia_corto": f_nombre_corto.value,
                "precio_dolares": f_precio_usd.value,
                "precio_bcv": f_precio_bcv.value,
                "existencia": f_existencia.value,
                "alerta_stock_minimo": f_alerta_stock.value,
                "proveedor_id": dd_proveedor.value or None,
            }
            # Las claves de costo solo viajan si el rol puede editarlas: el
            # servicio rechaza (PermissionError) que un no-admin las envíe,
            # incluso vacías.
            if self.es_admin:
                datos["costo_usd_efectivo"] = f_costo_usd.value
                datos["costo_usd_bcv"] = f_costo_bcv.value
            self._mostrar_paso3_confirmacion(ev, datos)

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text(titulo_paso, color=text_color),
            content=ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row([cod_display, f_ref, f_marca], spacing=12, wrap=True),
                        f_desc,
                        selector_depto.construir_fila(),
                        ft.Row([f_existencia, f_alerta_stock, dd_proveedor, f_barras], spacing=12, wrap=True),
                        fila_precios,
                        fila_costos,
                        f_nombre_corto,
                    ],
                    spacing=14,
                    scroll=ft.ScrollMode.AUTO,
                ),
                width=720,
                height=420,
            ),
            actions=[
                ft.TextButton("Cancelar", on_click=self._cancelar_flujo_formulario),
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
            ("Sub-Departamento", "sub_departamento"),
            ("Marca", "marca"),
            ("Existencia", "existencia"),
            ("Alerta de Stock Mínimo", "alerta_stock_minimo"),
            ("Precio USD (Efectivo)", "precio_dolares"),
            ("Precio USD (BCV)", "precio_bcv"),
            # Las claves de costo solo están en `datos` si el rol es
            # administrativo, y las filas se arman solo con las presentes.
            ("Costo USD (Efectivo)", "costo_usd_efectivo"),
            ("Costo USD (BCV)", "costo_usd_bcv"),
            ("Proveedor ID", "proveedor_id"),
            ("Código de Barras", "codigo_barras"),
            ("Nombre Corto", "nombre_referencia_corto"),
        ]

        # El valor va SIEMPRE dentro de un contenedor de ancho acotado
        # (`expand=True` sobre el ancho restante del diálogo) y con envoltura
        # multilínea: una descripción larga debe cortar en varias líneas y
        # elidir, nunca desbordarse hacia la derecha del diálogo.
        #
        # ── Densidad del resumen (Cambio 3 de octubre 2026) ──────────────────
        # Las casillas van PEGADAS (la Column no agrega separación y cada fila
        # ocupa solo el alto de una línea), como en la primera versión: la
        # separación generosa que había desperdiciaba la ventana y obligaba a
        # desplazarse para ver el resumen completo. Lo que NO se revierte es el
        # acotado del valor: el espaciado grande se había introducido para
        # arreglar el desborde de la descripción, y ese arreglo sigue vivo en el
        # contenedor de ancho acotado + envoltura multilínea de abajo.
        filas_resumen = []
        for etiqueta, key in campos_orden:
            # Solo se resumen los campos que el formulario realmente envió: un
            # rol sin acceso a los costos no debe ver ni sus etiquetas.
            if key not in datos:
                continue
            val = str(datos.get(key) or "").strip()
            mostrar = val if val and val not in ("0", "0.0", "None") else "— no llenado —"
            color_val = text_color if mostrar != "— no llenado —" else self.get_subtext_color()

            # EXCEPCIÓN ÚNICA — "Descripción General": es el único campo que
            # alberga textos largos (unos 300 caracteres como mínimo), así que
            # es el único al que se le reserva alto para varias líneas. Si se
            # compactara como los demás, el texto se cortaría en una sola línea
            # y el usuario confirmaría un registro cuya descripción no puede
            # leer. El resto de las casillas son valores de una línea y no
            # necesitan ni un píxel extra.
            es_descripcion = key == "descripcion_general"
            filas_resumen.append(
                ft.Row([
                    ft.Text(f"{etiqueta}:", width=190, color=self.get_subtext_color(), size=12),
                    ft.Container(
                        content=ft.Text(
                            mostrar, color=color_val, size=12, weight=ft.FontWeight.W_600,
                            no_wrap=False,
                            max_lines=self._LINEAS_DESCRIPCION_RESUMEN if es_descripcion else 1,
                            overflow=ft.TextOverflow.ELLIPSIS,
                            selectable=True,
                        ),
                        expand=True,
                        height=self._ALTO_DESCRIPCION_RESUMEN if es_descripcion else None,
                    ),
                ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.START)
            )

        def _confirmar(ev):
            self._close_dialog(ev)
            self._ejecutar_guardado(ev, datos)

        def _editar(ev):
            self._close_dialog(ev)
            prod_actual = (
                obtener_producto(datos["codigo"], rol_usuario=self._rol_para_costos())
                if self._editing_codigo else None
            )
            self._mostrar_paso2_dialogo(ev, codigo=datos["codigo"], datos_iniciales=prod_actual or datos)

        def _cancelar_todo(ev):
            """Cancelar en el paso 3 descarta todo y vuelve al paso 1 (ERS 3.1 paso 5)."""
            self._cancelar_flujo_formulario(ev)

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.Icons.FACT_CHECK_OUTLINED, color=accent),
                ft.Text("¿ESTÁS SEGURO DE REGISTRAR EL SIGUIENTE ÍTEM?", color=text_color, size=15),
            ], spacing=10),
            content=ft.Container(
                # Sin `scroll` y sin `height` fija: el criterio de aceptación
                # del Cambio 3 es que TODA la información se vea en una sola
                # ventana sin deslizable, así que la ventana se ajusta al
                # resumen (filas de una línea + el bloque de descripción) en
                # vez de recortarlo a un alto fijo con barra.
                content=ft.Column(
                    controls=filas_resumen,
                    spacing=0,
                    tight=True,
                ),
                width=640,
                padding=8,
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
                # El servicio registra el par en el catálogo jerárquico
                # (`registrar_desde_producto`), así que guardar el producto es
                # el único punto de escritura del catálogo.
                sub_departamento=datos.get("sub_departamento", ""),
                marca=datos.get("marca", ""),
                precio_dolares=_to_float(datos.get("precio_dolares", 0)),
                precio_bcv=_to_float(datos.get("precio_bcv", 0)),
                proveedor_id=prov_id,
                existencia=_to_float(datos.get("existencia", 0)),
                codigo_barras=datos.get("codigo_barras", ""),
                nombre_referencia_corto=datos.get("nombre_referencia_corto", ""),
                alerta_stock_minimo=datos.get("alerta_stock_minimo") or None,
                # Los costos solo viajan si el formulario los recogió (rol
                # administrativo); `None` significa "no modificar", con lo que
                # un vendedor nunca pisa el costo ya almacenado.
                costo_usd_efectivo=datos.get("costo_usd_efectivo") or None,
                costo_usd_bcv=datos.get("costo_usd_bcv") or None,
                rol_usuario=self._rol_para_costos(),
            )

            if self._editing_codigo:
                actualizar_producto(**kwargs)
                self._snack(f"Producto '{datos['codigo']}' actualizado correctamente.", ft.Colors.GREEN_700, e)
            else:
                crear_producto(**kwargs)
                self._snack(f"Producto '{datos['codigo']}' registrado exitosamente.", ft.Colors.GREEN_700, e)

            self._resetear_estado_formulario()
            self._refrescar_tabla(e)
        except ValueError as ex:
            self._snack(str(ex), ft.Colors.RED_700, e)

    # ─── Eliminar Producto (exige la clave del usuario) ───────────────────────
    # Decisión del usuario del proyecto: borrar inventario es irreversible y la
    # sesión suele quedar abierta en un mostrador, así que CADA borrado pide la
    # clave de la cuenta con la que está abierta la sesión. El borrado por lote
    # la pide UNA SOLA VEZ para todo el lote: encadenar quince diálogos de clave
    # haría que el usuario termine tecleándola sin leer qué autoriza.
    def _paleta_dialogo(self) -> dict:
        return {
            "texto": self.get_text_color(),
            "subtexto": self.get_subtext_color(),
            "acento": self.get_accent_color(),
            "fondo": self.get_card_bg(),
            "borde": self.get_border_color(),
        }

    def _verificar_clave_sesion(self, clave: str) -> bool:
        """¿`clave` es la de la cuenta con la sesión abierta?

        Delega en `authenticate_user`, que la compara con
        `core.security.verify_password` contra el `password_hash` almacenado.
        Sin usuario en sesión devuelve False (fail-closed): es preferible no
        poder borrar a borrar sin autorización comprobable.
        """
        if not self.username or not clave:
            return False
        return authenticate_user(self.username, clave) is not None

    def _pedir_clave_para_borrar(self, codigos: list[str], mensaje: str, e=None):
        """Apila el diálogo de clave que autoriza el borrado de `codigos`."""
        comp = DialogoClave(
            titulo="Confirmar Eliminación",
            mensaje=mensaje,
            verificar_clave=self._verificar_clave_sesion,
            on_exito=lambda ev=None: self._eliminar_codigos(codigos, ev),
            on_cerrar=lambda ev=None: self._close_dialog(ev, dialog=comp.dialogo),
            paleta=self._paleta_dialogo(),
            etiqueta_confirmar="Eliminar",
            icono=ft.Icons.DELETE_FOREVER_ROUNDED,
        )
        self._open_dialog(comp.dialogo, e)
        return comp

    def _confirmar_eliminar(self, codigo: str, e=None):
        """Borrado de un ítem: enuncia su código y pide la clave."""
        return self._pedir_clave_para_borrar(
            [codigo],
            f"Se eliminará permanentemente el producto '{codigo}'. "
            "Esta acción no se puede deshacer.",
            e,
        )

    def _confirmar_eliminar_lote(self, e=None):
        """Borrado masivo: enuncia cuántos ítems y cuáles, y pide la clave una
        sola vez para todo el lote."""
        codigos = list(self._seleccion.seleccionados)
        if not codigos:
            self._snack("No hay ítems marcados para borrar.", ft.Colors.AMBER_700, e)
            return None
        # Se nombran los primeros códigos para que el usuario reconozca el lote
        # sin convertir el diálogo en una lista interminable.
        muestra = ", ".join(codigos[:8])
        resto = len(codigos) - 8
        if resto > 0:
            muestra += f" y {resto} más"
        plural = "ítems" if len(codigos) != 1 else "ítem"
        return self._pedir_clave_para_borrar(
            codigos,
            f"Se eliminarán permanentemente {len(codigos)} {plural} del inventario "
            f"({muestra}). Esta acción no se puede deshacer.",
            e,
        )

    def _eliminar_codigos(self, codigos: list[str], e=None) -> list[str]:
        """Ejecuta el borrado ya autorizado y deja la selección consistente.

        Los códigos borrados se descartan del modelo de selección: si quedaran
        marcados, una selección fantasma dejaría inertes los botones de todas
        las filas vivas.
        """
        borrados, fallidos = [], []
        for codigo in codigos:
            try:
                eliminar_producto(codigo)
                borrados.append(codigo)
            except ValueError:
                fallidos.append(codigo)

        self._seleccion.descartar(borrados)
        if self._seleccion.es_multiple and not self._seleccion.hay_seleccion:
            # Lote terminado: salir del modo devuelve la tabla a su
            # comportamiento normal sin que el usuario tenga que acordarse.
            self._seleccion.desactivar_modo_multiple()
        self._actualizar_barra_seleccion()

        if borrados:
            if len(borrados) == 1:
                self._snack(f"Producto '{borrados[0]}' eliminado.", ft.Colors.GREEN_700, e)
            else:
                self._snack(f"{len(borrados)} productos eliminados.", ft.Colors.GREEN_700, e)
        if fallidos:
            self._snack(
                f"No se pudo eliminar: {', '.join(fallidos)}.", ft.Colors.RED_700, e,
            )
        self._refrescar_tabla(e)
        return borrados
