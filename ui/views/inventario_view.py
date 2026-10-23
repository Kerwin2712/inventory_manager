import flet as ft
from ui.views.base_view import BaseView
from ui.components.multi_select_filter import MultiSelectFilter, RangeFilter
from ui.components.pila_dialogos import sincronizar_al_descartar
from ui.components.scroll_nav import build_inline_h_nav, build_floating_v_nav
from ui.components.selector_departamentos import SelectorDepartamentos
from ui.components.producto_detalle_modal import construir_modal_detalle_producto
from ui.components.seleccion_lista import SeleccionLista
from ui.components.teclado_nav import (
    ACCIONES_SOLO_ADMIN, ControlTeclado, etiqueta_atajo, tooltip_con_atajo,
)
from ui.components.dialogo_clave import DialogoClave
# Las dos preguntas que hay que hacerle al usuario cuando una acción tiene
# varios destinatarios posibles ("¿este o todos?" y "¿cuál de todos?") viven en
# un componente aparte porque Ventas y Deudas por Cobrar van a reutilizarlas:
# aquí solo se decide QUÉ acción pregunta qué y qué se hace con la respuesta.
from ui.components.dialogo_alcance import (
    ALCANCE_TODOS, DialogoAlcance, DialogoElegirItem, hace_falta_preguntar,
)
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
from services.printer_service import imprimir_reporte_inventario



