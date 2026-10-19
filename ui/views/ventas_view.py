import os
import tkinter as tk
from tkinter import filedialog
import flet as ft
from ui.views.base_view import BaseView
from ui.components.scroll_nav import build_scroll_nav
from ui.components.seleccion_lista import SeleccionLista
from ui.components.teclado_nav import (
    ATAJOS_ITEM,
    ControlTeclado,
    RegistroFoco,
)
from core.database import get_setting, set_setting
from services.bcv_service import obtener_estado_tasa
from services.cartera_service import (
    actualizar_cliente,
    buscar_cliente_por_cedula,
    crear_cliente,
    parse_documento,
    format_documento,
)
from services.permisos_service import puede_ver_costos
from services.inventario_service import listar_productos
from services.busqueda_service import (
    CRITERIOS_BUSQUEDA,
    CRITERIO_POR_DEFECTO,
    buscar_productos,
    resolver_coincidencia_exacta,
)
from services.ventas_service import (
    calcular_porcentaje_descuento,
    formatear_porcentaje_descuento,
    procesar_venta,
)
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
    vaciar_carrito_activo,
    establecer_metodo_pago,
    establecer_tipo_venta,
    calcular_monto_predeterminado,
    calcular_suma_costos,
    moneda_de_cobro,
    METODOS_PAGO,
    METODOS_PAGO_BS,
    METODOS_PAGO_CREDITO,
    TIPO_VENTA_FORMAL,
)