def _repintar(pagina) -> None:
    """Fuerza un redibujado de la página, tolerando que no se pueda.

    Una página headless (las pruebas) o desmontada puede no aceptar `update()`;
    eso nunca debe tumbar la apertura o el cierre de un diálogo.
    """
    try:
        pagina.update()
    except (RuntimeError, AttributeError, AssertionError):
        pass


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

    # ── Etiquetas de los atajos sobre los íconos del ítem ────────────────────
    # El PDF pide que los nombres de los atajos estén visibles "para siempre
    # ser consciente de ellos", y un tooltip hay que ir a buscarlo con el
    # mouse: la tecla se dibuja TAMBIÉN sobre el ícono.
    #
    # Los seis íconos conviven en una celda estrecha (en la vista agrupada la
    # celda de acciones mide 250 px), así que la etiqueta no puede ocupar
    # espacio propio: va SUPERPUESTA en la esquina inferior derecha del mismo
    # cuadrado del ícono, dentro de un `Stack` del tamaño del botón. Así la
    # fila no crece ni a lo ancho ni a lo alto —al contrario, el cuadrado de
    # 34 px es más angosto que el botón de tamaño por omisión— y las dos
    # vistas con tabla siguen entrando sin tocar sus altos de fila.
    _LADO_BOTON_ACCION = 34
    _TAM_ICONO_ACCION = 20
    _TAM_ETIQUETA_ATAJO = 8

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

        # Nombres con los que los campos de cada diálogo quedaron anotados en
        # el registro de foco, para poder soltarlos al cerrarlo (ver
        # `_soltar_campos_de_dialogo`).
        self._campos_por_dialogo: dict[int, tuple[str, ...]] = {}

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

        # ── Atajos de teclado (segunda ola de octubre 2026) ─────────────────
        # Qué significa cada tecla (flechas, Ctrl+flecha, [Esc], F1..F6) vive
        # en `ui.components.teclado_nav`, compartido con las otras tres listas
        # de la aplicación; esta vista solo declara QUÉ desplazar y QUÉ
        # accionar. Los destinos de scroll se pasan como MÉTODOS y no como
        # controles porque la tabla se reconstruye en cada repintado: un
        # control guardado al instalar sería un control que ya no está en
        # pantalla, y la flecha desplazaría algo invisible.
        self._teclado = ControlTeclado(
            obtener_pagina=self._get_page,
            destino_vertical=self._destino_scroll_vertical,
            destino_horizontal=self._destino_scroll_horizontal,
            seleccion=self._seleccion,
            # F1..F6 actúan SOLO sobre el ítem marcado: el punto de entrada
            # recibe el nombre de la acción y resuelve el código él mismo, así
            # que la tecla no tiene que adivinar ninguna fila.
            ejecutar_accion=self._accionar_por_teclado,
            al_limpiar=self.limpiar_seleccion,
            # Identidad logica de la vista: el Dashboard la reemplaza en cada
            # repintado, asi que el control nuevo RELEVA al de la instancia
            # anterior en vez de encadenarse a el. Sin esto la cadena de
            # handlers crece sin tope y las instancias viejas siguen actuando
            # sobre controles que ya no estan en pantalla.
            identidad="inventario",
        )
        # ¿El cuerpo de esta vista salió de la pantalla? Ver
        # `_al_desmontar_cuerpo` y `_accionar_por_teclado`.
        self._cuerpo_desmontado = False

        # Índice de los productos de la página en pantalla, por código: permite
        # que las acciones por nombre (y los atajos F1..F6, que no tienen
        # ningún clic del cual sacar la fila) trabajen con un código, sin
        # depender del `dict` capturado en un clic.
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
        # Último recurso: el CUERPO de la vista. El Dashboard no monta esta
        # vista como vista de ruta —instancia la clase y se queda solo con lo
        # que devuelve `get_body()`—, y `View.page` es de solo lectura, así que
        # `self.page` no llega a tener valor ni con la pantalla viva. El cuerpo
        # sí está en el árbol de la página. Sin este recurso, los atajos de
        # teclado dependerían de que el usuario haga clic en algo primero.
        try:
            return getattr(self, "_body_scroll_col", None).page
        except (RuntimeError, AttributeError):
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

    # =========================================================================
    # REGISTRO DE FOCO DE LOS CAMPOS DE TEXTO
    # =========================================================================
    # Las flechas navegan SOLO cuando ningún campo de texto tiene el foco: con
    # el cursor dentro de un campo deben mover el cursor, como en cualquier
    # programa. Flet no expone un "¿quién tiene el foco?" global, así que cada
    # campo avisa al tomarlo y al soltarlo (`RegistroFoco.enlazar`). Un campo
    # sin enlazar no es un detalle estético: mientras el usuario escribe en él,
    # las flechas le mueven la pantalla, que es justo lo que la regla evita.
    #
    # Los campos de los DIÁLOGOS se enlazan recorriendo el diálogo al apilarlo
    # y no uno por uno: casi todos son variables locales de la función que los
    # construye —incluidos los de los filtros avanzados, que viven en
    # `ui/components/multi_select_filter.py`, y los del selector de
    # departamentos—, así que una lista escrita a mano se quedaría corta con el
    # próximo diálogo que se agregue, y el síntoma (la pantalla moviéndose al
    # escribir) no apunta al campo olvidado.

    # Atributos por los que se desciende buscando campos. `content`, `title` y
    # `label` pueden traer un texto plano en vez de un control, y de ahí no se
    # baja (`str` no tiene hijos).
    _ATRIBUTOS_CON_HIJOS = ("controls", "actions", "content", "title", "label")

    @classmethod
    def _campos_de_texto(cls, control, _vistos=None):
        """Recorre el árbol de `control` y entrega sus `ft.TextField`."""
        if _vistos is None:
            _vistos = set()
        if control is None or isinstance(control, str) or id(control) in _vistos:
            return
        _vistos.add(id(control))
        if isinstance(control, ft.TextField):
            yield control
        for attr in cls._ATRIBUTOS_CON_HIJOS:
            hijo = getattr(control, attr, None)
            if isinstance(hijo, (list, tuple)):
                for nieto in hijo:
                    yield from cls._campos_de_texto(nieto, _vistos)
            else:
                yield from cls._campos_de_texto(hijo, _vistos)

    def _enlazar_campos(self, control, etiqueta: str) -> tuple[str, ...]:
        """Anota en el registro de foco cada campo de texto de `control`.

        El nombre lleva `id()` porque dos campos pueden compartir etiqueta (dos
        diálogos con un "Mínimo" cada uno) y el registro distingue por nombre:
        con nombres repetidos, el `on_blur` de uno soltaría el foco del otro.
        """
        nombres = []
        for i, campo in enumerate(self._campos_de_texto(control)):
            nombre = f"{etiqueta}:{campo.label or i}:{id(campo):x}"
            self._teclado.foco.enlazar(campo, nombre)
            nombres.append(nombre)
        return tuple(nombres)

    def _enlazar_campos_de_dialogo(self, dialog) -> tuple[str, ...]:
        nombres = self._enlazar_campos(dialog, "dialogo")
        self._campos_por_dialogo[id(dialog)] = nombres
        return nombres

    def _soltar_campos_de_dialogo(self, dialog) -> None:
        """Olvida los campos de un diálogo que se cierra.

        Al cerrarse, el diálogo desaparece sin que sus campos lleguen a emitir
        `on_blur`: sin soltarlos a mano, el registro se queda creyendo que hay
        un campo con el foco y las flechas dejan de navegar PARA SIEMPRE, sin
        nada en pantalla que explique por qué.
        """
        for nombre in self._campos_por_dialogo.pop(id(dialog), ()):
            self._teclado.foco.soltar(nombre)

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
        self._soltar_campos_de_dialogo(dialog)

        p = self._get_page(e)
        if p is not None and hasattr(p, "pop_dialog"):
            # `pop_dialog()` cierra el diálogo más alto que siga abierto, así
            # que se llama ANTES de bajar la bandera: si se baja primero, el
            # que Flet encuentra como tope es el de ABAJO y se cierra el
            # equivocado (el aviso quedaba visible y el paso 1 desaparecía).
            p.pop_dialog()
            dialog.open = False
            # Mismo motivo que al abrir: Esc cierra desde el teclado y sin
            # repintado explícito el diálogo seguiría dibujado.
            _repintar(p)
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
        # Un diálogo que Flet descarte solo (tocando fuera, si no es modal)
        # dejaría un fantasma en esta pila y el siguiente cierre descartaría
        # el diálogo equivocado. Ver `ui/components/pila_dialogos.py`.
        sincronizar_al_descartar(dialog, self._dialog_stack)
        if dialog not in self._dialog_stack:
            self._dialog_stack.append(dialog)
        dialog.open = True
        # Mientras el cursor esté en un campo de este diálogo, las flechas son
        # del cursor y no de la lista de abajo.
        self._enlazar_campos_de_dialogo(dialog)

        p = self._get_page(e)
        if p is None:
            return
        if hasattr(p, "show_dialog"):
            try:
                p.show_dialog(dialog)
            except RuntimeError:
                pass  # ya estaba montado en la pila de la página
            # Repintado explícito. `show_dialog` apila el diálogo pero no
            # redibuja: tras un clic no se nota, porque Flet repinta al
            # terminar el handler del control, pero un atajo de teclado no
            # cuelga de ningún control. Sin esto, F1 abría el diálogo y la
            # pantalla no cambiaba hasta el siguiente clic en cualquier parte.
            _repintar(p)
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
        # El cuerpo es lo único de esta vista que llega al árbol de la página
        # (el Dashboard descarta la vista y se queda con su cuerpo), así que su
        # montaje es el primer instante en que hay teclado que tomar — y el
        # único que no depende de que el usuario haga clic antes: las flechas
        # tienen que navegar desde que la pantalla aparece. El gancho se pone
        # sobre la instancia porque el cuerpo es un `ft.Column` corriente y no
        # una subclase propia; Flet invoca `did_mount()` del objeto.
        self._body_scroll_col.did_mount = self._al_montar_cuerpo
        self._body_scroll_col.will_unmount = self._al_desmontar_cuerpo
        return self._body_scroll_col

    def _al_montar_cuerpo(self):
        """`did_mount` del cuerpo: con la pantalla viva se toma el teclado."""
        self._cuerpo_desmontado = False
        self._teclado.instalar()

    def _al_desmontar_cuerpo(self):
        """`will_unmount` del cuerpo: devolver el teclado al handler anterior.

        El Dashboard cambia de sección RECONSTRUYENDO su cuerpo, así que esta
        vista sale de la pantalla sin que nadie la cierre y sin que su estado
        se descarte: el ítem que quedó marcado sigue marcado. Si el teclado
        siguiera enganchado, una F2 pulsada mientras el usuario mira Ventas la
        procesaría esta vista y mandaría a cobrar un producto que el usuario ya
        no tiene delante — y esa sí es una acción con efecto real, porque sale
        de la vista por el callback del Dashboard.
        """
        self._cuerpo_desmontado = True
        self._teclado.desinstalar()

    # ─────────────────────────────────────────────────────────────────────────
    # DESTINOS DE SCROLL DE LAS FLECHAS
    # ─────────────────────────────────────────────────────────────────────────
    # Las flechas deben hacer EXACTAMENTE lo que hacen los botones de flecha de
    # la pantalla (`ui.components.scroll_nav`), así que apuntan a los mismos
    # controles: el cuerpo de la página para el eje vertical y la Row de la
    # tabla para el horizontal (un solo dueño por eje, ver `get_body`).
    # Son métodos y no atributos para que el control se resuelva EN LA
    # PULSACIÓN: entre dos pulsaciones puede haber un repintado que sustituya
    # la tabla, y un control viejo ya no está en pantalla.
    def _destino_scroll_vertical(self):
        """Mismo destino que el cluster flotante ↑/↓ (`self._nav_v`)."""
        return (
            getattr(self, "_body_scroll_col", None)
            or getattr(self, "_tabla_scroll_col", None)
        )

    def _destino_scroll_horizontal(self):
        """Mismo destino que el cluster ←/→ de la barra (`self._nav_h`)."""
        return getattr(self, "_tabla_scroll_row", None)

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

        # Enlazado al registro de foco: escribir una tasa no debe desplazar la
        # lista de abajo (ver "REGISTRO DE FOCO DE LOS CAMPOS DE TEXTO").
        self._inp_nueva_tasa = self._teclado.foco.enlazar(
            ft.TextField(
                label="Nueva tasa (Bs/$)",
                hint_text="Ej: 50.35",
                width=180,
                keyboard_type=ft.KeyboardType.NUMBER,
                color=text_color,
                border_color=border,
                focused_border_color=accent,
                border_radius=12,
                on_submit=self._handle_actualizar_tasa,
            ),
            "tasa_bcv",
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
        # El buscador es EL campo donde más tiempo está el cursor en esta
        # pantalla: sin enlazarlo al registro de foco, corregir un término de
        # búsqueda le desplazaría la lista al usuario mientras escribe.
        self._f_busqueda = self._teclado.foco.enlazar(
            ft.TextField(
                label="Buscar código, referencia, descripción, marca...",
                hint_text="Escriba cualquier término y los resultados se filtran al instante",
                expand=True,
                color=text_color, border_color=border, focused_border_color=accent,
                border_radius=12, prefix_icon=ft.Icons.SEARCH,
                on_change=self._handle_filtro_change,
            ),
            "busqueda",
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
        """Clic en cualquier parte de la fila: marca (nunca desmarca).

        Reintenta `instalar()` (es idempotente) porque la página puede haber
        llegado después de `get_body()`: una vista construida headless y
        montada más tarde se quedaría sin teclado para siempre, y [Esc] es
        justamente la tecla que hace falta en cuanto hay algo marcado.
        """
        self._teclado.instalar(e)
        self._seleccion.seleccionar(codigo)

    def alternar_item(self, codigo: str, e=None):
        """Clic DENTRO de la casilla marcadora: marca o desmarca."""
        self._teclado.instalar(e)
        self._seleccion.alternar(codigo)

    def limpiar_seleccion(self, e=None):
        """Quita la selección (tecla [Esc] o botón de la barra)."""
        self._seleccion.limpiar()
        self._actualizar_barra_seleccion()
        self._safe_update(e)

    def alternar_modo_seleccion(self, e=None):
        """Entra o sale del modo de selección múltiple (borrado por lote)."""
        self._teclado.instalar(e)
        self._seleccion.alternar_modo()
        self._actualizar_barra_seleccion()
        self._cargar_filas()
        self._safe_update(e)

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
        # Botón CON ETIQUETA, no un ícono suelto. Verificando en la aplicación
        # real, el usuario no encontró la selección múltiple: un ícono gris sin
        # texto, pegado a la leyenda "Sin selección", se lee como un indicador
        # de estado y no como algo que se pueda pulsar. Una función que existe
        # pero nadie descubre es una función que no existe.
        self._btn_modo_seleccion = ft.Button(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.CHECKLIST_ROUNDED, size=16),
                    ft.Text("Selección múltiple", size=11, weight=ft.FontWeight.W_600),
                ],
                spacing=6, tight=True,
            ),
            style=ft.ButtonStyle(
                bgcolor=ft.Colors.TRANSPARENT,
                color=subtext,
                shape=ft.RoundedRectangleBorder(radius=12),
                side=ft.BorderSide(1, subtext),
                padding=ft.Padding.symmetric(horizontal=10, vertical=4),
            ),
            tooltip="Marcar varios ítems a la vez para borrarlos juntos",
            on_click=self.alternar_modo_seleccion,
        )
        self._btn_limpiar_seleccion = ft.IconButton(
            ft.Icons.HIGHLIGHT_OFF_ROUNDED,
            icon_color=subtext,
            tooltip="Quitar la selección (equivale a pulsar Esc)",
            visible=False,
            on_click=self.limpiar_seleccion,
        )
        # NO hay botón "Borrar marcados" en la barra. Lo pidió el usuario del
        # proyecto —"podemos quitar el botón que se ve arriba de eliminar de
        # forma masiva, porque ya tenemos el atajo de F6 para eliminar"— y el
        # camino del mouse no se pierde: el ícono de la papelera de cualquier
        # fila marcada, con varias marcadas, pregunta por `DialogoAlcance` y
        # permite elegir "los N marcados". Un botón dedicado además duplicaba
        # el borrado del lote en dos sitios con reglas propias, que es como se
        # desincronizan.
        self._barra_seleccion = ft.Row(
            controls=[
                self._btn_modo_seleccion,
                self._lbl_seleccion,
                self._btn_limpiar_seleccion,
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
        # El botón dice en qué modo está y qué hace el próximo clic, en vez de
        # limitarse a cambiar de color: un botón que solo se tiñe deja al
        # usuario adivinando si ya lo pulsó.
        color_modo = accent if multiple else subtext
        self._btn_modo_seleccion.content = ft.Row(
            [
                ft.Icon(
                    ft.Icons.CHECKLIST_RTL_ROUNDED if multiple else ft.Icons.CHECKLIST_ROUNDED,
                    size=16,
                ),
                ft.Text(
                    "Salir de selección múltiple" if multiple else "Selección múltiple",
                    size=11, weight=ft.FontWeight.W_600,
                ),
            ],
            spacing=6, tight=True,
        )
        self._btn_modo_seleccion.style = ft.ButtonStyle(
            bgcolor=ft.Colors.with_opacity(0.14, accent) if multiple else ft.Colors.TRANSPARENT,
            color=color_modo,
            shape=ft.RoundedRectangleBorder(radius=12),
            side=ft.BorderSide(1, color_modo),
            padding=ft.Padding.symmetric(horizontal=10, vertical=4),
        )
        self._btn_modo_seleccion.tooltip = (
            "Volver a marcar un solo ítem"
            if multiple
            else "Marcar varios ítems a la vez para borrarlos juntos"
        )
        self._btn_limpiar_seleccion.visible = self._seleccion.hay_seleccion

    # ─────────────────────────────────────────────────────────────────────────
    # ACCIONES DE UN ÍTEM (los seis botones de la fila)
    # ─────────────────────────────────────────────────────────────────────────
    # Cada botón entra por aquí, con un nombre estable y un solo argumento (el
    # código del ítem): así los atajos F1..F6 se enlazan al ítem marcado sin
    # tener que alcanzar closures anónimas enterradas en `_cargar_filas`.
    #
    # El orden es el de `teclado_nav.ATAJOS_ITEM` (F1 info … F6 borrar) y es el
    # mismo en que se dibujan los botones de la fila: la tecla y la posición
    # del ícono cuentan la misma historia.
    ACCIONES_ITEM = ("info", "cobrar", "carrito", "historial", "editar", "borrar")

    # ── Qué significa cada acción cuando hay VARIOS ítems marcados ───────────
    # Pedido del usuario del proyecto: "que las acciones afecten a todos los
    # ítems que tengo seleccionados". Pero no todas admiten lo mismo, y la
    # diferencia no es cosmética:
    #
    #   - Las de LOTE se aplican a todo lo marcado, porque sumar quince
    #     artículos al carrito o borrar quince códigos son operaciones que
    #     siguen significando algo con quince ítems.
    #   - Las de UNO no: "ver el detalle" de cinco productos a la vez no
    #     significa nada, y editarlos juntos tampoco. Con varios marcados se
    #     muestra la lista de lo marcado para elegir cuál, en vez de mandar al
    #     usuario a desmarcar catorce filas y volver ("como hay varios ítems,
    #     debería mostrarme una lista o solicitarme de cuál ítem quiero ver").
    #
    # Las dos tuplas tienen que cubrir `ACCIONES_ITEM` entre ambas; si alguien
    # añade una séptima acción sin clasificarla, `_ejecutar_accion_en_lote`
    # falla ruidosamente en vez de hacer algo arbitrario con ella.
    ACCIONES_DE_UNO = ("info", "historial", "editar")
    ACCIONES_EN_LOTE = ("cobrar", "carrito", "borrar")

    # Cómo se nombra cada acción en los diálogos que preguntan. Van en las
    # palabras del usuario ("Añadir al carrito") y no en los nombres internos,
    # porque la pregunta quedaría abstracta justo cuando lo que se decide es
    # sobre qué ítems se va a actuar. Los dos diálogos las usan en minúscula
    # dentro de una frase, así que la etiqueta tiene que leerse bien ahí
    # ("¿Sobre cuáles quiere añadir al carrito?").
    ETIQUETAS_ACCION = {
        "info": "Ver el detalle",
        "cobrar": "Procesar la venta",
        "carrito": "Añadir al carrito",
        "historial": "Ver el historial clínico",
        "editar": "Editar",
        "borrar": "Eliminar",
    }

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

    def _handler_de_accion(self, accion: str):
        """Resuelve el handler de una acción, o falla si el nombre no existe.

        Falla RUIDOSAMENTE (y no devolviendo `None`) porque un nombre mal
        escrito en un cableado nuevo se vería como un botón que no hace nada, y
        eso es lo más difícil de encontrar.
        """
        handler = self._handlers_accion().get(accion)
        if handler is None:
            raise ValueError(f"Acción de ítem desconocida: {accion!r}")
        return handler

    def _accion_autorizada(self, accion: str) -> bool:
        """¿El rol de la sesión puede ejecutar esta acción?

        El mapeo de teclas es FIJO para todos los roles (decisión del usuario
        del proyecto): para un vendedor, F4 simplemente no hace nada. Se
        rechaza EN SILENCIO y no con un aviso, porque un error sobre una tecla
        que ese rol nunca va a poder usar solo confunde; el ícono tampoco se
        dibuja en su fila.
        """
        return not (accion in ACCIONES_SOLO_ADMIN and not self.es_admin)

    def ejecutar_accion_item(self, accion: str, codigo: str, e=None) -> bool:
        """Punto de entrada único de los seis botones y de los atajos F1..F6.

        Este es el camino del ÍCONO, donde el clic señala UNA fila concreta. Si
        hay varias marcadas, esa fila y el lote son dos destinatarios posibles
        y la ambigüedad es real, así que se PREGUNTA siempre: "si se usa el
        ícono y hay varios seleccionados, debe preguntar si solamente al que se
        le está haciendo clic o a todos los que están seleccionados". La
        respuesta NO se recuerda para el clic siguiente: la intención cambia de
        un clic al otro, y recordarla sería decidir por el usuario.

        Vuelve a comprobar `puede_accionar` aunque el botón ya venga
        deshabilitado: la regla tiene que valer también para quien invoque la
        acción por teclado o por código, no solo para quien hace clic.
        """
        handler = self._handler_de_accion(accion)
        if not self._accion_autorizada(accion):
            return False

        marcados = list(self._seleccion.seleccionados)
        # `hace_falta_preguntar` centraliza el criterio (más de uno marcado);
        # que el código esté entre los marcados es lo que hace de la pregunta
        # una disyuntiva: sobre una fila ajena al lote no hay nada que elegir
        # —y de hecho `puede_accionar` la rechaza unas líneas más abajo—.
        if hace_falta_preguntar(marcados) and codigo in marcados:
            self._preguntar_alcance(accion, codigo, marcados, e)
            return True

        if not self._seleccion.puede_accionar(codigo):
            self._snack(
                "Hay otro ítem marcado. Haga clic en su casilla o pulse Esc para liberarlo.",
                ft.Colors.AMBER_700, e,
            )
            return False
        handler(codigo, e)
        return True

    def ejecutar_accion_sobre_seleccionado(self, accion: str, e=None) -> bool:
        """Misma acción, aplicada a lo marcado: es lo que invocan F1..F6.

        Este es el camino de la TECLA, y se diferencia del ícono en una cosa:
        no hay ninguna fila señalada, así que no hay nada que preguntar sobre
        el alcance. La tecla actúa sobre TODO lo marcado, que es lo que el
        usuario pidió ("si yo tengo selección múltiple activado y selecciono
        varios elementos y uso el atajo, por ejemplo F2 para ir a las ventas,
        debería llevarme todas las ventas"). Con cero o un ítem marcado entra
        por el camino del ícono y todo sigue exactamente como antes.

        Sin ítem marcado no hace NADA (devuelve False): adivinar una fila
        sería disparar una acción —incluido un borrado— sobre algo que el
        usuario no eligió. F6 sigue pasando por el diálogo de clave como el
        botón de la fila, venga de la tecla o del clic, y en lote la pide una
        sola vez (ver `_ejecutar_accion_en_lote`).
        """
        marcados = list(self._seleccion.seleccionados)
        if not marcados:
            return False
        # Se valida el nombre aunque el despacho pueda no usar el handler
        # directamente: una tecla cableada a una acción inexistente tiene que
        # romper aquí y no más adentro.
        self._handler_de_accion(accion)
        if not self._accion_autorizada(accion):
            return False
        if hace_falta_preguntar(marcados):
            return self._ejecutar_accion_en_lote(accion, marcados, e)
        return self.ejecutar_accion_item(accion, marcados[0], e)

    # ─────────────────────────────────────────────────────────────────────────
    # DESPACHO POR ALCANCE: sobre qué ítems actúa cada acción
    # ─────────────────────────────────────────────────────────────────────────
    def _ejecutar_accion_en_lote(self, accion: str, marcados: list[str], e=None) -> bool:
        """Aplica una acción a TODO lo marcado, cada una a su manera.

        Es el punto donde la tabla de comportamiento se vuelve código, y está
        en UN SOLO sitio a propósito: la tecla y la respuesta "los N marcados"
        del `DialogoAlcance` desembocan las dos aquí, así que el mouse y el
        teclado no pueden divergir.
        """
        self._handler_de_accion(accion)
        if accion in self.ACCIONES_DE_UNO:
            # No tiene sentido en lote: se elige uno de entre los marcados.
            self._preguntar_cual_item(accion, marcados, e)
            return True
        if accion == "borrar":
            # La clave del usuario, UNA SOLA VEZ para todo el lote: encadenar
            # quince diálogos de clave haría que la teclee sin leer qué
            # autoriza.
            self._confirmar_eliminar_lote(e, codigos=marcados)
            return True
        if accion in ("cobrar", "carrito"):
            # Las dos añaden el lote al carrito que el usuario elija; solo
            # "cobrar" (F2, "Procesar Venta") sale además hacia Ventas.
            self._abrir_modal_destino_carrito_lote(
                marcados, ir_a_ventas=(accion == "cobrar"), e=e,
            )
            return True
        raise ValueError(f"Acción sin comportamiento de lote definido: {accion!r}")

    def _preguntar_alcance(self, accion: str, codigo: str, marcados: list[str], e=None):
        """"¿Este o todos?" sobre el ícono de una fila con varias marcadas."""
        etiqueta = self.ETIQUETAS_ACCION.get(accion, accion)

        comp = DialogoAlcance(
            titulo=etiqueta,
            accion=etiqueta,
            codigo=codigo,
            marcados=marcados,
            # El evento del clic si llega (trae consigo la página), y si no, el
            # que abrió esta pregunta: sin ese respaldo, el diálogo que apila
            # la acción no encontraría página donde mostrarse y la respuesta
            # del usuario se perdería en silencio.
            on_elegir=lambda alcance, ev=None: self._al_elegir_alcance(
                accion, codigo, marcados, alcance, ev if ev is not None else e,
            ),
            on_cerrar=lambda ev=None: self._close_dialog(
                ev if ev is not None else e, dialog=comp.dialogo,
            ),
            paleta=self._paleta_dialogo(),
        )
        self._open_dialog(comp.dialogo, e)
        return comp

    def _al_elegir_alcance(
        self, accion: str, codigo: str, marcados: list[str], alcance: str, e=None,
    ) -> bool:
        """Enruta la respuesta del `DialogoAlcance`.

        El `DialogoAlcance` ya se cerró antes de llamar aquí (lo hace él
        mismo), así que el diálogo que apile la acción queda ARRIBA y no debajo
        de uno muerto que el usuario seguiría viendo sin poder usar. Cancelar
        no llega hasta aquí: no se actúa sobre nada.
        """
        if alcance == ALCANCE_TODOS:
            return self._ejecutar_accion_en_lote(accion, marcados, e)
        # "Solo este": se ejecuta directo y no se vuelve a preguntar. Volver a
        # entrar por `ejecutar_accion_item` reabriría el mismo diálogo en
        # bucle, porque la selección múltiple sigue en pie.
        self._handler_de_accion(accion)(codigo, e)
        return True

    def _preguntar_cual_item(self, accion: str, marcados: list[str], e=None):
        """"¿Cuál de todos?" para las acciones que no tienen sentido en lote."""
        etiqueta = self.ETIQUETAS_ACCION.get(accion, accion)

        comp = DialogoElegirItem(
            titulo=etiqueta,
            accion=etiqueta,
            marcados=marcados,
            # La descripción corta y no solo el código: en una lista de la que
            # hay que ELEGIR, "PRD-0012" no le dice nada a quien atiende el
            # mostrador.
            etiquetas=self._etiquetas_de_items(marcados),
            on_elegir=lambda cod, ev=None: self._handler_de_accion(accion)(
                cod, ev if ev is not None else e,
            ),
            on_cerrar=lambda ev=None: self._close_dialog(
                ev if ev is not None else e, dialog=comp.dialogo,
            ),
            paleta=self._paleta_dialogo(),
        )
        self._open_dialog(comp.dialogo, e)
        return comp

    def _accionar_por_teclado(self, accion: str, e=None) -> bool:
        """Lo que invocan F1..F6, con una guarda de más.

        `_al_desmontar_cuerpo` devuelve el teclado al salir de la pantalla,
        pero esa devolución depende de que `will_unmount` llegue y de que el
        handler siga siendo el de esta vista (otra vista pudo instalarse
        encima en el medio, y entonces la cadena nos sigue entregando las
        teclas). La bandera no depende de nada de eso: una vista que ya no
        está en pantalla no acciona ítems, y punto.
        """
        if self._cuerpo_desmontado:
            return False
        return self.ejecutar_accion_sobre_seleccionado(accion, e)

    def _build_tabla_panel(self, accent, card_bg, text_color, subtext, border) -> ft.Control:
        self._dt = ft.DataTable(
            columns=[self._build_columna_header(k, accent, text_color) for k in self._columnas_orden_visible()],
            rows=[],
            # Explícito aunque sea el valor por omisión: todas las filas llevan
            # `on_select_change` (clic en cualquier parte de la fila), y con la
            # columna de casillas propia de la tabla activada se dibujaría una
            # SEGUNDA casilla junto a nuestro marcador.
            show_checkbox_column=False,
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

        _imprimiendo_inv = False
        def _on_imprimir_inventario(ev):
            nonlocal _imprimiendo_inv
            if _imprimiendo_inv:
                return
            _imprimiendo_inv = True
            p = self.get_current_page(ev)
            btn_imprimir_inv.disabled = True
            btn_imprimir_inv.tooltip = "Enviando a la impresora..."
            try:
                btn_imprimir_inv.update()
            except Exception:
                pass
            _repintar(p)

            def _tarea():
                nonlocal _imprimiendo_inv
                try:
                    prods_imprimir = None
                    codigos_sel = self._seleccion.seleccionados
                    if codigos_sel:
                        prods_imprimir = [
                            self._productos_en_pantalla[c]
                            for c in codigos_sel
                            if c in self._productos_en_pantalla
                        ]
                    ok, msg = imprimir_reporte_inventario(
                        productos=prods_imprimir,
                        limite=100
                    )
                    if ok:
                        self.show_alert_success(ev, "¡Catálogo de inventario enviado a la impresora térmica!")
                    else:
                        self.show_alert_error(ev, f"Error al imprimir inventario: {msg}")
                except Exception as ex:
                    self.show_alert_error(ev, f"Error al imprimir inventario: {ex}")
                finally:
                    _imprimiendo_inv = False
                    btn_imprimir_inv.disabled = False
                    btn_imprimir_inv.tooltip = "Imprimir catálogo en térmica (80mm)"
                    try:
                        btn_imprimir_inv.update()
                    except Exception:
                        pass
                    _repintar(p)

            import threading
            threading.Thread(target=_tarea, daemon=True).start()

        btn_imprimir_inv = ft.IconButton(
            icon=ft.Icons.PRINT_ROUNDED,
            icon_color=accent,
            tooltip="Imprimir catálogo en térmica (80mm)",
            on_click=_on_imprimir_inventario,
        )

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
                                btn_imprimir_inv,
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
        # y los atajos F1..F6 reciben un código y resuelven el producto aquí,
        # sin depender del `dict` de un clic (una tecla no tiene ninguno).
        self._productos_en_pantalla = {p["codigo"]: p for p in todos}

        # Selector de columnas visible solo en modo separado
        if hasattr(self, "_btn_columnas"):
            self._btn_columnas.visible = (self._modo_vista == "separado")

        def _boton_accion(accion: str, codigo: str, icono, color, tooltip: str, size=None):
            """Botón de la fila cableado a `ejecutar_accion_item`, con la tecla
            que lo acciona dibujada encima.

            `disabled` es la mitad visible de la regla del marcador: con otro
            ítem seleccionado, el botón se ve apagado en vez de aceptar el clic
            y no hacer nada (un botón que ignora en silencio se lee como un
            cuelgue de la aplicación).
            """
            habilitado = self._seleccion.puede_accionar(codigo)
            # El tooltip también lleva el atajo ("Editar (F5)"): sirve para
            # confirmarlo, no para descubrirlo.
            descripcion = tooltip_con_atajo(tooltip, accion)
            boton = ft.IconButton(
                icono,
                icon_color=color,
                icon_size=size or self._TAM_ICONO_ACCION,
                tooltip=descripcion if habilitado else f"{descripcion} (hay otro ítem marcado)",
                disabled=not habilitado,
                width=self._LADO_BOTON_ACCION,
                height=self._LADO_BOTON_ACCION,
                style=ft.ButtonStyle(padding=0),
                on_click=lambda ev, a=accion, c=codigo: self.ejecutar_accion_item(a, c, ev),
            )
            etiqueta = etiqueta_atajo(accion)
            if not etiqueta:
                return boton

            color_etiqueta = color if habilitado else subtext
            insignia = ft.Container(
                content=ft.Text(
                    etiqueta,
                    size=self._TAM_ETIQUETA_ATAJO,
                    weight=ft.FontWeight.BOLD,
                    color=color_etiqueta,
                    no_wrap=True,
                ),
                # Fondo OPACO (el de la tarjeta) más borde y texto del color
                # del ícono: así la tecla se lee sobre el dibujo del ícono y en
                # los dos temas, sin tener que elegir un color de texto por
                # tema. Un fondo translúcido dejaba el ícono asomando por
                # detrás de la "F6" justo en los íconos más densos.
                bgcolor=card_bg,
                border=ft.Border.all(1, color_etiqueta),
                border_radius=4,
                padding=ft.Padding.symmetric(horizontal=2),
                right=0,
                bottom=0,
            )
            return ft.Stack(
                controls=[boton, insignia],
                width=self._LADO_BOTON_ACCION,
                height=self._LADO_BOTON_ACCION,
            )

        def botones_accion(p, size=None) -> list[ft.Control]:
            """Los seis botones del ítem, en el orden de F1 a F6: la posición
            del ícono y la tecla que lo acciona cuentan la misma historia."""
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

    def _ir_a_ventas(self, e=None) -> bool:
        """Lleva la pantalla a Ventas SIN tocar ningún carrito.

        El Flujo Directo de un ítem sale por `on_procesar_venta`, pero ese
        callback del Dashboard (`procesar_venta_desde_inventario`) crea un
        carrito nuevo y mete el producto él mismo: para un lote que ya se
        añadió al carrito que el usuario eligió, volvería a crear uno y a
        duplicar el renglón, tirando por tierra justo la pregunta que el
        usuario pidió que se le hiciera. Así que el lote navega por el mismo
        camino que el enlace "IR A VENTAS" del aviso de un ítem: la vista de
        ruta de arriba cambia de sección, o en su defecto se va a la ruta.

        Devuelve False si no hay por dónde navegar (vista construida fuera del
        Dashboard), para que quien llame pueda avisar en vez de dejar al
        usuario esperando una pantalla que no va a llegar.
        """
        p = self._get_page(e)
        if p is None:
            return False
        vistas = getattr(p, "views", None) or []
        top_view = vistas[-1] if vistas else None
        if hasattr(top_view, "handle_nav_change"):
            top_view.handle_nav_change("Ventas")
            return True
        if hasattr(p, "go"):
            p.go("/ventas")
            return True
        return False

    @staticmethod
    def _etiqueta_carrito(cinfo: dict) -> str:
        """Cómo se nombra un carrito en un desplegable de destino.

        Lleva el nombre, a quién atiende y cuántos renglones acumula: sin el
        conteo, dos carritos del mismo cliente se leen idénticos y elegir
        destino se vuelve una lotería.
        """
        cliente = cinfo.get("cliente")
        n_items = len(cinfo.get("items", []))
        quien = cliente["nombre"] if cliente else "Sin cliente"
        return f"{cinfo['nombre']} — {quien} ({n_items} ítem{'s' if n_items != 1 else ''})"

    def _etiquetas_de_items(self, codigos) -> dict:
        """Descripción corta de cada código, para las listas de los diálogos.

        Un código solo ("PRD-0012") no le dice nada a quien atiende el
        mostrador: en una lista de la que hay que ELEGIR, el nombre del
        producto es lo único que permite elegir sin equivocarse.
        """
        etiquetas = {}
        for codigo in codigos or []:
            prod = self._producto_en_pantalla(codigo) or {}
            etiquetas[codigo] = (
                prod.get("nombre_referencia_corto")
                or prod.get("descripcion_general")
                or prod.get("referencia")
                or codigo
            )
        return etiquetas

    # ── Añadir VARIOS ítems al carrito (F2 y F3 en lote) ─────────────────────
    # Clave del desplegable que significa "hacer un carrito nuevo"; misma
    # convención que el modal de un solo ítem.
    _NUEVO_CARRITO = "__nuevo__"

    # Cantidad con la que entra cada ítem del lote. Es 1 por la misma razón que
    # el Flujo Directo de un ítem (`_procesar_venta_directo` también carga 1):
    # pedir quince cantidades en un diálogo convierte "añadir lo que marqué" en
    # un formulario, y cada renglón se ajusta después en Ventas, que es donde
    # el usuario va a cerrar la venta de todas formas.
    _CANTIDAD_POR_ITEM_DEL_LOTE = 1.0

    def _abrir_modal_destino_carrito_lote(self, codigos, ir_a_ventas: bool, e=None):
        """Pregunta a QUÉ carrito va el lote ANTES de tocar nada.

        Corrección expresa del usuario del proyecto: "a veces puede que se
        agreguen los artículos y no se quiera agregar al carrito que está ahí,
        sino que se quiera agregar a uno nuevo o a otro. Entonces debes
        preguntar". Así que F2 y F3 en lote no escriben en el carrito activo
        por omisión, aunque sea el destino más probable.

        El desplegable es el mismo mecanismo del modal de un ítem (el activo,
        otro de los abiertos, o uno nuevo) pero SIN el panel de cliente: un
        lote de quince artículos no es el momento de buscar o crear al
        cliente, y el carrito recién hecho se vincula en Ventas, que es donde
        el usuario va a terminar.
        """
        from services.cart_manager import (
            obtener_id_carrito_activo, obtener_todos_los_carritos,
        )

        codigos = [c for c in (codigos or []) if c]
        if not codigos:
            return None

        sid = self.get_session_id(e)
        carritos = obtener_todos_los_carritos(sid)
        activo = obtener_id_carrito_activo(sid)

        dd_destino = ft.Dropdown(
            label="Enviar a Carrito",
            # Arranca en el activo porque es el destino más probable, pero la
            # decisión no se da por hecha: este diálogo no se salta nunca.
            value=activo,
            options=(
                [ft.dropdown.Option(self._NUEVO_CARRITO, "➕ Crear nuevo carrito")]
                + [
                    ft.dropdown.Option(
                        cid,
                        self._etiqueta_carrito(cinfo)
                        + (" · activo" if cid == activo else ""),
                    )
                    for cid, cinfo in carritos.items()
                ]
            ),
            border_radius=12,
        )

        etiquetas = self._etiquetas_de_items(codigos)
        resumen = ft.Column(
            [
                ft.Text(
                    f"{etiquetas[c]} ({c})",
                    size=12, color=self.get_subtext_color(), no_wrap=False,
                )
                for c in codigos
            ],
            spacing=2,
            tight=True,
            # Lote largo: la lista es la dueña de su propio eje vertical, para
            # que el diálogo no crezca sin fin (un solo dueño por eje).
            scroll=ft.ScrollMode.AUTO,
            height=min(160, 22 * max(1, len(codigos))),
        )

        def confirmar(ev=None):
            # Se CIERRA antes de ejecutar: los avisos del resultado se apilan
            # encima, y un diálogo muerto debajo dejaría al usuario mirando
            # botones que ya no responden (ver `dialogo_alcance`).
            self._close_dialog(ev if ev is not None else e, dialog=dlg)
            self._agregar_lote_a_carrito(
                codigos, dd_destino.value, ir_a_ventas,
                ev if ev is not None else e,
            )

        def cancelar(ev=None):
            self._close_dialog(ev if ev is not None else e, dialog=dlg)

        nombre_accion = "Procesar Venta" if ir_a_ventas else "Añadir al Carrito"
        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(
                    ft.Icons.POINT_OF_SALE if ir_a_ventas else ft.Icons.ADD_SHOPPING_CART,
                    color=ft.Colors.BLUE_400 if ir_a_ventas else ft.Colors.GREEN_400,
                ),
                ft.Text(
                    f"{nombre_accion} — {len(codigos)} ítems",
                    weight=ft.FontWeight.BOLD, color=self.get_text_color(),
                ),
            ], spacing=10),
            content=ft.Column([
                ft.Text(
                    "¿A qué carrito van los ítems marcados? Puede sumarlos al "
                    "carrito que ya está abierto, a otro de los abiertos, o "
                    "empezar uno nuevo.",
                    size=13, color=self.get_text_color(), no_wrap=False,
                ),
                dd_destino,
                ft.Divider(height=6),
                ft.Text(
                    "Se añadirá 1 unidad de cada uno:",
                    size=12, weight=ft.FontWeight.W_600, color=self.get_text_color(),
                ),
                resumen,
            ], spacing=10, tight=True, width=440),
            actions=[
                ft.TextButton("Cancelar", on_click=cancelar),
                ft.Button(
                    content=ft.Text(nombre_accion, weight=ft.FontWeight.BOLD),
                    style=ft.ButtonStyle(
                        bgcolor=ft.Colors.GREEN_700, color=ft.Colors.WHITE,
                        shape=ft.RoundedRectangleBorder(radius=12),
                    ),
                    on_click=confirmar,
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            bgcolor=self.get_card_bg(),
            # Detrás de este diálogo no hay una clase componente (como sí la
            # hay en `dialogo_alcance`), así que los controles por los que la
            # vista y las pruebas lo alcanzan viajan en `data`, siguiendo el
            # mismo convenio.
            data={
                "destino": dd_destino,
                "codigos": tuple(codigos),
                "ir_a_ventas": ir_a_ventas,
                "confirmar": confirmar,
                "cancelar": cancelar,
            },
        )
        self._open_dialog(dlg, e)
        return dlg

    def _agregar_lote_a_carrito(
        self, codigos, destino: str, ir_a_ventas: bool, e=None,
    ) -> list[str]:
        """Añade el lote al carrito elegido y avisa de lo que quedó fuera.

        EXISTENCIA INSUFICIENTE — decisión documentada: se añaden LOS QUE SE
        PUEDA y se avisa de los que no, en vez de rechazar el lote entero.
        Rechazarlo obligaría al usuario a adivinar cuál de los quince códigos
        es el culpable, desmarcarlo y volver a empezar; y lo que quería —cobrar
        los catorce que sí hay— es justo lo que no conseguiría. El aviso nombra
        los que quedaron fuera para que la omisión no pase desapercibida: una
        omisión silenciosa en una venta se descubre en la caja.
        """
        from services.cart_manager import (
            agregar_o_actualizar_producto, cambiar_carrito_activo,
            crear_nuevo_carrito, obtener_carrito_activo,
            obtener_todos_los_carritos,
        )

        cantidad = self._CANTIDAD_POR_ITEM_DEL_LOTE
        aptos, omitidos = [], []
        for codigo in codigos or []:
            prod = self._producto_en_pantalla(codigo)
            # Un código sin producto (otro camino lo borró entre el marcado y
            # la confirmación) cuenta como omitido, no como error del lote.
            if not prod or float(prod.get("existencia", 0) or 0) < cantidad:
                omitidos.append(codigo)
                continue
            aptos.append(prod)

        if not aptos:
            self._snack(
                "Ninguno de los ítems marcados tiene existencia disponible: "
                "no se añadió nada al carrito.",
                ft.Colors.RED_700, e,
            )
            return []

        sid = self.get_session_id(e)
        if destino == self._NUEVO_CARRITO:
            # El carrito nuevo se crea DESPUÉS de comprobar las existencias:
            # crearlo antes dejaría un carrito vacío colgado en la sesión
            # cuando no hubiera nada que poner dentro.
            carrito = crear_nuevo_carrito(sid)
        else:
            # Un destino que ya no existe (otro camino lo eliminó) cae al
            # activo en vez de tumbar la acción.
            carrito = obtener_todos_los_carritos(sid).get(destino) or obtener_carrito_activo(sid)

        for prod in aptos:
            agregar_o_actualizar_producto(
                sid, prod, cantidad=cantidad, id_carrito=carrito["id"],
            )
        # El destino elegido pasa a ser el activo: es el carrito en el que el
        # usuario acaba de decidir trabajar, y Ventas abre el activo.
        cambiar_carrito_activo(sid, carrito["id"])

        agregados = [p["codigo"] for p in aptos]
        plural = "ítems" if len(agregados) != 1 else "ítem"
        self._snack(
            f"{len(agregados)} {plural} añadidos a {carrito['id']}.",
            ft.Colors.GREEN_700, e,
        )
        if omitidos:
            self._snack(
                "Quedaron fuera (sin existencia suficiente o ya no están en el "
                f"inventario): {', '.join(omitidos)}.",
                ft.Colors.AMBER_700, e,
            )
        # La diferencia entre las dos acciones: F3 se queda en Inventario y F2
        # ("Procesar Venta") lleva además a Ventas.
        if ir_a_ventas and not self._ir_a_ventas(e):
            self._snack(
                "Esta acción requiere el Dashboard (navegación a Ventas no "
                "disponible en este contexto).",
                ft.Colors.AMBER_700, e,
            )
        return agregados

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

        carritos_dict = obtener_todos_los_carritos(sid)
        opciones_carrito = [
            ft.dropdown.Option(NUEVO_CARRITO, "➕ Crear nuevo carrito")
        ] + [ft.dropdown.Option(cid, self._etiqueta_carrito(cinfo)) for cid, cinfo in carritos_dict.items()]

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
                self._soltar_campos_de_dialogo(dlg)
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
            self._soltar_campos_de_dialogo(dlg)
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

        # Este diálogo es el único del módulo que todavía se monta a mano en el
        # `overlay` en vez de pasar por `_open_dialog`, así que sus campos
        # (cantidad, cédula del cliente, datos del cliente nuevo) hay que
        # enlazarlos y soltarlos aquí mismo.
        self._enlazar_campos_de_dialogo(dlg)
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

    def _confirmar_eliminar_lote(self, e=None, codigos=None):
        """Borrado masivo: enuncia cuántos ítems y cuáles, y pide la clave una
        sola vez para todo el lote.

        `codigos` permite nombrar el lote explícitamente, que es como llegan
        tanto F6 como la respuesta "los N marcados" del `DialogoAlcance`; sin
        él se toma la selección vigente. Se acepta el lote ya resuelto en vez
        de releer la selección aquí para que el lote que el usuario vio
        enunciado en el diálogo de alcance sea exactamente el que se borra.
        """
        codigos = list(codigos) if codigos else list(self._seleccion.seleccionados)
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