class VentasView(BaseView):
    # ── Visibilidad de columnas de la tabla del carrito ─────────────────────
    # Estado a nivel de clase (no de instancia): el Dashboard reconstruye una
    # instancia nueva de VentasView en cada re-render (ver DashboardView.get_body),
    # así que si esto viviera solo en self se perdería con cada actualización.
    # "marcador" (casilla de selección) y "acciones" (íconos de editar/remover)
    # son estructurales y NO figuran aquí: ocultar el marcador dejaría el
    # sombreado sin forma de quitarse con el mouse, y ocultar las acciones
    # escondería los únicos botones del renglón.
    _COLUMNAS_CARRITO_OCULTABLES = ["codigo", "producto", "cantidad", "precio_usd", "precio_bs", "subtotal"]
    _columnas_carrito_visibles_estaticas = {k: True for k in _COLUMNAS_CARRITO_OCULTABLES}
    _modo_vista_carrito_estatico = "separado"

    def __init__(self, page: ft.Page = None, user_data: dict = None, on_update_callback=None):
        self.user_data = user_data or {}
        self.venta_id_reciente = None
        self.divisa_impresion_pdf = "USD"
        # Page real inyectada por el Dashboard. self.page (heredado de
        # BaseControl) es una propiedad de solo lectura que camina el árbol
        # de padres — como esta instancia nunca queda adjunta al árbol real
        # de la página (ver rebuild_ui más abajo), self.page SIEMPRE lanza
        # RuntimeError aquí; hay que guardar la referencia real aparte.
        self._page_ref = page
        # Callback del Dashboard para forzar un re-render real: como el Dashboard
        # embebe únicamente el resultado de get_body() (no esta instancia) en su
        # propio árbol de controles, llamar a self.rebuild_ui() heredado de
        # BaseView no actualiza nada visible en pantalla (mutaría una instancia
        # "huérfana" que nunca queda adjunta a la página). Ver bitácora 10/08/2026.
        self.on_update_callback = on_update_callback

        # Rol nombrado del usuario conectado. NO autoriza nada por sí mismo:
        # solo decide si el hint con la suma de costos del carrito se dibuja
        # (los costos son información reservada a la administración, ver
        # `services/permisos_service`). El piso del descuento lo valida
        # igualmente `ventas_service` para todos los roles.
        self._rol_usuario = self.user_data.get("role")

        # ── Pila de diálogos abiertos (el tope es el que se ve) ──────────────
        # Es una PILA porque el diálogo de cobro abre otros encima (la
        # confirmación de omitir la referencia, la ventana de crédito): al
        # cerrar el de arriba hay que volver a apuntar al de abajo y no
        # perderlo. Ver `ui/views/inventario_view.py`, donde una sola
        # referencia dejaba al usuario atrapado.
        self._dialog_stack: list[ft.AlertDialog] = []

        # Datos capturados en la ventana de crédito (fecha límite y contacto).
        # Viven en la vista y no en el carrito porque son del COBRO, no de la
        # mercancía: cambiar de método de pago los descarta.
        self._datos_credito: dict | None = None

        # ── Marcador del renglón del carrito (Nueva Función 3) ───────────────
        # DELIBERADAMENTE de instancia y no de clase, al revés de las
        # preferencias de columnas de arriba. El marcador es un puntero
        # efímero a "el renglón sobre el que estoy trabajando ahora", y
        # compartirlo tendría dos consecuencias graves:
        #   - Entre sesiones (dos vendedores en dos pestañas) el marcador de
        #     uno dejaría los botones del otro deshabilitados, porque
        #     `puede_accionar` solo habilita lo marcado.
        #   - Entre las instancias que el Dashboard reconstruye en cada
        #     render, una instancia muerta seguiría viendo selección y
        #     ejecutaría los atajos por segunda vez.
        # Las interacciones que importan (marcar, editar, quitar, +/-) pasan
        # por `_refrescar_carrito_y_resumen`, que NO reconstruye el Dashboard,
        # así que la marca sobrevive a todo el uso normal del carrito.
        self._seleccion = SeleccionLista()

        # ── Atajos de teclado (flechas de navegación y F1–F6) ───────────────
        # Los destinos de scroll se pasan como INVOCABLES y no como controles:
        # la tabla del carrito se reconstruye entera en cada repintado, así
        # que un control guardado aquí sería uno que ya no está en pantalla y
        # las flechas desplazarían un árbol muerto sin dar señal de nada.
        self._carrito_scroll_h = None
        self._carrito_scroll_v = None
        self._resultados_scroll_v = None
        self._registro_foco = RegistroFoco()
        self._teclado = ControlTeclado(
            obtener_pagina=self._pagina_actual,
            destino_vertical=self._destino_scroll_vertical,
            destino_horizontal=self._destino_scroll_horizontal,
            seleccion=self._seleccion,
            ejecutar_accion=self.ejecutar_accion_sobre_seleccionado,
            al_limpiar=self.limpiar_seleccion,
            registro_foco=self._registro_foco,
        )

        self._columnas_carrito_ocultables = VentasView._COLUMNAS_CARRITO_OCULTABLES
        self._columnas_carrito_labels = {
            "marcador": "Sel.",
            "codigo": "Código",
            "producto": "Producto",
            "cantidad": "Cant.",
            "precio_usd": "P. Unit ($)",
            "precio_bs": "P. Unit (Bs)",
            "subtotal": "Subtotal ($)",
            "acciones": "Acciones",
        }
        self._columnas_carrito_visibles = VentasView._columnas_carrito_visibles_estaticas
        self._modo_vista_carrito = VentasView._modo_vista_carrito_estatico

        super().__init__(route="/ventas", title="Módulo de Ventas y Notas de Entrega")

        # Cargar estado de la Tasa BCV
        self.actualizar_estado_tasa_local()

    def _handle_cambio_modo_vista_carrito(self, e):
        if e.control.selected:
            VentasView._modo_vista_carrito_estatico = list(e.control.selected)[0]
            self._refrescar_carrito_y_resumen(e)

    def rebuild_ui(self, e=None):
        """Sobreescribe BaseView.rebuild_ui(): esta vista es reconstruida por
        DashboardView en cada render y no permanece adjunta a la página, por lo
        que reconstruir solo self.controls no se refleja en pantalla. En su
        lugar se delega al callback del Dashboard, que sí es la vista viva."""
        if self.on_update_callback:
            try:
                self.on_update_callback()
            except (RuntimeError, AttributeError):
                pass
        else:
            super().rebuild_ui()

    def _refrescar_carrito_y_resumen(self, e=None):
        """Actualiza in-situ la tabla del carrito y el panel de resumen de venta
        sin provocar la reconstrucción completa del Dashboard."""
        c_activo = obtener_carrito_activo(self._sid)
        items = c_activo["items"]

        if hasattr(self, "tabla_carrito_container"):
            self.tabla_carrito_container.content = self.build_tabla_carrito(items)

        tot_usd = sum(item["subtotal_usd"] for item in items)
        tot_bcv = sum(item["subtotal_bcv"] for item in items)
        tot_usd_bcv_equivalente = round(tot_bcv / self.tasa_bcv, 2) if self.tasa_bcv > 0 else 0.0

        if hasattr(self, "lbl_subtotal_usd"):
            self.lbl_subtotal_usd.value = f"$ {tot_usd:,.2f}"
        if hasattr(self, "lbl_subtotal_bcv"):
            self.lbl_subtotal_bcv.value = f"Bs. {tot_bcv:,.2f}"
        if hasattr(self, "lbl_total_usd_efectivo"):
            self.lbl_total_usd_efectivo.value = f"$ {tot_usd:,.2f}"
        if hasattr(self, "lbl_total_usd_pago_bs"):
            self.lbl_total_usd_pago_bs.value = f"$ {tot_usd_bcv_equivalente:,.2f}"
        if hasattr(self, "lbl_total_bcv"):
            self.lbl_total_bcv.value = f"Bs. {tot_bcv:,.2f}"

        # Método de pago (determina qué monto se cobra realmente): Efectivo/
        # Binance cobran en dólares (Precio USD Efectivo); Pago Móvil/
        # Transferencia/Punto cobran en Bolívares (Precio USD BCV x tasa).
        # Todo lo que depende de esto (monto, título, referencia, resaltado
        # de los dos totales y el borde de la caja) debe refrescarse aquí —
        # si no, cambiar el método en el Dropdown no se refleja visualmente.
        metodo_pago_actual = c_activo.get("metodo_pago", "Efectivo")
        cobra_en_bs = metodo_pago_actual in METODOS_PAGO_BS
        monto_str, color_metodo, sub_texto = self._estilo_metodo_pago(
            metodo_pago_actual, tot_usd, tot_bcv, tot_usd_bcv_equivalente
        )

        if hasattr(self, "lbl_monto_a_pagar"):
            self.lbl_monto_a_pagar.value = monto_str
            self.lbl_monto_a_pagar.color = color_metodo

        if hasattr(self, "lbl_monto_titulo"):
            self.lbl_monto_titulo.value = f"MONTO A COBRAR ({metodo_pago_actual}):"

        if hasattr(self, "txt_sub_metodo_ref"):
            self.txt_sub_metodo_ref.value = sub_texto
            self.txt_sub_metodo_ref.color = color_metodo

        if hasattr(self, "container_monto_a_pagar"):
            self.container_monto_a_pagar.border = ft.Border.all(1.5, color_metodo)

        if hasattr(self, "lbl_total_efectivo_titulo"):
            self.lbl_total_efectivo_titulo.weight = ft.FontWeight.NORMAL if cobra_en_bs else ft.FontWeight.BOLD
            self.lbl_total_efectivo_titulo.color = self.get_text_color() if cobra_en_bs else ft.Colors.GREEN_700

        if hasattr(self, "lbl_total_bcv_titulo"):
            self.lbl_total_bcv_titulo.weight = ft.FontWeight.BOLD if cobra_en_bs else ft.FontWeight.NORMAL
            self.lbl_total_bcv_titulo.color = ft.Colors.AMBER_800 if cobra_en_bs else self.get_text_color()

        if hasattr(self, "tira_carritos_container"):
            carritos_dict = obtener_todos_los_carritos(self._sid)
            self.tira_carritos_container.content = self._build_tira_carritos(carritos_dict, obtener_id_carrito_activo(self._sid))

        if hasattr(self, "dd_carritos"):
            carritos_dict = obtener_todos_los_carritos(self._sid)
            def _etiqueta_carrito(cinfo: dict) -> str:
                cliente = cinfo.get("cliente")
                n_items = len(cinfo.get("items", []))
                quien = cliente["nombre"] if cliente else "Sin cliente"
                return f"{cinfo['nombre']} — {quien} ({n_items} ítem{'s' if n_items != 1 else ''})"
            self.dd_carritos.options = [ft.dropdown.Option(cid, _etiqueta_carrito(cinfo)) for cid, cinfo in carritos_dict.items()]
            self.dd_carritos.value = obtener_id_carrito_activo(self._sid)

        # `safe_update(e)` resuelve la página vía `e.control.page`, pero para
        # el `on_change` de un `Dropdown` esa referencia puede no estar
        # disponible en el momento del evento (a diferencia de un clic de
        # botón) — si eso pasa, todos los atributos de arriba sí se
        # actualizan en el modelo de datos, pero `page.update()` nunca se
        # llama y no se ve ningún cambio en pantalla, aunque los cálculos
        # sean correctos. Se agrega `self._page_ref` (la Page real inyectada
        # por el Dashboard al construir esta vista, ya usada como respaldo
        # en `_calcular_sid`) como último recurso para no depender solo del
        # evento.
        p = self.get_current_page(e) or self._page_ref
        if p:
            p.update()
        else:
            self.safe_update(e)

    def _estilo_metodo_pago(
        self, metodo_pago: str, tot_usd: float, tot_bcv: float, tot_usd_bcv_equivalente: float
    ) -> tuple[str, str, str]:
        """Monto, color y subtítulo de la caja "MONTO A COBRAR" según el método.

        Son tres casos con lecturas distintas y por eso no comparten color:
        Bolívares (ámbar), dólares en efectivo (verde) y Crédito (morado), que
        no cobra nada ahora y por eso dice explícitamente que genera una deuda
        — confundirlo con un cobro en dólares es el error caro."""
        if metodo_pago in METODOS_PAGO_CREDITO:
            return f"$ {tot_usd:,.2f}", ft.Colors.PURPLE_400, "A crédito: genera Deuda por Cobrar"
        if metodo_pago in METODOS_PAGO_BS:
            return (
                f"Bs. {tot_bcv:,.2f}",
                ft.Colors.AMBER_800,
                f"Ref: $ {tot_usd_bcv_equivalente:,.2f} BCV",
            )
        return f"$ {tot_usd:,.2f}", ft.Colors.GREEN_700, "Dólares en Efectivo"

    # ── Atajos de teclado: instalación y destinos de scroll ─────────────────

    def _pagina_actual(self, e=None):
        """Página viva de la vista. Es lo que `ControlTeclado` necesita para
        tomar el teclado, y se resuelve igual que en el resto del archivo:
        primero el evento (siempre fiable) y después la Page inyectada por el
        Dashboard al construir la vista."""
        return self.get_current_page(e) or self._page_ref

    def _asegurar_teclado(self, e=None) -> bool:
        """Engancha los atajos a la página, de forma perezosa e idempotente.

        Perezosa porque al construir la vista todavía no hay `page`: esta
        vista se instancia headless y el Dashboard la monta después, así que
        se reintenta desde los puntos en los que ya hay un evento a mano. La
        idempotencia y el respeto por el handler previo —esta vista comparte
        la página con el Dashboard y no puede quedarse con el teclado— los
        resuelve `ControlTeclado`; aquí solo se le pide instalarse.
        """
        return self._teclado.instalar(e)

    def _enlazar_foco(self, campos: dict) -> None:
        """Enlaza un grupo de `TextField` al registro de foco, por nombre.

        TODO campo de texto de la vista en el que pueda estar el cursor tiene
        que pasar por aquí —los del cuerpo y los de cada diálogo—, porque la
        regla de las flechas se decide con este registro: un campo que se
        quede sin enlazar le desplaza la pantalla al usuario justo mientras
        escribe en él, que es exactamente lo que la regla evita. Los nombres
        se prefijan por diálogo para que dos campos homónimos (dos "Teléfono",
        dos "Cantidad") no se pisen la entrada del registro.
        """
        for nombre, campo in campos.items():
            self._registro_foco.enlazar(campo, nombre)

    def _liberar_foco(self) -> None:
        """Da por soltado el foco de todos los campos. Se llama al cerrar
        cualquier diálogo.

        Hace falta porque no se puede contar con que Flet entregue el `on_blur`
        de un campo que desaparece de la pantalla junto con su diálogo. Si ese
        aviso no llega, el registro se queda creyendo que hay un campo con el
        cursor y las flechas dejan de navegar para siempre, sin nada en
        pantalla que explique por qué. El error se corre a propósito hacia
        este lado: los diálogos de esta vista son modales, así que al cerrarse
        no queda ningún campo detrás en el que el usuario pueda estar
        escribiendo.
        """
        self._registro_foco.limpiar()

    def _destino_scroll_vertical(self):
        """Qué desplazan ↑/↓ (y Ctrl+↑/↓ hasta el extremo).

        El carrito es la lista sobre la que actúan los atajos F5/F6, así que
        es también la que navegan las flechas: tener un eje con dos dueños
        según dónde esté mirando el usuario convierte cada pulsación en una
        apuesta. La única excepción es el carrito VACÍO, donde no hay tabla ni
        scroll que mover y el panel de resultados es lo único desplazable en
        pantalla.
        """
        return self._carrito_scroll_v or self._resultados_scroll_v

    def _destino_scroll_horizontal(self):
        """Qué desplazan ←/→: el mismo eje que mueven los botones de flecha de
        la barra del carrito (la tabla es más ancha que la pantalla)."""
        return self._carrito_scroll_h

    def _calcular_sid(self, e=None) -> str:
        """Resuelve el ID de sesión de Flet (page.session.id) para aislar los
        carritos por usuario/pestaña. Prioriza el evento de clic (siempre
        fiable porque el control que lo disparó sí está adjunto a la página
        real) y cae de vuelta a la Page inyectada por el Dashboard al
        construir esta vista (self._page_ref) para los casos sin evento,
        como la carga inicial en get_body()."""
        if e is not None:
            sid = self.get_session_id(e)
            if sid != "_sin_sesion":
                return sid
        if self._page_ref is not None:
            try:
                return self._page_ref.session.id
            except (RuntimeError, AttributeError):
                pass
        return self.get_session_id(e)

    # ── Pila de diálogos (API nativa de Flet 0.86) ──────────────────────────

    @property
    def _dialog(self) -> "ft.AlertDialog | None":
        """Diálogo activo (tope de la pila) o `None` si no hay ninguno."""
        return self._dialog_stack[-1] if self._dialog_stack else None

    def _open_dialog(self, dialog: ft.AlertDialog, e=None):
        """Apila un diálogo y lo muestra sobre el que hubiera debajo."""
        if dialog not in self._dialog_stack:
            self._dialog_stack.append(dialog)
        dialog.open = True

        p = self.get_current_page(e) or self._page_ref
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

    def _close_dialog(self, e=None, dialog: ft.AlertDialog = None):
        """Descarta el diálogo del tope y deja activo el que estaba debajo.

        El cierre se delega en `page.pop_dialog()`: con el patrón heredado
        (`page.overlay` + bandera `open`) Flet 0.86 no llega a dibujar el
        cierre y el diálogo se queda pegado —o activo pero invisible,
        recibiendo clics sobre botones que ya no se ven—. `pop_dialog()`
        cierra el diálogo más alto que siga abierto, así que se invoca ANTES
        de bajar la bandera: al revés cerraría el de abajo.
        """
        if dialog is None:
            dialog = self._dialog
        if dialog is None:
            return
        if dialog in self._dialog_stack:
            self._dialog_stack.remove(dialog)
        self._liberar_foco()

        p = self.get_current_page(e) or self._page_ref
        if p is not None and hasattr(p, "pop_dialog"):
            p.pop_dialog()
            dialog.open = False
            return

        dialog.open = False
        if p is None:
            return
        if dialog in getattr(p, "overlay", []):
            p.overlay.remove(dialog)
        p.update()

    def _cerrar_todos_los_dialogos(self, e=None):
        """Vacía la pila cerrando de arriba hacia abajo (cancelación total)."""
        while self._dialog_stack:
            self._close_dialog(e, dialog=self._dialog_stack[-1])

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
        self._sid = self._calcular_sid()
        self.actualizar_estado_tasa_local()
        carrito_activo = obtener_carrito_activo(self._sid)

        # ── 1. Cabecera: Selector de Carrito, Selector Tipo Venta y Tasa BCV ──
        # Cada opción muestra a qué cliente pertenece el carrito (o "Sin
        # cliente" si es una venta informal/aún sin vincular), para que
        # nunca sea ambiguo a quién se le está vendiendo en cada carrito.
        carritos_dict = obtener_todos_los_carritos(self._sid)

        def _etiqueta_carrito(cinfo: dict) -> str:
            cliente = cinfo.get("cliente")
            n_items = len(cinfo.get("items", []))
            quien = cliente["nombre"] if cliente else "Sin cliente"
            return f"{cinfo['nombre']} — {quien} ({n_items} ítem{'s' if n_items != 1 else ''})"

        options_carritos = [ft.dropdown.Option(cid, _etiqueta_carrito(cinfo)) for cid, cinfo in carritos_dict.items()]

        self.dd_carritos = ft.Dropdown(
            label="Carrito Activo (Cliente)",
            value=obtener_id_carrito_activo(self._sid),
            options=options_carritos,
            width=320,
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

        self.tira_carritos_container = ft.Container(
            content=self._build_tira_carritos(carritos_dict, obtener_id_carrito_activo(self._sid))
        )

        cabecera_card = self.create_card(
            content=ft.Column(
                controls=[
                    self.tira_carritos_container,
                    ft.Row(
                        controls=[
                            ft.Row([self.dd_carritos, btn_nuevo_carrito, btn_eliminar_carrito], spacing=5),
                            self.tipo_venta_selector,
                            tasa_badge
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        wrap=True
                    ),
                ],
                spacing=10,
            ),
            padding=12,
            border_radius=16
        )

        # ── 2. Panel de Cliente (Venta Formal) ────────────────────────────────
        # Búsqueda simplificada: un Dropdown para el tipo de documento
        # (V/E/J/G/P) + un campo que solo acepta el número de Cédula/RIF —
        # el operador nunca necesita escribir letras ni guiones.
        cliente_actual = carrito_activo.get("cliente")
        self.cli_search_tipo = ft.Dropdown(
            value="V",
            width=80,
            border_radius=12,
            options=[
                ft.dropdown.Option("V"),
                ft.dropdown.Option("E"),
                ft.dropdown.Option("J"),
                ft.dropdown.Option("G"),
                ft.dropdown.Option("P"),
            ],
        )
        self.cli_search_numero = ft.TextField(
            label="Número de Cédula / RIF",
            hint_text="Solo números, ej: 12345678",
            prefix_icon=ft.Icons.BADGE,
            keyboard_type=ft.KeyboardType.NUMBER,
            border_radius=12,
            expand=True,
            on_change=self._filtrar_solo_digitos_cliente,
            on_submit=self.handle_buscar_cliente,
        )
        self._enlazar_foco({"cliente_cedula": self.cli_search_numero})
        self.btn_buscar_cli = ft.ElevatedButton(
            content=ft.Row([ft.Icon(ft.Icons.SEARCH, size=18), ft.Text("Buscar Cliente", weight=ft.FontWeight.BOLD)], tight=True),
            style=ft.ButtonStyle(
                color=ft.Colors.WHITE,
                bgcolor=self.get_accent_color(),
                shape=ft.RoundedRectangleBorder(radius=12)
            ),
            on_click=self.handle_buscar_cliente
        )

        if cliente_actual:
            lbl_texto_cli = f"✓ Esta venta es para: {cliente_actual['nombre']} ({cliente_actual['cedula_rif']}) — Tel: {cliente_actual.get('telefono', '-')}"
            lbl_color_cli = ft.Colors.GREEN_600
        else:
            lbl_texto_cli = "⚠ Ningún cliente seleccionado todavía. Busque o registre uno para continuar la Venta Formal."
            lbl_color_cli = ft.Colors.AMBER_700

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
                ft.Row([self.cli_search_tipo, self.cli_search_numero, self.btn_buscar_cli]),
                self.lbl_cliente_info
            ], spacing=8),
            padding=12,
            border_radius=16,
        )
        self.panel_cliente_container.visible = (carrito_activo.get("tipo_venta") == "Formal")

        # ── 3. Panel de Búsqueda Multicriterio e Inserción de Productos ──────
        # El selector de criterio va a la IZQUIERDA del campo de texto y sus
        # opciones se generan desde `CRITERIOS_BUSQUEDA` (mismo orden que el
        # mapa) para que agregar un criterio en el servicio no obligue a
        # tocar esta vista.
        self.criterio_busqueda_dd = ft.Dropdown(
            label="Buscar por",
            value=CRITERIO_POR_DEFECTO,
            width=165,
            border_radius=12,
            options=[ft.dropdown.Option(c) for c in CRITERIOS_BUSQUEDA]
        )

        # Enter busca y MUESTRA resultados; nunca muta el carrito. Agregar al
        # carrito es siempre un acto explícito: el botón "Agregar" de la barra
        # o el botón "Agregar" de una fila de resultados.
        self.prod_search_input = ft.TextField(
            label="Buscar Producto",
            hint_text="Escriba o escanee y presione Enter para ver coincidencias...",
            prefix_icon=ft.Icons.SEARCH,
            border_radius=12,
            width=320,
            on_submit=self.handle_buscar_producto
        )
        self.cant_input = ft.TextField(
            label="Cant.",
            value="1",
            width=90,
            keyboard_type=ft.KeyboardType.NUMBER,
            text_align=ft.TextAlign.CENTER,
            border_radius=12,
        )
        self._enlazar_foco({
            "busqueda_producto": self.prod_search_input,
            "cantidad_solicitada": self.cant_input,
        })
        self.btn_buscar_prod = ft.IconButton(
            icon=ft.Icons.MANAGE_SEARCH,
            icon_color=self.get_accent_color(),
            tooltip="Buscar coincidencias con el criterio seleccionado (equivale a presionar Enter)",
            on_click=self.handle_buscar_producto,
        )
        self.btn_agregar_prod = ft.ElevatedButton(
            content=ft.Row([ft.Icon(ft.Icons.ADD_SHOPPING_CART, size=18), ft.Text("Agregar", weight=ft.FontWeight.BOLD)], tight=True),
            style=ft.ButtonStyle(
                color=ft.Colors.WHITE,
                bgcolor=self.get_accent_color(),
                shape=ft.RoundedRectangleBorder(radius=12)
            ),
            on_click=self.handle_agregar_producto
        )
        self.btn_buscar_inventario = ft.OutlinedButton(
            content=ft.Row([ft.Icon(ft.Icons.INVENTORY_2_OUTLINED, size=18), ft.Text("Buscar en Inventario", weight=ft.FontWeight.BOLD)], tight=True),
            style=ft.ButtonStyle(
                color=self.get_accent_color(),
                shape=ft.RoundedRectangleBorder(radius=12),
                side={
                    ft.ControlState.DEFAULT: ft.BorderSide(1, self.get_accent_color()),
                }
            ),
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

        # Panel de resultados embebido en la vista (no un modal): se puebla con
        # `handle_buscar_producto` y arranca oculto para no ocupar espacio antes
        # de la primera búsqueda. Único dueño del scroll vertical: la Column
        # interna que construye `build_panel_resultados`, dentro de este
        # contenedor de altura acotada (no se anida otro scroll adentro).
        self.panel_resultados_container = ft.Container(
            content=None,
            visible=False,
            padding=ft.Padding.only(top=4),
        )
        self._resultados_busqueda: list[dict] = []

        panel_agregar_prod = self.create_card(
            content=ft.Column([
                ft.Text("BÚSQUEDA Y SELECCIÓN DE ARTÍCULOS", size=13, weight=ft.FontWeight.BOLD, color=self.get_accent_color()),
                ft.Row([self.criterio_busqueda_dd, self.prod_search_input, self.btn_buscar_prod, self.cant_input, self.btn_agregar_prod, self.btn_buscar_inventario], alignment=ft.MainAxisAlignment.START, wrap=True),
                self.panel_resultados_container,
                panel_recomendaciones
            ], spacing=10),
            padding=15,
            border_radius=16
        )

        # ── 4. Carrito de Compras (Tabla de Ítems Renglones) ──────────────────
        # Se establece una altura fija (height=440) para evitar que colapse verticalmente en el layout
        self.tabla_carrito_container = ft.Container(
            content=self.build_tabla_carrito(carrito_activo["items"]),
            height=440,
            expand=True
        )

        # ── 5. Resumen de Venta Bimoneda Detallado ─────────────────────────────
        tot_usd = sum(item["subtotal_usd"] for item in carrito_activo["items"])
        tot_bcv = sum(item["subtotal_bcv"] for item in carrito_activo["items"])
        tot_usd_bcv_equivalente = round(tot_bcv / self.tasa_bcv, 2) if self.tasa_bcv > 0 else 0.0

        self.lbl_subtotal_usd = ft.Text(f"$ {tot_usd:,.2f}", size=14, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_600)
        self.lbl_subtotal_bcv = ft.Text(f"Bs. {tot_bcv:,.2f}", size=14, weight=ft.FontWeight.BOLD, color=ft.Colors.AMBER_700)

        # Desglose: Total $ Efectivo vs Total $ BCV (referencia) vs Total Bs
        self.lbl_total_usd_efectivo = ft.Text(f"$ {tot_usd:,.2f}", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_700)
        self.lbl_total_usd_pago_bs = ft.Text(f"$ {tot_usd_bcv_equivalente:,.2f}", size=14, weight=ft.FontWeight.W_600, color=self.get_subtext_color())
        self.lbl_total_bcv = ft.Text(f"Bs. {tot_bcv:,.2f}", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.AMBER_800)
        self.lbl_antiguedad_resumen = ft.Text(f"Tasa: {self.tasa_bcv:,.2f} Bs/$ ({self.tasa_antiguedad})", size=10, color=self.get_subtext_color())

        # ── Selector de Método de Pago (determina qué monto se cobra) ────────
        # Efectivo/Binance: se cobra el Total $ (Precio USD Efectivo).
        # Pago Móvil/Transferencia/Punto: se cobra en Bolívares (Precio USD BCV x tasa).
        metodo_pago_actual = carrito_activo.get("metodo_pago", "Efectivo")
        self.dd_metodo_pago = ft.Dropdown(
            label="Método de Pago del Cliente",
            value=metodo_pago_actual,
            width=230,
            border_radius=12,
            options=self._opciones_metodo_pago(carrito_activo),
        )
        self.dd_metodo_pago.on_change = self.handle_cambio_metodo_pago

        cobra_en_bs = metodo_pago_actual in METODOS_PAGO_BS
        monto_a_pagar_str, lbl_monto_color, txt_sub_metodo = self._estilo_metodo_pago(
            metodo_pago_actual, tot_usd, tot_bcv, tot_usd_bcv_equivalente
        )

        self.lbl_monto_a_pagar = ft.Text(monto_a_pagar_str, size=18, weight=ft.FontWeight.BOLD, color=lbl_monto_color)
        self.lbl_monto_titulo = ft.Text(f"MONTO A COBRAR ({metodo_pago_actual}):", size=12, weight=ft.FontWeight.BOLD, color=self.get_text_color())
        self.txt_sub_metodo_ref = ft.Text(txt_sub_metodo, size=11, color=lbl_monto_color, weight=ft.FontWeight.W_600)
        # Etiquetas de los dos totales (Efectivo vs Bs): se resaltan en negrita
        # y en el color de su moneda cuando ese es el método activo, para que
        # sea evidente cuál de los dos montos es el que realmente se cobra.
        self.lbl_total_efectivo_titulo = ft.Text(
            "Total $ (Efectivo):", size=14,
            weight=ft.FontWeight.BOLD if not cobra_en_bs else ft.FontWeight.NORMAL,
            color=ft.Colors.GREEN_700 if not cobra_en_bs else self.get_text_color(),
        )
        self.lbl_total_bcv_titulo = ft.Text(
            "TOTAL A PAGAR (Bs):", size=14,
            weight=ft.FontWeight.BOLD if cobra_en_bs else ft.FontWeight.NORMAL,
            color=ft.Colors.AMBER_800 if cobra_en_bs else self.get_text_color(),
        )
        self.container_monto_a_pagar = ft.Container(
            content=ft.Column([
                ft.Row([self.lbl_monto_titulo, self.lbl_monto_a_pagar], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Row([self.txt_sub_metodo_ref], alignment=ft.MainAxisAlignment.END),
            ], spacing=2),
            padding=ft.Padding.symmetric(horizontal=10, vertical=8),
            bgcolor=self.get_card_bg(),
            border_radius=10,
            border=ft.Border.all(1.5, lbl_monto_color),
        )

        panel_totales = self.create_card(
            content=ft.Column([
                ft.Text("RESUMEN DE VENTA", size=14, weight=ft.FontWeight.BOLD, color=self.get_accent_color()),
                ft.Divider(height=6),
                ft.Row([ft.Text("Subtotal ($):", weight=ft.FontWeight.BOLD, color=self.get_text_color()), self.lbl_subtotal_usd], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Row([ft.Text("Subtotal (Bs):", weight=ft.FontWeight.BOLD, color=self.get_text_color()), self.lbl_subtotal_bcv], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Divider(height=6),
                ft.Row([self.lbl_total_efectivo_titulo, self.lbl_total_usd_efectivo], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Row([ft.Text("Total $ (Referencia BCV):", size=13, color=self.get_subtext_color()), self.lbl_total_usd_pago_bs], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Row([self.lbl_total_bcv_titulo, self.lbl_total_bcv], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Row([self.lbl_antiguedad_resumen], alignment=ft.MainAxisAlignment.END),
                ft.Divider(height=6),
                self.dd_metodo_pago,
                self.container_monto_a_pagar,
                ft.Container(height=8),
                ft.FilledButton(
                    content=ft.Row([
                        ft.Icon(ft.Icons.POINT_OF_SALE, size=20),
                        ft.Text("PROCESAR VENTA", size=14, weight=ft.FontWeight.BOLD)
                    ], alignment=ft.MainAxisAlignment.CENTER, tight=True),
                    style=ft.ButtonStyle(
                        bgcolor=ft.Colors.BLUE_700,
                        color=ft.Colors.WHITE,
                        shape=ft.RoundedRectangleBorder(radius=12)
                    ),
                    height=48,
                    on_click=self.handle_procesar_venta
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

        # Primer intento de enganche del teclado: cuando el Dashboard inyectó
        # la Page al construir la vista, aquí ya hay con qué (y las flechas
        # funcionan desde el primer pintado, sin esperar un clic).
        self._asegurar_teclado()

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

    def _build_tira_carritos(self, carritos_dict: dict, activo_id: str) -> ft.Control:
        """Tira horizontal de tarjetas, una por carrito abierto: muestra de un
        vistazo cliente, cantidad de ítems y total $ de cada uno, resalta el
        activo y permite activar/eliminar con un clic — antes solo existía un
        Dropdown de texto que obligaba a abrirlo para comparar carritos."""
        accent = self.get_accent_color()
        text_color = self.get_text_color()
        subtext = self.get_subtext_color()
        border = self.get_border_color()

        tarjetas = []
        for cid, cinfo in carritos_dict.items():
            es_activo = (cid == activo_id)
            cliente = cinfo.get("cliente")
            quien = cliente["nombre"] if cliente else "Sin cliente"
            items_c = cinfo.get("items", [])
            total_usd = sum(i["subtotal_usd"] for i in items_c)
            tipo_icon = ft.Icons.BUSINESS if cinfo.get("tipo_venta") == "Formal" else ft.Icons.STORE

            tarjetas.append(
                ft.Container(
                    content=ft.Row(
                        controls=[
                            ft.Column(
                                controls=[
                                    ft.Row([
                                        ft.Icon(tipo_icon, size=13, color=accent if es_activo else subtext),
                                        ft.Text(cinfo["nombre"], size=12, weight=ft.FontWeight.BOLD, color=text_color, max_lines=1),
                                    ], spacing=4, tight=True),
                                    ft.Text(quien, size=11, color=subtext, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                                    ft.Text(
                                        f"{len(items_c)} ítem(s) · $ {total_usd:,.2f}",
                                        size=11, weight=ft.FontWeight.W_600,
                                        color=ft.Colors.GREEN_600 if total_usd else subtext,
                                    ),
                                ],
                                spacing=2, tight=True, expand=True,
                            ),
                            ft.IconButton(
                                icon=ft.Icons.CLOSE_ROUNDED, icon_size=14, icon_color=ft.Colors.RED_400,
                                tooltip=f"Eliminar '{cinfo['nombre']}'",
                                style=ft.ButtonStyle(padding=2),
                                on_click=lambda e, c=cid: self.handle_eliminar_carrito(e, c),
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                    ),
                    padding=10, border_radius=12, width=200,
                    bgcolor=self.get_card_bg(),
                    border=ft.Border.all(2 if es_activo else 1, accent if es_activo else border),
                    ink=True,
                    on_click=lambda e, c=cid: self.handle_cambiar_carrito_click(e, c),
                    tooltip="Carrito activo" if es_activo else "Clic para activar este carrito",
                )
            )

        tira_row = ft.Row(controls=tarjetas, spacing=8, scroll=ft.ScrollMode.AUTO)
        return ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.Text(f"CARRITOS ABIERTOS ({len(tarjetas)})", size=11, weight=ft.FontWeight.BOLD, color=subtext),
                        build_scroll_nav(tira_row, "horizontal", accent, tooltip_prefix="Carritos: "),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                tira_row,
            ],
            spacing=4,
        )

    # ── Manejadores de Eventos de Carrito y Tasa ──────────────────────────────

    def on_tasa_actualizada(self, nueva_tasa: float):
        """Callback invocado al actualizar la tasa BCV en el modal global."""
        self.actualizar_estado_tasa_local()
        # Recalcular el monto en Bolívares de cada renglón a partir de su
        # Precio USD BCV de referencia (no del Precio USD Efectivo).
        c = obtener_carrito_activo(self._sid)
        for item in c["items"]:
            ref_bcv = item.get("precio_usd_bcv_ref", item["precio_usd"])
            item["precio_bcv"] = round(ref_bcv * self.tasa_bcv, 2)
            item["subtotal_bcv"] = round(item["cantidad"] * item["precio_bcv"], 2)
        self.rebuild_ui()

    def handle_cambiar_carrito(self, e):
        cid = e.control.value
        cambiar_carrito_activo(self._sid, cid)
        self._refrescar_carrito_y_resumen(e)

    def handle_cambiar_carrito_click(self, e, cid: str):
        """Igual que handle_cambiar_carrito pero disparado desde una tarjeta
        de la tira de carritos (no tiene e.control.value de un Dropdown)."""
        cambiar_carrito_activo(self._sid, cid)
        self._refrescar_carrito_y_resumen(e)

    def handle_crear_nuevo_carrito(self, e):
        c_nuevo = crear_nuevo_carrito(self._sid)
        self.show_alert_success(e, f"¡Creado nuevo '{c_nuevo['nombre']}'!")
        self._refrescar_carrito_y_resumen(e)

    def handle_eliminar_carrito(self, e, cid: str):
        carritos = obtener_todos_los_carritos(self._sid)
        if len(carritos) == 1:
            eliminar_carrito(self._sid, cid)
            self.show_alert_info(e, f"Se vació el carrito '{cid}' por ser el único activo.")
        else:
            eliminar_carrito(self._sid, cid)
            self.show_alert_success(e, f"Carrito '{cid}' eliminado.")
        self._refrescar_carrito_y_resumen(e)

    def handle_eliminar_carrito_activo(self, e):
        self.handle_eliminar_carrito(e, obtener_id_carrito_activo(self._sid))

    def _opciones_metodo_pago(self, carrito: dict) -> list[ft.dropdown.Option]:
        """Opciones del selector de método de pago para un carrito concreto.

        "Crédito" se OFRECE solo en Venta Formal: la deuda por cobrar se
        registra contra la Cédula/RIF del cliente, así que en una venta de
        mostrador no es una opción válida y no debe aparecer (mejor no
        ofrecerla que ofrecerla y rechazarla al cobrar)."""
        opciones = [
            ft.dropdown.Option("Efectivo", "Efectivo ($)"),
            ft.dropdown.Option("Binance", "Binance ($)"),
            ft.dropdown.Option("Pago Móvil", "Pago Móvil (Bs)"),
            ft.dropdown.Option("Transferencia", "Transferencia (Bs)"),
            ft.dropdown.Option("Punto", "Punto de Venta (Bs)"),
        ]
        if (carrito or {}).get("tipo_venta") == TIPO_VENTA_FORMAL:
            opciones.append(ft.dropdown.Option("Credito", "Crédito (Deuda por Cobrar)"))
        return opciones

    def handle_cambio_metodo_pago(self, e):
        metodo = e.control.value
        try:
            establecer_metodo_pago(self._sid, metodo)
        except ValueError as ex:
            # Defensa en profundidad: el Dropdown no ofrece Crédito fuera de
            # Venta Formal, pero si llegara igual se vuelve a Efectivo en vez
            # de dejar el carrito en un estado que el cobro rechazaría.
            establecer_metodo_pago(self._sid, "Efectivo")
            e.control.value = "Efectivo"
            self.show_alert_error(e, str(ex))
            self._refrescar_carrito_y_resumen(e)
            return

        if metodo not in METODOS_PAGO_CREDITO:
            # Cambiar de método descarta lo capturado para el crédito: esos
            # datos (fecha límite, contacto) son del compromiso de pago, no
            # de la mercancía, y reusarlos más tarde sería inventar un dato.
            self._datos_credito = None

        self._refrescar_carrito_y_resumen(e)

        # "Si se selecciona el método crédito se abrirá una ventana con las
        # casillas obligatorias": se pide al elegirlo, no al cobrar, para que
        # el vendedor no descubra al final que le falta la fecha límite.
        if metodo in METODOS_PAGO_CREDITO:
            self.abrir_ventana_credito(e)

    def handle_cambio_tipo_venta(self, e):
        val = list(e.control.selected)[0] if e.control.selected else "Formal"
        # `establecer_tipo_venta` repara el método de pago: Crédito no existe
        # en Venta Mostrador y volvería inválido el carrito.
        c = establecer_tipo_venta(self._sid, val)
        if val == "Informal":
            desvincular_cliente(self._sid)
            self._datos_credito = None
        if hasattr(self, "dd_metodo_pago"):
            self.dd_metodo_pago.options = self._opciones_metodo_pago(c)
            self.dd_metodo_pago.value = c.get("metodo_pago", "Efectivo")
        self.rebuild_ui()

    def handle_desvincular_cliente(self, e):
        desvincular_cliente(self._sid)
        self.show_alert_info(e, "Cliente desvinculado de la venta.")
        self.rebuild_ui()

    def _filtrar_solo_digitos_cliente(self, e):
        """El operario nunca debe escribir letras/guiones: se filtra en vivo
        el número de Cédula/RIF para que solo queden dígitos."""
        limpio = "".join(filter(str.isdigit, self.cli_search_numero.value or ""))
        if limpio != self.cli_search_numero.value:
            self.cli_search_numero.value = limpio
            self.safe_update(e)

    def handle_buscar_cliente(self, e):
        numero = "".join(filter(str.isdigit, self.cli_search_numero.value or ""))
        if not numero:
            self.show_alert_error(e, "Ingrese el número de Cédula o RIF del cliente.")
            return

        tipo = self.cli_search_tipo.value or "V"
        cedula_completa = format_documento(tipo, numero)

        cliente = buscar_cliente_por_cedula(cedula_completa)
        if cliente:
            vincular_cliente_a_carrito(self._sid, cliente)
            self.show_alert_success(e, f"Cliente '{cliente['nombre']}' vinculado a la venta.")
            self.rebuild_ui()
        else:
            # ERS 3.4: si no coincide con la Cartera de Clientes, se abre el
            # Módulo 1.2 para registrarlo sin abandonar la venta en curso.
            self.abrir_modal_crear_cliente(cedula_completa, e)

    def abrir_modal_crear_cliente(self, cedula_sugerida: str, e=None):
        """Abre el Módulo 1.2 (Cartera de Clientes) para registrar al cliente
        no encontrado, aplicando RNO-CLI-01, y lo vincula a la venta en curso."""
        p = self.get_current_page(e)
        if not p:
            return

        tipo_sugerido, numero_sugerido = parse_documento(cedula_sugerida)
        f_tipo = ft.Dropdown(
            value=tipo_sugerido, width=80, border_radius=12, disabled=True,
            options=[ft.dropdown.Option(t) for t in ("V", "E", "J", "G", "P")],
        )
        f_numero = ft.TextField(label="Cédula/RIF *", value=numero_sugerido, border_radius=12, width=160, disabled=True)
        f_nombre = ft.TextField(label="Nombre / Razón Social *", autofocus=True, border_radius=12, expand=True)
        f_telefono = ft.TextField(label="Teléfono", border_radius=12, width=200)
        f_direccion = ft.TextField(label="Dirección", border_radius=12, expand=True)
        f_correo = ft.TextField(label="Correo (opcional)", border_radius=12, expand=True)
        self._enlazar_foco({
            "cliente_nuevo_cedula": f_numero,
            "cliente_nuevo_nombre": f_nombre,
            "cliente_nuevo_telefono": f_telefono,
            "cliente_nuevo_direccion": f_direccion,
            "cliente_nuevo_correo": f_correo,
        })
        lbl_err = ft.Text("", color=ft.Colors.RED_500, size=12, weight=ft.FontWeight.BOLD)

        def _crear(ev):
            try:
                nuevo = crear_cliente(
                    nombre=f_nombre.value,
                    cedula_rif=format_documento(f_tipo.value, f_numero.value),
                    direccion=f_direccion.value,
                    telefono=f_telefono.value,
                    correo=f_correo.value,
                )
                dlg.open = False
                self._liberar_foco()
                self.safe_update(ev)
                vincular_cliente_a_carrito(self._sid, nuevo)
                self.show_alert_success(ev, f"Cliente '{nuevo['nombre']}' registrado y vinculado a la venta.")
                self.rebuild_ui()
            except ValueError as ex:
                lbl_err.value = str(ex)
                self.safe_update(ev)

        def cerrar(ev):
            dlg.open = False
            self._liberar_foco()
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
                    ft.Row([f_tipo, f_numero, f_telefono], spacing=10),
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
        c, es_nuevo = agregar_o_actualizar_producto(self._sid, producto, cantidad=cantidad, tasa_bcv=self.tasa_bcv)
        nombre_c = producto.get("nombre_referencia_corto") or producto.get("referencia") or producto["codigo"]
        self.show_alert_success(e, f"Agregado {cantidad:.0f} ud(s) de '{nombre_c}' al {c['id']}.")
        self._refrescar_carrito_y_resumen(e)

    # ── Búsqueda de artículos (separada de la mutación del carrito) ──────────
    # Regla de diseño: BUSCAR y AGREGAR son dos responsabilidades distintas.
    # Enter en el campo de texto solo busca y renderiza coincidencias; agregar
    # al carrito ocurre únicamente al pulsar un botón "Agregar" explícito.

    _LIMITE_RESULTADOS_BUSQUEDA = 25

    def _leer_cantidad_solicitada(self, e=None) -> float | None:
        """Cantidad del `cant_input` validada; `None` (y alerta) si es inválida."""
        try:
            cantidad = float(self.cant_input.value or "1")
            if cantidad <= 0:
                raise ValueError()
        except ValueError:
            self.show_alert_error(e, "La cantidad debe ser mayor a cero.")
            return None
        return cantidad

    def _ejecutar_busqueda(self, e=None) -> tuple[str, list[dict]] | None:
        """Lee término + criterio de la barra y consulta el motor de búsqueda.
        Devuelve (término, resultados) o `None` si el término está vacío."""
        termino = (self.prod_search_input.value or "").strip()
        if not termino:
            self.show_alert_error(e, "Ingrese un término o código para buscar.")
            return None

        criterio = self.criterio_busqueda_dd.value or CRITERIO_POR_DEFECTO
        resultados = buscar_productos(
            termino, criterio=criterio, limite=self._LIMITE_RESULTADOS_BUSQUEDA
        )
        return termino, resultados

    def handle_buscar_producto(self, e):
        """Handler del Enter y del botón de lupa: SOLO busca y muestra. No
        toca el carrito bajo ninguna circunstancia — ni cuando el término
        coincide exactamente con un código o un código de barras (ahí el
        producto se destaca primero en la lista, pero no se agrega solo)."""
        consulta = self._ejecutar_busqueda(e)
        if consulta is None:
            return
        termino, resultados = consulta
        self._renderizar_resultados(termino, resultados, e)

    def _renderizar_resultados(self, termino: str, resultados: list[dict], e=None) -> None:
        """Puebla el panel de resultados con las coincidencias (la exacta
        primero) y refresca la pantalla."""
        exacto = resolver_coincidencia_exacta(termino, resultados)
        if exacto is not None:
            ordenados = [exacto] + [p for p in resultados if p["codigo"] != exacto["codigo"]]
        else:
            ordenados = list(resultados)

        self._resultados_busqueda = ordenados
        if hasattr(self, "panel_resultados_container"):
            self.panel_resultados_container.content = self.build_panel_resultados(
                termino, ordenados, exacto
            )
            self.panel_resultados_container.visible = True

        p = self.get_current_page(e) or self._page_ref
        if p:
            p.update()
        else:
            self.safe_update(e)

    # Reparto proporcional de la fila de resultados. Los pesos se distribuyen
    # el ancho que queda tras reservar el del botón "Agregar", que es fijo.
    _PESO_COL_CODIGO = 2
    _PESO_COL_NOMBRE = 5
    _PESO_COL_DEPARTAMENTO = 2
    _PESO_COL_PRECIOS = 2
    _PESO_COL_EXISTENCIA = 2
    _ANCHO_COL_AGREGAR = 120

    def build_panel_resultados(self, termino: str, resultados: list[dict], exacto: dict | None = None) -> ft.Control:
        """Lista de coincidencias con un botón "Agregar" por fila. Incluye
        estado vacío y avisa cuando se alcanzó el límite de resultados."""
        accent = self.get_accent_color()
        subtext = self.get_subtext_color()
        text_color = self.get_text_color()

        if not resultados:
            self._resultados_scroll_v = None  # nada que desplazar
            return ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.SEARCH_OFF, size=16, color=subtext),
                    ft.Text(
                        f"No se encontraron productos para '{termino}'.",
                        size=12, color=subtext, weight=ft.FontWeight.W_600,
                        no_wrap=False, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                ], tight=True, spacing=6),
                padding=10,
                border_radius=12,
                bgcolor=self.get_card_bg(),
                border=ft.Border.all(1, self.get_border_color()),
            )

        filas: list[ft.Control] = []
        for pr in resultados:
            es_exacto = exacto is not None and pr["codigo"] == exacto["codigo"]
            nombre = pr.get("nombre_referencia_corto") or pr.get("referencia") or pr["codigo"]
            descripcion = pr.get("descripcion_general") or ""
            existencia = float(pr.get("existencia") or 0.0)
            sin_stock = existencia <= 0

            filas.append(ft.Container(
                content=ft.Row([
                    # Código (+ marca de coincidencia exacta para el escáner).
                    ft.Container(
                        content=ft.Row([
                            ft.Icon(ft.Icons.QR_CODE_2, size=13, color=accent) if es_exacto else ft.Container(width=0),
                            ft.Text(pr["codigo"], size=11, weight=ft.FontWeight.BOLD, color=text_color,
                                    no_wrap=False, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                        ], tight=True, spacing=4),
                        expand=self._PESO_COL_CODIGO,
                    ),
                    # Nombre corto + descripción larga acotada (sin desbordes).
                    ft.Container(
                        content=ft.Column([
                            ft.Text(nombre, size=11, weight=ft.FontWeight.W_600, color=text_color,
                                    no_wrap=False, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                            ft.Text(descripcion, size=10, color=subtext,
                                    no_wrap=False, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                        ], spacing=1, tight=True),
                        expand=self._PESO_COL_NOMBRE,
                    ),
                    ft.Container(
                        content=ft.Text(pr.get("departamento") or "—", size=10, color=subtext,
                                        no_wrap=False, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                        expand=self._PESO_COL_DEPARTAMENTO,
                    ),
                    ft.Container(
                        content=ft.Column([
                            ft.Text(f"$ {float(pr.get('precio_dolares') or 0):,.2f}", size=11,
                                    weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_600),
                            ft.Text(f"Bs. {float(pr.get('monto_bcv_bolivares') or 0):,.2f}", size=10,
                                    color=ft.Colors.AMBER_700),
                        ], spacing=1, tight=True),
                        expand=self._PESO_COL_PRECIOS,
                    ),
                    ft.Container(
                        content=ft.Text(
                            f"Exist.: {existencia:,.2f}", size=10,
                            weight=ft.FontWeight.W_600,
                            color=ft.Colors.RED_400 if sin_stock else subtext,
                            no_wrap=False, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                        ),
                        expand=self._PESO_COL_EXISTENCIA,
                    ),
                    # Único elemento de ancho fijo de la fila: así el botón
                    # nunca se recorta contra el borde en ventanas angostas y
                    # son las columnas de texto las que ceden espacio (con
                    # elipsis) al repartirse el ancho restante.
                    ft.Container(
                        content=ft.TextButton(
                            content=ft.Row([ft.Icon(ft.Icons.ADD_SHOPPING_CART, size=14), ft.Text("Agregar", size=11, weight=ft.FontWeight.BOLD)], tight=True, spacing=4),
                            disabled=sin_stock,
                            tooltip="Sin existencia disponible" if sin_stock else f"Agregar {nombre} al carrito activo",
                            on_click=lambda ev, p=pr: self.handle_agregar_desde_resultado(ev, p),
                        ),
                        width=self._ANCHO_COL_AGREGAR,
                    ),
                ], vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=8),
                padding=ft.Padding.symmetric(horizontal=8, vertical=6),
                border_radius=10,
                bgcolor=ft.Colors.with_opacity(0.10, accent) if es_exacto else None,
            ))

        # Se nombra para poder apuntarle las flechas del teclado cuando el
        # carrito está vacío (ver `_destino_scroll_vertical`).
        lista_resultados = ft.Column(controls=filas, spacing=2, scroll=ft.ScrollMode.AUTO)
        self._resultados_scroll_v = lista_resultados

        pie: list[ft.Control] = []
        if len(resultados) >= self._LIMITE_RESULTADOS_BUSQUEDA:
            pie.append(ft.Text(
                f"Se muestran las primeras {self._LIMITE_RESULTADOS_BUSQUEDA} coincidencias; refine el término o el criterio.",
                size=10, color=subtext, italic=True,
                no_wrap=False, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS,
            ))

        return ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Text(
                        f"{len(resultados)} coincidencia(s) para '{termino}' — elija el artículo a agregar:",
                        size=11, weight=ft.FontWeight.W_600, color=accent, expand=True,
                        no_wrap=False, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                    ft.IconButton(
                        icon=ft.Icons.CLOSE, icon_size=16, icon_color=subtext,
                        tooltip="Cerrar resultados",
                        on_click=self.handle_limpiar_resultados,
                    ),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                # Único scroll vertical del panel, dentro de una altura acotada.
                ft.Container(
                    content=lista_resultados,
                    height=min(240, 46 * len(filas) + 8),
                ),
                *pie,
            ], spacing=6),
            padding=10,
            border_radius=12,
            bgcolor=self.get_card_bg(),
            border=ft.Border.all(1, self.get_border_color()),
        )

    def handle_limpiar_resultados(self, e):
        """Oculta y vacía el panel de resultados."""
        self._resultados_busqueda = []
        self._resultados_scroll_v = None
        if hasattr(self, "panel_resultados_container"):
            self.panel_resultados_container.content = None
            self.panel_resultados_container.visible = False
        p = self.get_current_page(e) or self._page_ref
        if p:
            p.update()
        else:
            self.safe_update(e)

    def _validar_stock_y_agregar(self, producto: dict, cantidad: float, e=None) -> bool:
        """Verifica la existencia contra lo que ya hay en el carrito activo y,
        si alcanza, agrega el producto. Devuelve si se agregó."""
        stock_disponible = float(producto.get("existencia") or 0.0)
        c_activo = obtener_carrito_activo(self._sid)
        cant_en_carrito = sum(
            item["cantidad"] for item in c_activo["items"] if item["codigo"] == producto["codigo"]
        )

        if (cant_en_carrito + cantidad) > stock_disponible:
            self.show_alert_error(
                e,
                f"Stock insuficiente para {producto['codigo']}.\n"
                f"Disponible: {stock_disponible:.2f} | En carrito: {cant_en_carrito:.2f}"
            )
            return False

        self.agregar_producto_directo(producto, cantidad, e)
        return True

    def handle_agregar_desde_resultado(self, e, producto: dict):
        """Botón "Agregar" de una fila del panel de resultados: agrega ese
        producto concreto con la cantidad indicada en la barra de búsqueda."""
        cantidad = self._leer_cantidad_solicitada(e)
        if cantidad is None:
            return
        if self._validar_stock_y_agregar(producto, cantidad, e):
            self.cant_input.value = "1"

    def handle_agregar_producto(self, e):
        """Botón "Agregar" de la barra: es el atajo explícito de agregar. Usa el
        mismo motor de búsqueda (criterio incluido) y solo agrega cuando la
        coincidencia es inequívoca: un único resultado, o una coincidencia
        exacta por código / código de barras (escáner). Si hay varias
        candidatas, NO adivina: muestra los resultados y pide elegir."""
        consulta = self._ejecutar_busqueda(e)
        if consulta is None:
            return
        termino, resultados = consulta

        cantidad = self._leer_cantidad_solicitada(e)
        if cantidad is None:
            return

        if not resultados:
            self._renderizar_resultados(termino, resultados, e)
            self.show_alert_error(e, f"No se encontró ningún producto para '{termino}'.")
            return

        prod_encontrado = resolver_coincidencia_exacta(termino, resultados)
        if prod_encontrado is None and len(resultados) == 1:
            prod_encontrado = resultados[0]

        if prod_encontrado is None:
            self._renderizar_resultados(termino, resultados, e)
            self.show_alert_error(
                e,
                f"{len(resultados)} productos coinciden con '{termino}'. "
                "Elija uno en la lista de resultados."
            )
            return

        if self._validar_stock_y_agregar(prod_encontrado, cantidad, e):
            self.prod_search_input.value = ""
            self.cant_input.value = "1"
            self.handle_limpiar_resultados(e)

    def abrir_modal_buscar_inventario(self, e):
        """Flujo Inverso (ERS 3.3): abre el Inventario en un modal con filtro de
        búsqueda; al seleccionar un producto, se retorna directamente a la
        línea de venta en curso (se agrega al carrito activo)."""
        p = self.get_current_page(e)
        if not p:
            return

        modo_vista_state = {"modo": "agrupado"}

        txt_busqueda = ft.TextField(
            label="Filtrar por código, referencia, descripción, marca o departamento",
            autofocus=True,
            border_radius=12,
            expand=True,
            prefix_icon=ft.Icons.SEARCH,
        )
        cant_modal_input = ft.TextField(
            label="Cant.", value=self.cant_input.value or "1", width=90,
            keyboard_type=ft.KeyboardType.NUMBER, text_align=ft.TextAlign.CENTER,
            border_radius=12,
        )
        self._enlazar_foco({
            "inventario_modal_busqueda": txt_busqueda,
            "inventario_modal_cantidad": cant_modal_input,
        })

        btn_modo_modal = ft.SegmentedButton(
            selected=[modo_vista_state["modo"]],
            segments=[
                ft.Segment(
                    value="separado",
                    label=ft.Text("Separado", size=10, weight=ft.FontWeight.W_600),
                    icon=ft.Icon(ft.Icons.VIEW_COLUMN_ROUNDED, size=14),
                ),
                ft.Segment(
                    value="agrupado",
                    label=ft.Text("Agrupado", size=10, weight=ft.FontWeight.W_600),
                    icon=ft.Icon(ft.Icons.VIEW_LIST_ROUNDED, size=14),
                ),
                ft.Segment(
                    value="tarjetas",
                    label=ft.Text("Tarjetas", size=10, weight=ft.FontWeight.W_600),
                    icon=ft.Icon(ft.Icons.GRID_VIEW_ROUNDED, size=14),
                ),
            ],
            on_change=lambda ev: _cambiar_modo(ev),
        )

        lista_resultados = ft.Column(spacing=8, scroll=ft.ScrollMode.AUTO, height=520)
        lbl_conteo = ft.Text("", size=11, color=self.get_subtext_color())

        def _cambiar_modo(ev):
            if ev.control.selected:
                modo_vista_state["modo"] = list(ev.control.selected)[0]
                _refrescar(ev)

        def _agregar_desde_modal(prod: dict, ev):
            try:
                cant = float(cant_modal_input.value or "1")
                if cant <= 0:
                    cant = 1.0
            except ValueError:
                cant = 1.0
            dlg.open = False
            self._liberar_foco()
            self.safe_update(ev)
            self.agregar_producto_directo(prod, cant, ev)

        def _refrescar(ev=None):
            termino = (txt_busqueda.value or "").strip()
            productos = listar_productos(busqueda=termino, per_page=50) if termino else listar_productos(per_page=50)
            lbl_conteo.value = f"{len(productos)} resultado(s)"
            modo = modo_vista_state["modo"]

            if not productos:
                lista_resultados.controls = [
                    ft.Text("No se encontraron productos.", color=self.get_subtext_color())
                ]
            elif modo == "tarjetas":
                tarjetas = []
                for pr in productos:
                    t = ft.Container(
                        content=ft.Column([
                            ft.Row([
                                ft.Text(f"Código: {pr['codigo']}", size=11, weight=ft.FontWeight.BOLD, color=self.get_accent_color()),
                                ft.Container(
                                    content=ft.Text(f"Stock: {pr['existencia']:.0f}", size=10, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                                    bgcolor=ft.Colors.GREEN_700 if pr['existencia'] > 0 else ft.Colors.RED_700,
                                    padding=ft.Padding.symmetric(horizontal=6, vertical=2),
                                    border_radius=8,
                                )
                            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                            ft.Text(pr.get("descripcion_general") or pr.get("referencia") or pr["codigo"],
                                    size=13, weight=ft.FontWeight.BOLD, color=self.get_text_color(), max_lines=2),
                            ft.Text(f"Ref: {pr.get('referencia') or '-'} | {pr.get('departamento','-')} / {pr.get('marca','-')}", size=11, color=self.get_subtext_color()),
                            ft.Row([
                                ft.Text(f"${pr['precio_dolares']:.2f} (Efvo)", size=11, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_600),
                                ft.Text(f"${pr.get('precio_bcv',0):.2f} (BCV)", size=11, weight=ft.FontWeight.BOLD, color=ft.Colors.CYAN_600),
                                ft.Text(f"Bs {pr.get('monto_bcv_bolivares',0):,.2f}", size=11, weight=ft.FontWeight.BOLD, color=ft.Colors.AMBER_700),
                            ], spacing=8, wrap=True),
                            ft.FilledButton(
                                content=ft.Row([ft.Icon(ft.Icons.ADD_SHOPPING_CART, size=16), ft.Text("Agregar")], tight=True),
                                style=ft.ButtonStyle(bgcolor=ft.Colors.GREEN_700, color=ft.Colors.WHITE),
                                on_click=lambda ev2, prod=pr: _agregar_desde_modal(prod, ev2),
                            ),
                        ], spacing=4),
                        padding=10, border_radius=10, width=280,
                        bgcolor=self.get_card_bg(),
                        border=ft.Border.all(1, self.get_border_color()),
                    )
                    tarjetas.append(t)
                lista_resultados.controls = [ft.Row(controls=tarjetas, wrap=True, spacing=8)]

            elif modo == "separado":
                items = []
                for pr in productos:
                    items.append(
                        ft.Container(
                            content=ft.Row([
                                ft.Text(pr["codigo"], size=12, color=self.get_accent_color(), weight=ft.FontWeight.W_600, width=90),
                                ft.Text(pr.get("referencia") or "-", size=12, color=self.get_subtext_color(), width=90),
                                ft.Text(pr.get("descripcion_general") or "-", size=12, color=self.get_text_color(), width=220, max_lines=1),
                                ft.Text(pr.get("departamento") or "-", size=12, color=self.get_subtext_color(), width=100),
                                ft.Text(pr.get("marca") or "-", size=12, color=self.get_subtext_color(), width=90),
                                ft.Text(f"${pr['precio_dolares']:.2f}", size=12, color=ft.Colors.GREEN_600, weight=ft.FontWeight.BOLD, width=80),
                                ft.Text(f"Stock: {pr['existencia']:.0f}", size=12, color=self.get_subtext_color(), width=80),
                                ft.IconButton(
                                    icon=ft.Icons.ADD_SHOPPING_CART, icon_color=ft.Colors.GREEN_600, icon_size=24,
                                    tooltip="Agregar a la venta", on_click=lambda ev2, prod=pr: _agregar_desde_modal(prod, ev2),
                                ),
                            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                            padding=8, border_radius=8, bgcolor=self.get_card_bg(), border=ft.Border.all(1, self.get_border_color()),
                        )
                    )
                lista_resultados.controls = items

            else:  # agrupado (default)
                items = []
                for pr in productos:
                    items.append(
                        ft.Container(
                            content=ft.Row(
                                controls=[
                                    ft.Column([
                                        ft.Text(
                                            pr.get("descripcion_general") or pr.get("referencia") or pr["codigo"],
                                            weight=ft.FontWeight.BOLD, color=self.get_text_color(), size=15,
                                            no_wrap=False,
                                        ),
                                        ft.Text(f"Código: {pr['codigo']}  ·  Ref: {pr.get('referencia') or '-'}  ·  {pr.get('departamento','-')} / {pr.get('marca') or '-'}", size=12, color=self.get_subtext_color()),
                                        ft.Row([
                                            ft.Text(f"$ {pr['precio_dolares']:.2f} (Efvo.)", size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_600),
                                            ft.Text(f"$ {pr.get('precio_bcv', 0):.2f} (BCV)", size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.CYAN_600),
                                            ft.Text(f"Bs {pr.get('monto_bcv_bolivares', 0):,.2f}", size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.AMBER_700),
                                            ft.Text(f"Stock: {pr['existencia']:.0f}", size=13, color=self.get_subtext_color()),
                                        ], spacing=14, wrap=True),
                                    ], spacing=3, tight=True, expand=True),
                                    ft.IconButton(
                                        icon=ft.Icons.ADD_SHOPPING_CART, icon_color=ft.Colors.GREEN_600,
                                        icon_size=28,
                                        tooltip="Agregar a la venta en curso",
                                        on_click=lambda ev2, prod=pr: _agregar_desde_modal(prod, ev2),
                                    ),
                                ],
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                            padding=12, border_radius=10, bgcolor=self.get_card_bg(),
                            border=ft.Border.all(1, self.get_border_color()),
                        )
                    )
                lista_resultados.controls = items

            self.safe_update(ev)

        txt_busqueda.on_change = _refrescar

        def cerrar(ev):
            dlg.open = False
            self._liberar_foco()
            self.safe_update(ev)

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Row([
                    ft.Icon(ft.Icons.INVENTORY_2_ROUNDED, color=self.get_accent_color()),
                    ft.Text("Buscar en Inventario", weight=ft.FontWeight.BOLD),
                ], spacing=8),
                btn_modo_modal,
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            content=ft.Container(
                content=ft.Column([
                    ft.Row([txt_busqueda, cant_modal_input], spacing=10),
                    ft.Row([
                        lbl_conteo,
                        build_scroll_nav(lista_resultados, "vertical", self.get_accent_color(), tooltip_prefix="Resultados: "),
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    ft.Divider(height=4),
                    lista_resultados,
                ], spacing=8, tight=True),
                width=980,
                height=680,
            ),
            actions=[ft.TextButton("Cerrar", on_click=cerrar)],
        )

        _refrescar()
        if dlg not in p.overlay:
            p.overlay.append(dlg)
        dlg.open = True
        p.update()
        p.update()

    def handle_ajustar_cantidad(self, e, item: dict, delta: float):
        """Stepper +/- en línea de la tabla del carrito: suma/resta 1 unidad
        sin necesidad de abrir el diálogo de edición. Si la cantidad llega a
        0 o menos, remueve el renglón."""
        # Revalidación de la regla del marcador: el botón ya viene
        # deshabilitado, pero la regla también tiene que valer para quien
        # llegue por código (y los +/- son de lo que el renglón acciona).
        if not self._seleccion.puede_accionar(item["codigo"]):
            self.show_alert_info(e, self._AVISO_OTRO_MARCADO)
            return
        nueva_cant = item["cantidad"] + delta
        if nueva_cant <= 0:
            self.handle_remover_item(e, item["codigo"])
            return
        editar_item_en_carrito(self._sid, item["codigo"], nueva_cant, item["precio_usd"], tasa_bcv=self.tasa_bcv)
        self._refrescar_carrito_y_resumen(e)

    def handle_remover_item(self, e, codigo):
        remover_item_de_carrito(self._sid, codigo)
        self.show_alert_info(e, f"Producto '{codigo}' removido del carrito.")
        self._refrescar_carrito_y_resumen(e)

    def handle_abrir_modal_editar_item(self, item: dict, e=None):
        """Diálogo para editar la cantidad o el precio de un renglón.

        Es lo que ejecuta F5 sobre el renglón marcado, además del botón de
        editar de la fila: los dos entran por `ejecutar_accion_item`.
        """
        p = self._pagina_actual(e)
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
            label="Precio Unit. Efectivo ($)",
            value=f"{item['precio_usd']:.2f}",
            keyboard_type=ft.KeyboardType.NUMBER,
            width=170,
            border_radius=12
        )
        # Precio USD BCV: independiente del Efectivo (regla de negocio
        # Venezuela — suele ser más alto, es el que se usa para calcular el
        # monto en Bolívares). Antes este diálogo no lo exponía y al guardar
        # (aunque solo fuera para cambiar la cantidad) lo igualaba
        # silenciosamente al precio Efectivo, rompiendo el cálculo en Bs.
        txt_precio_bcv = ft.TextField(
            label="Precio Unit. BCV ($)",
            value=f"{item.get('precio_usd_bcv_ref', item['precio_usd']):.2f}",
            keyboard_type=ft.KeyboardType.NUMBER,
            width=170,
            border_radius=12
        )
        self._enlazar_foco({
            "editar_renglon_cantidad": txt_cant,
            "editar_renglon_precio_usd": txt_precio_usd,
            "editar_renglon_precio_bcv": txt_precio_bcv,
        })
        lbl_err = ft.Text("", color=ft.Colors.RED_500, size=12, weight=ft.FontWeight.BOLD)

        def guardar_cambios(e_save):
            lbl_err.value = ""
            try:
                n_cant = float(txt_cant.value.strip().replace(",", "."))
                n_precio = float(txt_precio_usd.value.strip().replace(",", "."))
                n_precio_bcv = float(txt_precio_bcv.value.strip().replace(",", "."))
                if n_cant <= 0 or n_precio <= 0 or n_precio_bcv <= 0:
                    raise ValueError("Los valores deben ser mayores a cero.")

                editar_item_en_carrito(self._sid, item["codigo"], n_cant, n_precio, n_precio_bcv, tasa_bcv=self.tasa_bcv)
                self._close_dialog(e_save, dialog=dlg)
                self.show_alert_success(e_save, f"Renglón '{item['codigo']}' actualizado.")
                self._refrescar_carrito_y_resumen(e_save)
            except ValueError as ex:
                lbl_err.value = str(ex) if str(ex) else "Ingrese valores numéricos válidos."
                p.update()

        def cerrar(e_close):
            self._close_dialog(e_close, dialog=dlg)

        dlg = ft.AlertDialog(
            title=ft.Row([
                ft.Icon(ft.Icons.EDIT_NOTE, color=self.get_accent_color()),
                ft.Text(f"Editar Renglón: {item['nombre_corto']}", weight=ft.FontWeight.BOLD, size=15)
            ], spacing=10),
            content=ft.Container(
                content=ft.Column([
                    ft.Text(f"Código: {item['codigo']}", size=12, color=self.get_subtext_color()),
                    ft.Divider(height=10),
                    txt_cant,
                    ft.Row([txt_precio_usd, txt_precio_bcv], spacing=10),
                    lbl_err
                ], spacing=10, tight=True),
                width=400,
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

        # Pila nativa de Flet 0.86 (`show_dialog`/`pop_dialog`) y no el patrón
        # heredado de `page.overlay` + bandera `open`: con ese patrón esta
        # versión no llega a dibujar el cierre y el diálogo se queda pegado, o
        # sigue activo pero invisible recibiendo clics sobre botones que el
        # usuario ya no ve (el resto de los diálogos de esta vista se migraron
        # antes por lo mismo).
        self._dlg_editar_item = dlg
        self._open_dialog(dlg, e)

    # ─────────────────────────────────────────────────────────────────────────
    # MARCADOR DEL RENGLÓN DEL CARRITO (Nueva Función 3, extendida a Ventas)
    # ─────────────────────────────────────────────────────────────────────────
    # Mecánica pedida por el usuario del proyecto, idéntica a la del
    # Inventario para que la misma lista se comporte igual en los dos módulos:
    #   - Un clic en cualquier parte del renglón lo marca: se sombrea y la
    #     casilla de la izquierda queda marcada, y sigue marcado al
    #     desplazarse a la derecha de la tabla (el sombreado se deriva del
    #     modelo, no de una bandera local, así que sobrevive al repintado).
    #   - Solo hay DOS formas de desmarcar: el clic DENTRO de la casilla
    #     marcada y la tecla [Esc].
    #   - Con un renglón marcado, solo ese renglón puede accionar sus botones;
    #     los de los demás quedan deshabilitados VISIBLEMENTE.
    #   - SIN NADA MARCADO TODO FUNCIONA COMO ANTES: los botones de todos los
    #     renglones siguen activos. Es la regla "Importante" del PDF y la más
    #     fácil de romper al cablear la vista.

    def _sincronizar_seleccion(self, items: list) -> None:
        """Olvida los códigos marcados que ya no están en el carrito.

        Sin esto, quitar el renglón marcado (o cambiar de carrito activo)
        dejaría una selección FANTASMA: un código que no se puede desmarcar
        con el mouse porque su casilla ya no se dibuja, y que mientras exista
        deshabilita los botones de todos los renglones vivos.
        """
        codigos = {str(item["codigo"]).strip() for item in items}
        fantasmas = [c for c in self._seleccion.seleccionados if c not in codigos]
        if fantasmas:
            self._seleccion.descartar(fantasmas)

    def seleccionar_item(self, codigo: str, e=None):
        """Clic en cualquier parte del renglón: marca (nunca desmarca)."""
        # Reintento de enganche: si la vista se construyó antes de tener
        # página, este es el primer momento con un evento en la mano, y es
        # justo cuando [Esc] y F1–F6 empiezan a tener sentido.
        self._asegurar_teclado(e)
        if self._seleccion.seleccionar(codigo):
            self._refrescar_carrito_y_resumen(e)

    def alternar_item(self, codigo: str, e=None):
        """Clic DENTRO de la casilla marcadora: marca o desmarca.

        Es la primera de las dos únicas formas de deseleccionar que admite la
        especificación (la otra es [Esc], que entra por `limpiar_seleccion`).
        """
        self._asegurar_teclado(e)
        if self._seleccion.alternar(codigo):
            self._refrescar_carrito_y_resumen(e)

    def limpiar_seleccion(self, e=None):
        """Quita la marca (tecla [Esc]). Es el `al_limpiar` del control de
        teclado, así que recibe el evento de teclado como `e`."""
        if self._seleccion.limpiar():
            self._refrescar_carrito_y_resumen(e)

    # El repintado NO se cuelga de `SeleccionLista.on_cambio` (como sí hace el
    # Inventario) porque ese callback no recibe argumentos y aquí el repintado
    # necesita el evento: `_refrescar_carrito_y_resumen` resuelve la página a
    # partir de `e` y sin ella no llama a `page.update()` — los cálculos
    # quedarían bien y la pantalla no mostraría ningún cambio. Los tres
    # métodos de arriba son los únicos que mutan la selección, así que
    # repintar en ellos cubre todos los caminos.

    _AVISO_OTRO_MARCADO = (
        "Hay otro renglón marcado. Haga clic en su casilla o pulse Esc para liberarlo."
    )

    # ─────────────────────────────────────────────────────────────────────────
    # ACCIONES DEL RENGLÓN (los botones de la fila y los atajos F1–F6)
    # ─────────────────────────────────────────────────────────────────────────
    # Mapeo CANÓNICO (`ATAJOS_ITEM`), por decisión explícita del usuario del
    # proyecto: la misma tecla hace lo mismo en todas las listas, y las teclas
    # que no tienen un ícono equivalente en el carrito quedan INERTES. Se
    # prefirió eso a inventarle un mapeo propio al carrito (se descartó
    # expresamente mapear F3/F4 a subir/bajar cantidad): una tecla que cambia
    # de significado según la lista en la que esté el usuario no se aprende.
    #   F5 = editar el renglón · F6 = quitarlo del carrito
    #   F1 (info), F2 (cobrar), F3 (carrito) y F4 (historial) no hacen nada.
    #
    # Por qué F6 NO pide la clave del usuario, aunque "borrar" figure en
    # `teclado_nav.ACCIONES_CON_CLAVE`: quitar un renglón de un carrito no
    # borra ningún dato del sistema, solo saca un artículo de una venta que
    # todavía no se procesó (nada se registró, nada se puede perder). La clave
    # quedó reservada al borrado de ítems del inventario y de deudas, que sí
    # destruyen información persistida.
    ACCIONES_RENGLON = ("editar", "borrar")

    def _item_del_carrito(self, codigo: str) -> dict | None:
        """Renglón del carrito activo por su código, o `None` si ya no está.

        Se relee el carrito en vez de usar el `dict` que capturó el clic: un
        atajo de teclado actúa sobre el código marcado y la copia que tuviera
        la fila pintada puede ser de antes del último repintado.
        """
        codigo = str(codigo or "").strip()
        if not codigo:
            return None
        items = obtener_carrito_activo(self._sid)["items"]
        return next((i for i in items if str(i["codigo"]).strip() == codigo), None)

    def accion_editar(self, item: dict, e=None):
        self.handle_abrir_modal_editar_item(item, e)

    def accion_borrar(self, item: dict, e=None):
        self.handle_remover_item(e, item["codigo"])

    def _handlers_accion_renglon(self) -> dict:
        return {
            "editar": self.accion_editar,
            "borrar": self.accion_borrar,
        }

    def ejecutar_accion_item(self, accion: str, codigo: str, e=None) -> bool:
        """Punto de entrada ÚNICO de los botones del renglón y de los atajos.

        Que el mouse y el teclado recorran exactamente el mismo camino no es
        elegancia: dos caminos distintos para la misma acción divergen en
        cuanto alguien toque uno de los dos (una validación nueva en el botón
        que la tecla se saltea, por ejemplo).

        Revalida `puede_accionar` aunque el botón ya venga deshabilitado,
        porque la regla también tiene que valer para quien llegue por teclado
        o por código. Devuelve `False` cuando la acción no aplica.
        """
        if accion not in ATAJOS_ITEM.values():
            raise ValueError(f"Acción de renglón desconocida: {accion!r}")
        handler = self._handlers_accion_renglon().get(accion)
        if handler is None:
            return False  # F1–F4: inertes en el carrito (ver nota de arriba).
        item = self._item_del_carrito(codigo)
        if item is None:
            return False
        if not self._seleccion.puede_accionar(codigo):
            self.show_alert_info(e, self._AVISO_OTRO_MARCADO)
            return False
        handler(item, e)
        return True

    def ejecutar_accion_sobre_seleccionado(self, accion: str, e=None) -> bool:
        """La misma acción, aplicada al renglón marcado: es lo que invocan
        F1–F6. Sin nada marcado no hace nada (y no adivina un renglón: una
        tecla que actúa sobre algo que el usuario no eligió es una trampa)."""
        codigo = self._seleccion.seleccionado
        if not codigo:
            return False
        return self.ejecutar_accion_item(accion, codigo, e)

    def _columnas_carrito_orden_visible(self) -> list[str]:
        """Orden fijo de columnas, filtrando las ocultables que el usuario desactivó.

        "marcador" va SIEMPRE primero y "acciones" siempre al final: ninguna
        de las dos es ocultable (ver `_COLUMNAS_CARRITO_OCULTABLES`).
        """
        return (
            ["marcador"]
            + [k for k in self._columnas_carrito_ocultables if self._columnas_carrito_visibles.get(k, True)]
            + ["acciones"]
        )

    def _toggle_columna_carrito(self, key: str, e=None):
        visibles_actuales = [k for k in self._columnas_carrito_ocultables if self._columnas_carrito_visibles.get(k, True)]
        if self._columnas_carrito_visibles[key] and len(visibles_actuales) <= 1:
            self.show_alert_error(e, "Debe quedar al menos una columna visible.")
            return
        self._columnas_carrito_visibles[key] = not self._columnas_carrito_visibles[key]
        self.rebuild_ui()

    def _build_selector_columnas_carrito(self) -> ft.PopupMenuButton:
        items = [
            ft.PopupMenuItem(
                content=self._columnas_carrito_labels[key],
                checked=self._columnas_carrito_visibles[key],
                on_click=lambda e, k=key: self._toggle_columna_carrito(k, e),
            )
            for key in self._columnas_carrito_ocultables
        ]
        return ft.PopupMenuButton(
            icon=ft.Icons.VIEW_COLUMN_ROUNDED,
            icon_color=self.get_accent_color(),
            tooltip="Mostrar/ocultar columnas",
            items=items,
        )

    def build_tabla_carrito(self, items: list) -> ft.Control:
        # Antes de dibujar: la marca tiene que referirse a un renglón que
        # exista (ver `_sincronizar_seleccion`).
        self._sincronizar_seleccion(items)

        if not items:
            # Carrito vacío: no hay tabla, así que tampoco destinos de scroll.
            # Dejarlos apuntando a los controles del pintado anterior haría
            # que las flechas desplazaran un control ya desmontado.
            self._carrito_scroll_h = None
            self._carrito_scroll_v = None
            return self.create_card(
                content=ft.Column([
                    ft.Icon(ft.Icons.SHOPPING_CART_OUTLINED, size=64, color=self.get_accent_color()),
                    ft.Text("CARRITO DE COMPRAS VACÍO", size=15, weight=ft.FontWeight.BOLD, color=self.get_text_color()),
                    ft.Text("Seleccione un producto arriba o use las recomendaciones rápidas para añadir ítems.", size=12, color=self.get_subtext_color(), text_align=ft.TextAlign.CENTER)
                ], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10),
                padding=40,
                border_radius=16,
                height=440,
            )

        accent = self.get_accent_color()
        text_color = self.get_text_color()
        subtext = self.get_subtext_color()
        border = self.get_border_color()
        card_bg = self.get_card_bg()

        def boton_accion(accion: str, item: dict, icono, color, descripcion: str):
            """Botón del renglón, cableado al punto de entrada único
            (`ejecutar_accion_item`) para que la tecla y el mouse recorran
            exactamente el mismo camino.

            `disabled` es la mitad VISIBLE de la regla del marcador: con otro
            renglón marcado el botón se ve apagado y el tooltip dice por qué,
            en vez de aceptar el clic y no hacer nada (un botón que ignora en
            silencio se lee como un cuelgue de la aplicación).
            """
            cod = item["codigo"]
            habilitado = self._seleccion.puede_accionar(cod)
            return ft.IconButton(
                icon=icono,
                icon_color=color if habilitado else subtext,
                disabled=not habilitado,
                tooltip=descripcion if habilitado else f"{descripcion} — {self._AVISO_OTRO_MARCADO}",
                on_click=lambda e, a=accion, c=cod: self.ejecutar_accion_item(a, c, e),
            )

        def celda_acciones(item, cod):
            return ft.Row([
                boton_accion("editar", item, ft.Icons.EDIT_OUTLINED, accent, "Editar cantidad o precio"),
                boton_accion("borrar", item, ft.Icons.DELETE_OUTLINED, ft.Colors.RED_400, "Remover ítem"),
            ], spacing=0)

        def celda_cantidad(item):
            # Los +/- son parte de lo que el renglón puede accionar, así que
            # siguen la misma regla que los botones de la columna "Acciones":
            # con otro renglón marcado quedan apagados y explicados.
            habilitado = self._seleccion.puede_accionar(item["codigo"])
            sufijo = "" if habilitado else f" — {self._AVISO_OTRO_MARCADO}"
            return ft.Row([
                ft.IconButton(
                    icon=ft.Icons.REMOVE_CIRCLE_OUTLINE, icon_size=18,
                    icon_color=subtext,
                    tooltip=f"Restar 1{sufijo}",
                    disabled=not habilitado,
                    style=ft.ButtonStyle(padding=2),
                    on_click=lambda e, it=item: self.handle_ajustar_cantidad(e, it, -1),
                ),
                ft.Text(f"{item['cantidad']:.2f}", color=text_color, weight=ft.FontWeight.W_600, width=48, text_align=ft.TextAlign.CENTER),
                ft.IconButton(
                    icon=ft.Icons.ADD_CIRCLE_OUTLINE, icon_size=18,
                    icon_color=accent if habilitado else subtext,
                    tooltip=f"Sumar 1{sufijo}",
                    disabled=not habilitado,
                    style=ft.ButtonStyle(padding=2),
                    on_click=lambda e, it=item: self.handle_ajustar_cantidad(e, it, 1),
                ),
            ], spacing=0, tight=True)

        # ── Casilla marcadora y sombreado del renglón ────────────────────────
        def celda_marcador(item) -> ft.Control:
            marcado = self._seleccion.esta_seleccionado(item["codigo"])
            return ft.Container(
                content=ft.Icon(
                    ft.Icons.RADIO_BUTTON_CHECKED if marcado else ft.Icons.RADIO_BUTTON_UNCHECKED,
                    color=accent if marcado else subtext,
                    size=20,
                ),
                width=34,
                alignment=ft.Alignment.CENTER,
                tooltip=(
                    "Clic para quitar la marca de este renglón"
                    if marcado else "Clic para marcar este renglón"
                ),
            )

        def celda_marcador_dc(item) -> ft.DataCell:
            """La casilla atiende su propio toque: es la única celda de la fila
            que DESMARCA (`alternar`), mientras el resto del renglón solo
            marca."""
            return ft.DataCell(
                celda_marcador(item),
                on_tap=lambda e, cod=item["codigo"]: self.alternar_item(cod, e),
            )

        def construir_fila(item, celdas: list[ft.DataCell], color_base=None) -> ft.DataRow:
            marcado = self._seleccion.esta_seleccionado(item["codigo"])
            return ft.DataRow(
                cells=celdas,
                selected=marcado,
                # Sombreado derivado del MODELO y no de una bandera local: por
                # eso sobrevive al repintado de la tabla y al desplazamiento
                # horizontal (el renglón sigue sombreado al llegar a la
                # columna de acciones).
                color=ft.Colors.with_opacity(0.22, accent) if marcado else color_base,
                # Hace sensible al clic el renglón COMPLETO ("no importa si es
                # fuera de la casilla"); la celda del marcador tiene su propio
                # `on_tap` y por eso no cae aquí.
                on_select_change=lambda e, cod=item["codigo"]: self.seleccionar_item(cod, e),
                data=item["codigo"],
            )

        modo = VentasView._modo_vista_carrito_estatico

        btn_modo_vista = ft.SegmentedButton(
            selected=[modo],
            segments=[
                ft.Segment(
                    value="separado",
                    label=ft.Text("Separado", size=10, weight=ft.FontWeight.W_600),
                    icon=ft.Icon(ft.Icons.VIEW_COLUMN_ROUNDED, size=14),
                ),
                ft.Segment(
                    value="agrupado",
                    label=ft.Text("Agrupado", size=10, weight=ft.FontWeight.W_600),
                    icon=ft.Icon(ft.Icons.VIEW_LIST_ROUNDED, size=14),
                ),
                ft.Segment(
                    value="tarjetas",
                    label=ft.Text("Tarjetas", size=10, weight=ft.FontWeight.W_600),
                    icon=ft.Icon(ft.Icons.GRID_VIEW_ROUNDED, size=14),
                ),
            ],
            on_change=self._handle_cambio_modo_vista_carrito,
        )

        if modo == "separado":
            columnas_clave = self._columnas_carrito_orden_visible()
            constructores_celda = {
                "marcador": celda_marcador,
                "codigo": lambda item: ft.Text(item["codigo"], weight=ft.FontWeight.BOLD, color=text_color),
                "producto": lambda item: ft.Text(item["nombre_corto"], color=text_color),
                "cantidad": celda_cantidad,
                "precio_usd": lambda item: ft.Text(f"$ {item['precio_usd']:,.2f}", color=ft.Colors.GREEN_600, weight=ft.FontWeight.BOLD),
                "precio_bs": lambda item: ft.Column([
                    ft.Text(f"Bs. {item['precio_bcv']:,.2f}", color=ft.Colors.AMBER_700, weight=ft.FontWeight.BOLD, size=11),
                    ft.Text(f"Ref BCV: ${item.get('precio_usd_bcv_ref', item['precio_usd']):,.2f}", color=ft.Colors.CYAN_600, size=10),
                ], spacing=1, tight=True),
                "subtotal": lambda item: ft.Column([
                    ft.Text(f"$ {item['subtotal_usd']:,.2f} (Efvo)", weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_600, size=11),
                    ft.Text(f"Bs. {item['subtotal_bcv']:,.2f}", weight=ft.FontWeight.BOLD, color=ft.Colors.AMBER_700, size=11),
                ], spacing=1, tight=True),
                "acciones": lambda item: celda_acciones(item, item["codigo"]),
            }

            zebra_bg = "#1B2331" if self.is_dark else "#F8FAFC"
            filas = [
                construir_fila(
                    item,
                    [
                        celda_marcador_dc(item) if k == "marcador"
                        else ft.DataCell(constructores_celda[k](item))
                        for k in columnas_clave
                    ],
                    # El cebreado es el fondo por omisión del renglón: el
                    # sombreado del marcador lo reemplaza cuando está marcado.
                    color_base=zebra_bg if idx % 2 == 1 else None,
                )
                for idx, item in enumerate(items)
            ]

            header_color = "#273549" if self.is_dark else "#F1F5F9"
            dt = ft.DataTable(
                columns=[
                    ft.DataColumn(ft.Text(self._columnas_carrito_labels[k], color=text_color, weight=ft.FontWeight.BOLD))
                    for k in columnas_clave
                ],
                rows=filas,
                heading_row_color=header_color,
                divider_thickness=1,
                horizontal_lines=ft.BorderSide(1, border),
                # Explícito: todas las filas llevan `on_select_change`, y con
                # la columna de casillas propia de la tabla activada Flet
                # dibujaría una SEGUNDA casilla junto a nuestro marcador.
                show_checkbox_column=False,
            )
            tabla_scroll_row = ft.Row(controls=[dt], scroll=ft.ScrollMode.ALWAYS)
            tabla_scroll_col = ft.Column(controls=[tabla_scroll_row], scroll=ft.ScrollMode.ALWAYS, height=304)
            # Destinos de las flechas del teclado: EXACTAMENTE los mismos
            # controles que mueven los botones de flecha de la barra, para que
            # la tecla y el clic desplacen lo mismo.
            self._carrito_scroll_h = tabla_scroll_row
            self._carrito_scroll_v = tabla_scroll_col
            contenido_vista = ft.Column([
                ft.Row([
                    ft.Container(expand=True),
                    build_scroll_nav(tabla_scroll_row, "horizontal", accent, tooltip_prefix="Carrito: "),
                ]),
                tabla_scroll_col,
            ], spacing=6)

        elif modo == "agrupado":
            filas = []
            for item in items:
                precio_bcv_ref = item.get("precio_usd_bcv_ref", item["precio_usd"])
                subtotal_bcv_usd = round(item["cantidad"] * precio_bcv_ref, 2)

                celda_prod = ft.Container(
                    content=ft.Column([
                        ft.Text(item["nombre_corto"], size=13, weight=ft.FontWeight.BOLD, color=text_color, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                        ft.Container(
                            content=ft.Text(f"Cód: {item['codigo']}", size=11, weight=ft.FontWeight.W_600, color=accent),
                            bgcolor=ft.Colors.with_opacity(0.12, accent),
                            padding=ft.Padding.symmetric(horizontal=6, vertical=2),
                            border_radius=6,
                        ),
                    ], spacing=3, tight=True),
                    width=210,
                    padding=ft.Padding.symmetric(vertical=4),
                )

                celda_precios = ft.Container(
                    content=ft.Column([
                        ft.Text(f"${item['precio_usd']:.2f} (Efvo)", size=11, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_600),
                        ft.Text(f"${precio_bcv_ref:.2f} (BCV)", size=10, color=ft.Colors.CYAN_600),
                        ft.Text(f"Bs {item['precio_bcv']:,.2f}", size=11, weight=ft.FontWeight.W_600, color=ft.Colors.AMBER_700),
                    ], spacing=1, tight=True),
                    width=150,
                    padding=ft.Padding.symmetric(vertical=4),
                )

                celda_cant = ft.Container(content=celda_cantidad(item), width=110, padding=ft.Padding.symmetric(vertical=4))

                celda_subtotales = ft.Container(
                    content=ft.Column([
                        ft.Text(f"${item['subtotal_usd']:.2f} (Efvo)", size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_600),
                        ft.Text(f"${subtotal_bcv_usd:.2f} (BCV)", size=10, color=ft.Colors.CYAN_600),
                        ft.Text(f"Bs {item['subtotal_bcv']:,.2f}", size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.AMBER_700),
                    ], spacing=1, tight=True),
                    width=160,
                    padding=ft.Padding.symmetric(vertical=4),
                )

                celda_acc = ft.Container(content=celda_acciones(item, item["codigo"]), width=90, padding=ft.Padding.symmetric(vertical=4))

                filas.append(
                    construir_fila(item, [
                        celda_marcador_dc(item),
                        ft.DataCell(celda_prod),
                        ft.DataCell(celda_precios),
                        ft.DataCell(celda_cant),
                        ft.DataCell(celda_subtotales),
                        ft.DataCell(celda_acc),
                    ])
                )

            dt = ft.DataTable(
                columns=[
                    ft.DataColumn(ft.Text(self._columnas_carrito_labels["marcador"], color=text_color, weight=ft.FontWeight.BOLD)),
                    ft.DataColumn(ft.Text("Producto", color=text_color, weight=ft.FontWeight.BOLD)),
                    ft.DataColumn(ft.Text("Precios Unit.", color=text_color, weight=ft.FontWeight.BOLD)),
                    ft.DataColumn(ft.Text("Cant.", color=text_color, weight=ft.FontWeight.BOLD)),
                    ft.DataColumn(ft.Text("Subtotales", color=accent, weight=ft.FontWeight.BOLD)),
                    ft.DataColumn(ft.Text("Acciones", color=accent, weight=ft.FontWeight.BOLD)),
                ],
                rows=filas,
                data_row_min_height=72,
                data_row_max_height=95,
                # Ver la nota del modo "separado": con `on_select_change` en
                # las filas, Flet añadiría su propia columna de casillas.
                show_checkbox_column=False,
            )
            tabla_scroll_row = ft.Row(controls=[dt], scroll=ft.ScrollMode.ALWAYS)
            tabla_scroll_col = ft.Column(controls=[tabla_scroll_row], scroll=ft.ScrollMode.ALWAYS, height=304)
            # Destinos de las flechas del teclado: EXACTAMENTE los mismos
            # controles que mueven los botones de flecha de la barra, para que
            # la tecla y el clic desplacen lo mismo.
            self._carrito_scroll_h = tabla_scroll_row
            self._carrito_scroll_v = tabla_scroll_col
            contenido_vista = ft.Column([
                ft.Row([
                    ft.Container(expand=True),
                    build_scroll_nav(tabla_scroll_row, "horizontal", accent, tooltip_prefix="Carrito: "),
                ]),
                tabla_scroll_col,
            ], spacing=6)

        else:  # modo == "tarjetas"
            tarjetas = []
            for item in items:
                precio_bcv_ref = item.get("precio_usd_bcv_ref", item["precio_usd"])
                subtotal_bcv_usd = round(item["cantidad"] * precio_bcv_ref, 2)
                marcado = self._seleccion.esta_seleccionado(item["codigo"])
                t = ft.Container(
                    content=ft.Column([
                        ft.Row([
                            # La casilla también va en las tarjetas: sin ella,
                            # en este modo el renglón solo se podría desmarcar
                            # con [Esc] y la mitad de la mecánica quedaría
                            # fuera del alcance del mouse.
                            ft.Container(
                                content=celda_marcador(item),
                                on_click=lambda e, cod=item["codigo"]: self.alternar_item(cod, e),
                            ),
                            ft.Text(f"Cód: {item['codigo']}", size=11, weight=ft.FontWeight.BOLD, color=accent),
                            celda_cantidad(item),
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        ft.Divider(height=4),
                        ft.Text(item["nombre_corto"], size=13, weight=ft.FontWeight.BOLD, color=text_color, max_lines=2),
                        ft.Row([
                            ft.Column([
                                ft.Text("P. Unit. Efvo ($)", size=9, color=subtext),
                                ft.Text(f"${item['precio_usd']:.2f}", size=11, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_600),
                            ], spacing=0),
                            ft.Column([
                                ft.Text("P. Unit. BCV ($)", size=9, color=subtext),
                                ft.Text(f"${precio_bcv_ref:.2f}", size=11, color=ft.Colors.CYAN_600),
                            ], spacing=0),
                            ft.Column([
                                ft.Text("P. Unit. (Bs)", size=9, color=subtext),
                                ft.Text(f"Bs {item['precio_bcv']:,.2f}", size=11, weight=ft.FontWeight.BOLD, color=ft.Colors.AMBER_700),
                            ], spacing=0),
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        ft.Divider(height=4),
                        ft.Row([
                            ft.Column([
                                ft.Text("Subtotal Efvo", size=9, color=subtext),
                                ft.Text(f"${item['subtotal_usd']:.2f}", size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_600),
                            ], spacing=0),
                            ft.Column([
                                ft.Text("Subtotal BCV", size=9, color=subtext),
                                ft.Text(f"${subtotal_bcv_usd:.2f}", size=10, color=ft.Colors.CYAN_600),
                            ], spacing=0),
                            ft.Column([
                                ft.Text("Subtotal Bs", size=9, color=subtext),
                                ft.Text(f"Bs {item['subtotal_bcv']:,.2f}", size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.AMBER_700),
                            ], spacing=0),
                            celda_acciones(item, item["codigo"]),
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    ], spacing=4),
                    padding=10, border_radius=12, width=280,
                    # Mismo sombreado derivado del modelo que en las tablas,
                    # con el borde reforzado para que la tarjeta marcada se
                    # distinga también en modo claro.
                    bgcolor=ft.Colors.with_opacity(0.22, accent) if marcado else card_bg,
                    border=ft.Border.all(2 if marcado else 1, accent if marcado else border),
                    ink=True,
                    on_click=lambda e, cod=item["codigo"]: self.seleccionar_item(cod, e),
                )
                tarjetas.append(t)

            contenido_vista = ft.Column(
                controls=[ft.Row(controls=tarjetas, wrap=True, spacing=8)],
                scroll=ft.ScrollMode.ALWAYS,
                height=346,
            )
            # Las tarjetas se reacomodan solas al ancho disponible (`wrap`):
            # no hay eje horizontal que desplazar, así que ←/→ no tienen aquí
            # un destino que mover y quedan inertes en este modo.
            self._carrito_scroll_h = None
            self._carrito_scroll_v = contenido_vista

        selector_cols = self._build_selector_columnas_carrito() if modo == "separado" else ft.Container()

        return self.create_card(
            content=ft.Column([
                # NOTA: nunca combinar wrap=True con un hijo expand=True en el
                # mismo Row — Flutter's Wrap no soporta hijos Expanded y la
                # UI se renderiza como un rectángulo gris sólido en vez del
                # contenido real (ver bitácora 04/08/2026, mismo bug ya
                # corregido antes en el panel de búsqueda de este archivo).
                # `alignment=SPACE_BETWEEN` ya separa los dos grupos sin
                # necesitar un espaciador expand.
                ft.Row(
                    controls=[
                        ft.Text(f"CARRITO DE COMPRAS ({len(items)} renglones)", size=13, weight=ft.FontWeight.BOLD, color=accent),
                        ft.Row([btn_modo_vista, selector_cols], spacing=8),
                    ],
                    wrap=True,
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                ft.Container(content=contenido_vista, height=350),
            ], spacing=10),
            padding=15,
            border_radius=16,
            height=440,
        )

    # ── Procesamiento de Venta & Diálogo PDF (ERS 3.5) ─────────────────────

    def handle_procesar_venta(self, e):
        """Pulsar "Procesar Venta" ya NO cobra: abre el diálogo de cobro.

        "Preguntar siempre antes de procesar la compra": el cobro necesita la
        referencia del pago y el monto definitivo, y ninguno de los dos se
        puede adivinar desde el carrito. Aquí solo se verifica lo que haría
        inútil abrir el diálogo (carrito vacío, Venta Formal sin cliente)."""
        c_activo = obtener_carrito_activo(self._sid)
        items = c_activo["items"]

        if not items:
            self.show_alert_error(e, "No puede procesar una venta sin artículos en el carrito.")
            return

        if c_activo.get("tipo_venta") == TIPO_VENTA_FORMAL and not c_activo.get("cliente"):
            self.show_alert_error(e, "Debe buscar y seleccionar un cliente registrado para realizar una Venta Formal.")
            return

        self.abrir_dialogo_cobro(e)

    # ── Diálogo ÚNICO de cobro: referencia + monto + descuento ──────────────
    # Un solo diálogo y no dos encadenados: la referencia y el descuento son
    # dos datos del MISMO acto (cerrar el cobro), y el monto con descuento
    # aplicado es justamente lo que el vendedor necesita ver mientras anota la
    # referencia del pago que acaba de recibir por ese monto.

    def _piso_descuento(self, items: list, metodo_pago: str) -> dict:
        """Piso del descuento para este carrito, en la moneda del cobro.

        Réplica exacta del cálculo de `ventas_service` (costos en dólares
        llevados a la moneda del cobro con la proporción del total de lista).
        Aquí es solo informativo: la validación autoritativa vive en el
        servicio, para todos los roles, y esta copia nunca la reemplaza."""
        resumen = calcular_suma_costos(items)
        total_usd = sum(float(i.get("subtotal_usd") or 0.0) for i in items)
        predeterminado = calcular_monto_predeterminado(items, metodo_pago)
        factor = (predeterminado / total_usd) if total_usd else 1.0
        return {
            "monto": round(resumen["suma"] * factor, 2),
            "parcial": resumen["parcial"],
        }

    def abrir_dialogo_cobro(self, e=None):
        c_activo = obtener_carrito_activo(self._sid)
        items = c_activo["items"]
        metodo = c_activo.get("metodo_pago", "Efectivo")
        es_credito = metodo in METODOS_PAGO_CREDITO
        # El efectivo no deja rastro bancario: es el único método sin
        # referencia que anotar. Crédito sí la exige (ahí es el documento del
        # compromiso), con la misma vía de omisión confirmada.
        exige_referencia = metodo != "Efectivo"

        self._monto_predeterminado = calcular_monto_predeterminado(items, metodo)
        simbolo = "Bs." if moneda_de_cobro(metodo) == "BCV" else "$"
        piso = self._piso_descuento(items, metodo)

        # Fuga de información a cuidar: la suma de costos es información
        # reservada a la administración (`permisos_service.puede_ver_costos`).
        # Al vendedor la casilla "Descuento" le aparece VACÍA y sin hint; el
        # piso se valida igual para él en el servicio, pero el rechazo no
        # nombra el costo.
        self._hint_costo_descuento = (
            f"Costo: {simbolo} {piso['monto']:,.2f}"
            if puede_ver_costos(self._rol_usuario) else None
        )

        self.txt_referencia_pago = ft.TextField(
            label="Número de Referencia del Pago *",
            hint_text=f"Referencia de {metodo}",
            prefix_icon=ft.Icons.RECEIPT_LONG,
            border_radius=12,
            autofocus=True,
            visible=exige_referencia,
        )
        self.txt_monto_cobrar = ft.TextField(
            label=f"Monto a Cobrar ({simbolo})",
            value=f"{self._monto_predeterminado:.2f}",
            # Auto-rellenado y de solo lectura: el monto predeterminado sale
            # del método de pago, y cambiarlo es exactamente lo que hace la
            # casilla gemela "Descuento" (así queda a la vista de cuánto se
            # bajó o se subió respecto de la lista).
            read_only=True,
            border_radius=12,
            expand=True,
        )
        self.txt_descuento = ft.TextField(
            label="Descuento",
            hint_text=self._hint_costo_descuento,
            border_radius=12,
            expand=True,
            keyboard_type=ft.KeyboardType.NUMBER,
            on_change=self._actualizar_porcentaje_descuento,
        )
        self._enlazar_foco({
            "cobro_referencia": self.txt_referencia_pago,
            "cobro_monto": self.txt_monto_cobrar,
            "cobro_descuento": self.txt_descuento,
        })
        self.lbl_pct_descuento = ft.Text("", size=14, weight=ft.FontWeight.BOLD)
        self._lbl_err_cobro = ft.Text("", color=ft.Colors.RED_500, size=12, weight=ft.FontWeight.BOLD)

        avisos: list[ft.Control] = []
        if piso["parcial"] and puede_ver_costos(self._rol_usuario):
            avisos.append(ft.Text(
                "Aviso: hay productos sin costo registrado, el piso del "
                "descuento es parcial (más bajo que el real).",
                size=11, color=ft.Colors.AMBER_700, no_wrap=False,
            ))
        if es_credito:
            avisos.append(ft.Text(
                "A crédito el descuento tiene un límite del -5%; por encima "
                "del precio de lista no hay tope.",
                size=11, color=ft.Colors.PURPLE_300, no_wrap=False,
            ))

        acciones = [ft.TextButton("Cancelar", on_click=self._cancelar_cobro)]
        if exige_referencia:
            acciones.append(ft.TextButton(
                "Omitir referencia",
                on_click=self.abrir_confirmacion_omitir_referencia,
            ))
        acciones.append(ft.Button(
            content=ft.Row([ft.Icon(ft.Icons.POINT_OF_SALE), ft.Text("Confirmar Cobro")], tight=True),
            bgcolor=ft.Colors.BLUE_700, color=ft.Colors.WHITE,
            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=12)),
            on_click=self._confirmar_cobro,
        ))

        self._dlg_cobro = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.Icons.POINT_OF_SALE, color=self.get_accent_color()),
                ft.Text("Cobro de la Venta", weight=ft.FontWeight.BOLD),
            ], spacing=10),
            content=ft.Container(
                content=ft.Column([
                    ft.Text(
                        f"Método de pago: {metodo} · "
                        f"{'Venta Formal' if c_activo.get('tipo_venta') == TIPO_VENTA_FORMAL else 'Venta Mostrador'}",
                        size=12, color=self.get_subtext_color(), weight=ft.FontWeight.W_600,
                    ),
                    self.txt_referencia_pago,
                    ft.Row([self.txt_monto_cobrar, self.txt_descuento], spacing=10),
                    ft.Row([self.lbl_pct_descuento], alignment=ft.MainAxisAlignment.END),
                    *avisos,
                    self._lbl_err_cobro,
                ], spacing=10, tight=True),
                width=480,
            ),
            actions=acciones,
            actions_alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )
        self._open_dialog(self._dlg_cobro, e)

    def _actualizar_porcentaje_descuento(self, e=None):
        """Recalcula el porcentaje mientras se escribe en "Descuento".

        Vacía → no se muestra porcentaje y el costo vuelve a asomarse como
        hint; con algo escrito el hint desaparece (es el monto del usuario el
        que manda) y el porcentaje sale en ROJO si cobra por debajo de la
        lista (`-33,75% OFF`) o en VERDE si cobra por encima (`+11,23% ON`).
        """
        crudo = (self.txt_descuento.value or "").strip()
        if not crudo:
            self.txt_descuento.hint_text = self._hint_costo_descuento
            self.lbl_pct_descuento.value = ""
            self.safe_update(e)
            return

        self.txt_descuento.hint_text = None
        try:
            monto = float(crudo.replace(",", "."))
        except ValueError:
            self.lbl_pct_descuento.value = "Monto inválido"
            self.lbl_pct_descuento.color = ft.Colors.RED_500
            self.safe_update(e)
            return

        porcentaje = calcular_porcentaje_descuento(monto, self._monto_predeterminado)
        self.lbl_pct_descuento.value = formatear_porcentaje_descuento(porcentaje)
        self.lbl_pct_descuento.color = ft.Colors.RED_500 if porcentaje < 0 else ft.Colors.GREEN_600
        self.safe_update(e)

    def _cancelar_cobro(self, e=None):
        """Descarta el cobro sin tocar el carrito (la venta no se registró)."""
        self._cerrar_todos_los_dialogos(e)

    def _leer_monto_descuento(self) -> tuple[float | None, str | None]:
        """Monto escrito en "Descuento" o `(None, None)` si quedó vacía.

        Vacía significa "cobrar el precio de lista": se devuelve `None` para
        que `procesar_venta` use el predeterminado y registre 0% de descuento,
        en vez de mandar un número que podría venir de un redondeo de pantalla.
        """
        crudo = (self.txt_descuento.value or "").strip()
        if not crudo:
            return None, None
        try:
            return float(crudo.replace(",", ".")), None
        except ValueError:
            return None, "El descuento debe ser un monto numérico válido."

    def abrir_confirmacion_omitir_referencia(self, e=None):
        """Pregunta de confirmación apilada SOBRE el diálogo de cobro.

        Omitir la referencia queda registrado en la venta
        (`ventas.referencia_omitida`), así que no puede ser un clic suelto:
        se confirma con [Sí] / [NO] y el [NO] devuelve al cobro intacto."""
        def _si(ev):
            self._close_dialog(ev, dialog=dlg_confirmar)
            self._ejecutar_venta(ev, referencia=None, omitida=True)

        def _no(ev):
            self._close_dialog(ev, dialog=dlg_confirmar)

        dlg_confirmar = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, color=ft.Colors.AMBER_700),
                ft.Text("¿Omitir la referencia?", weight=ft.FontWeight.BOLD),
            ], spacing=10),
            content=ft.Container(
                content=ft.Text(
                    "¿Está seguro de omitir el número de referencia? La venta "
                    "quedará registrada sin referencia del pago.",
                    size=13, no_wrap=False,
                ),
                width=380,
            ),
            actions=[
                ft.TextButton("NO", on_click=_no),
                ft.Button(
                    content=ft.Row([ft.Icon(ft.Icons.CHECK), ft.Text("Sí, omitir")], tight=True),
                    bgcolor=ft.Colors.AMBER_800, color=ft.Colors.WHITE,
                    style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=12)),
                    on_click=_si,
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )
        self._dlg_omitir_referencia = dlg_confirmar
        self._open_dialog(dlg_confirmar, e)

    def _confirmar_cobro(self, e=None):
        """Botón "Confirmar Cobro": exige la referencia cuando corresponde."""
        c_activo = obtener_carrito_activo(self._sid)
        metodo = c_activo.get("metodo_pago", "Efectivo")
        referencia = (self.txt_referencia_pago.value or "").strip()

        if metodo != "Efectivo" and not referencia:
            self._mostrar_error_cobro(
                "Ingrese el número de referencia del pago, o use «Omitir "
                "referencia» si no lo tiene.", e,
            )
            return

        self._ejecutar_venta(e, referencia=referencia or None, omitida=False)

    def _mostrar_error_cobro(self, mensaje: str, e=None):
        """Muestra el error DENTRO del diálogo de cobro (no en un snackbar):
        el vendedor tiene que poder corregir el dato sin perder lo escrito."""
        if hasattr(self, "_lbl_err_cobro") and self._lbl_err_cobro is not None:
            self._lbl_err_cobro.value = mensaje
            self.safe_update(e)
        else:
            self.show_alert_error(e, mensaje)

    def _ejecutar_venta(self, e=None, referencia: str = None, omitida: bool = False):
        """Registra la venta con los datos del cobro ya confirmados."""
        c_activo = obtener_carrito_activo(self._sid)
        items = c_activo["items"]
        metodo = c_activo.get("metodo_pago", "Efectivo")
        es_credito = metodo in METODOS_PAGO_CREDITO

        # Crédito sin los datos del compromiso: se vuelve a pedir la ventana
        # en vez de dejar que el servicio rechace la venta por fecha límite
        # faltante (el vendedor no sabría qué le falta).
        if es_credito and not self._datos_credito:
            self.abrir_ventana_credito(e)
            return

        monto_cobrado, error_monto = self._leer_monto_descuento()
        if error_monto:
            self._mostrar_error_cobro(error_monto, e)
            return

        cliente_id = None
        if c_activo.get("tipo_venta") == TIPO_VENTA_FORMAL:
            cliente = c_activo.get("cliente")
            if not cliente:
                self._mostrar_error_cobro(
                    "Debe vincular un cliente registrado para una Venta Formal.", e,
                )
                return
            cliente_id = cliente["cedula_rif"]

        lineas = [
            {
                "producto_codigo": item["codigo"],
                # Viaja solo a los renglones de la deuda (el "repuesto fiado").
                "nombre_corto": item.get("nombre_corto", ""),
                "cantidad": item["cantidad"],
                "precio_unitario_usd": item["precio_usd"],
                "precio_unitario_bcv": item["precio_bcv"],
                "subtotal_usd": item["subtotal_usd"],
                "subtotal_bcv": item["subtotal_bcv"],
            }
            for item in items
        ]

        try:
            resultado = procesar_venta(
                tipo_venta=c_activo.get("tipo_venta", "Formal"),
                cliente_id=cliente_id,
                lineas=lineas,
                metodo_pago=metodo,
                referencia_pago=referencia,
                referencia_omitida=omitida,
                monto_cobrado=monto_cobrado,
                usuario_nombre=self.user_data.get("username"),
                fecha_limite_pago=(self._datos_credito or {}).get("fecha_limite_pago"),
                rol_usuario=self._rol_usuario,
            )
        except ValueError as ve:
            self._mostrar_error_cobro(str(ve), e)
            return
        except Exception as ex:
            self._mostrar_error_cobro(f"Error al procesar la venta: {ex}", e)
            return

        self._cerrar_todos_los_dialogos(e)
        self.venta_id_reciente = resultado["venta_id"]
        vaciar_carrito_activo(self._sid)
        # El carrito vacío ya no tiene cliente, así que Crédito dejaría de ser
        # un método válido: se vuelve a Efectivo para no arrancar la próxima
        # venta en una combinación que el cobro rechazaría.
        if es_credito:
            establecer_metodo_pago(self._sid, "Efectivo")
            self._datos_credito = None

        mensaje = f"¡Venta N° {self.venta_id_reciente:06d} registrada exitosamente!"
        if resultado.get("deuda_id"):
            mensaje += f" Deuda por cobrar N° {resultado['deuda_id']} creada."
        self.show_alert_success(e, mensaje)
        self.rebuild_ui()
        self.mostrar_dialogo_pdf(e)

    # ── Ventana del método de pago "Crédito" ────────────────────────────────

    def abrir_ventana_credito(self, e=None):
        """Casillas del compromiso de pago a crédito.

        Teléfono, dirección, contacto secundario y correo se auto-rellenan con
        lo que ya tenga el cliente de la cartera y quedan en blanco cuando no
        había nada (no eran campos obligatorios al registrarlo). La fecha
        límite siempre se escribe: es lo que vuelve cobrable a la deuda.
        """
        c_activo = obtener_carrito_activo(self._sid)
        cliente = c_activo.get("cliente") or {}
        hay_cliente = bool(cliente.get("cedula_rif"))

        self.txt_credito_fecha = ft.TextField(
            label="Fecha Límite de Pago (Día/Mes/Año) *",
            hint_text="31/12/2026",
            value=(self._datos_credito or {}).get("fecha_limite_pago", ""),
            prefix_icon=ft.Icons.EVENT,
            border_radius=12,
            autofocus=True,
        )
        self.txt_credito_telefono = ft.TextField(
            label="Número de Contacto *",
            value=cliente.get("telefono") or "",
            prefix_icon=ft.Icons.PHONE,
            border_radius=12,
        )
        self.txt_credito_direccion = ft.TextField(
            label="Dirección *",
            value=cliente.get("direccion") or "",
            prefix_icon=ft.Icons.HOME_OUTLINED,
            border_radius=12,
        )
        self.txt_credito_contacto2 = ft.TextField(
            label="Contacto Secundario (opcional)",
            value=cliente.get("contacto_secundario") or "",
            prefix_icon=ft.Icons.CONTACT_PHONE_OUTLINED,
            border_radius=12,
        )
        self.txt_credito_correo = ft.TextField(
            label="Correo (opcional)",
            value=cliente.get("correo") or "",
            prefix_icon=ft.Icons.ALTERNATE_EMAIL,
            border_radius=12,
        )
        self._enlazar_foco({
            "credito_fecha": self.txt_credito_fecha,
            "credito_telefono": self.txt_credito_telefono,
            "credito_direccion": self.txt_credito_direccion,
            "credito_contacto2": self.txt_credito_contacto2,
            "credito_correo": self.txt_credito_correo,
        })
        self._lbl_err_credito = ft.Text("", color=ft.Colors.RED_500, size=12, weight=ft.FontWeight.BOLD)

        if not hay_cliente:
            # Sin cliente la ventana NO se puede completar: la deuda se
            # registra contra su Cédula/RIF. Se dice con claridad en vez de
            # dejar confirmar y fallar después.
            self._lbl_err_credito.value = (
                "Esta venta no tiene cliente vinculado. La deuda a crédito se "
                "registra contra la Cédula/RIF del cliente: busque o registre "
                "el cliente antes de cobrar a crédito."
            )

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.Icons.CREDIT_SCORE, color=ft.Colors.PURPLE_400),
                ft.Text("Venta a Crédito — Compromiso de Pago", weight=ft.FontWeight.BOLD),
            ], spacing=10),
            content=ft.Container(
                content=ft.Column([
                    ft.Text(
                        f"Cliente: {cliente.get('nombre', '—')} ({cliente.get('cedula_rif', 'sin Cédula/RIF')})",
                        size=12, color=self.get_subtext_color(), weight=ft.FontWeight.W_600,
                    ),
                    self.txt_credito_fecha,
                    ft.Row([self.txt_credito_telefono, self.txt_credito_contacto2], spacing=10),
                    self.txt_credito_direccion,
                    self.txt_credito_correo,
                    self._lbl_err_credito,
                ], spacing=10, tight=True),
                width=520,
            ),
            actions=[
                ft.TextButton("Cancelar", on_click=self._cancelar_credito),
                ft.Button(
                    content=ft.Row([ft.Icon(ft.Icons.SAVE), ft.Text("Guardar Compromiso")], tight=True),
                    bgcolor=ft.Colors.PURPLE_400, color=ft.Colors.WHITE,
                    style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=12)),
                    disabled=not hay_cliente,
                    on_click=self._confirmar_credito,
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )
        self._dlg_credito = dlg
        self._open_dialog(dlg, e)

    def _cancelar_credito(self, e=None):
        """Cancelar el compromiso cancela el crédito: el método vuelve a
        Efectivo para que el carrito no quede a crédito sin fecha límite."""
        self._close_dialog(e, dialog=self._dlg_credito)
        self._datos_credito = None
        # Si la ventana se había abierto desde el cobro, ese diálogo quedó
        # mostrando un método de pago que ya no es el del carrito: se cierra
        # también en vez de dejarlo cobrar con datos viejos.
        if getattr(self, "_dlg_cobro", None) in self._dialog_stack:
            self._close_dialog(e, dialog=self._dlg_cobro)
        establecer_metodo_pago(self._sid, "Efectivo")
        if hasattr(self, "dd_metodo_pago"):
            self.dd_metodo_pago.value = "Efectivo"
        self._refrescar_carrito_y_resumen(e)

    def _confirmar_credito(self, e=None):
        c_activo = obtener_carrito_activo(self._sid)
        cliente = c_activo.get("cliente") or {}
        cedula = cliente.get("cedula_rif")
        if not cedula:
            self._lbl_err_credito.value = (
                "No hay cliente vinculado: la deuda no tendría contra quién registrarse."
            )
            self.safe_update(e)
            return

        try:
            # Se normaliza con el mismo servicio que guardará la deuda, para
            # no aceptar aquí una fecha que después rechace el registro.
            from services.deudas_service import normalizar_fecha
            fecha_normalizada = normalizar_fecha(self.txt_credito_fecha.value)
        except ValueError as ex:
            self._lbl_err_credito.value = str(ex)
            self.safe_update(e)
            return

        telefono = (self.txt_credito_telefono.value or "").strip()
        direccion = (self.txt_credito_direccion.value or "").strip()
        if not telefono or not direccion:
            self._lbl_err_credito.value = (
                "El número de contacto y la dirección son obligatorios para una "
                "venta a crédito: son los datos con los que se sale a cobrar."
            )
            self.safe_update(e)
            return

        correo = (self.txt_credito_correo.value or "").strip()
        contacto_secundario = (self.txt_credito_contacto2.value or "").strip()

        # Se completa la ficha del cliente con lo que el vendedor acaba de
        # recoger: estos campos no eran obligatorios al registrarlo y la
        # cartera es el lugar donde tienen que quedar. El contacto secundario
        # entra aquí por primera vez para un cliente cargado antes de que la
        # columna existiera.
        try:
            actualizar_cliente(
                cedula_rif=cedula, telefono=telefono, direccion=direccion,
                correo=correo, contacto_secundario=contacto_secundario,
            )
            cliente.update({
                "telefono": telefono, "direccion": direccion, "correo": correo,
                "contacto_secundario": contacto_secundario,
            })
        except ValueError as ex:
            self._lbl_err_credito.value = f"No se pudo actualizar la ficha del cliente: {ex}"
            self.safe_update(e)
            return

        self._datos_credito = {
            "fecha_limite_pago": fecha_normalizada,
            "telefono": telefono,
            "direccion": direccion,
            "contacto_secundario": contacto_secundario,
            "correo": correo,
        }
        self._close_dialog(e, dialog=self._dlg_credito)
        self.show_alert_success(e, "Compromiso de pago registrado para esta venta a crédito.")
        self._refrescar_carrito_y_resumen(e)

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
            self._close_dialog(e_dialog, dialog=dialog)

        def confirmar_generar_pdf(e_dialog):
            self.divisa_impresion_pdf = dd_divisa.value or "USD"
            formato_papel = dd_formato_papel.value or "carta"
            self._close_dialog(e_dialog, dialog=dialog)

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

        # Por la pila nativa de Flet 0.86 (`show_dialog`/`pop_dialog`): este
        # diálogo se abre justo después de cerrar el de cobro, y con el patrón
        # heredado de `page.overlay` el cierre no se dibujaba y quedaba pegado.
        self._dlg_pdf = dialog
        self._open_dialog(dialog, e)
