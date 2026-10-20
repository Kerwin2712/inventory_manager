import os
import tkinter as tk
from tkinter import filedialog
from datetime import datetime
import pandas as pd
import flet as ft
from ui.views.base_view import BaseView
from ui.components.scroll_nav import build_scroll_nav
from ui.components.pila_dialogos import sincronizar_al_descartar
from ui.components.teclado_nav import ControlTeclado, RegistroFoco
from core.database import get_connection, get_setting, set_setting
from services.importacion_service import (
    procesar_importacion_excel,
    CAMPOS_PRODUCTO_MAPEO,
    MODO_SUMAR,
    detectar_modo_existencia,
    listar_hojas_excel,
    detectar_hoja_productos,
    obtener_columnas_y_muestra,
    sugerir_mapeo_columnas,
    analizar_proveedores_con_mapeo,
    ejecutar_importacion_completa_mapeada,
)
from services.busqueda_service import CRITERIOS_BUSQUEDA, CRITERIO_POR_DEFECTO
from services.permisos_service import es_admin
from services import pedidos_service


def _repintar(pagina) -> None:
    """Fuerza un redibujado de la página, tolerando que no se pueda.

    Una página headless (las pruebas) o desmontada puede no aceptar `update()`;
    eso nunca debe tumbar la apertura o el cierre de un diálogo.
    """
    try:
        pagina.update()
    except (RuntimeError, AttributeError, AssertionError):
        pass


class GestionDatosView(BaseView):
    """Vista de Gestión de Datos y Respaldos del Sistema (ERS 1.1)."""

    def __init__(self, page: ft.Page = None, user_data: dict = None):
        self.user_data = user_data or {}
        # Pila de diálogos del Generador de Pedido. El flujo encadena modales
        # (pedido → casillas del renglón → cierre), y en Flet 0.86 el cierre
        # solo se dibuja a través de `page.show_dialog` / `page.pop_dialog`.
        self._dialog_stack: list[ft.AlertDialog] = []
        # Controles del diálogo del pedido que hay que refrescar en vivo.
        self._pedido_lista_col: ft.Column | None = None
        self._pedido_resumen_lbl: ft.Text | None = None
        self._pedido_resultados_col: ft.Column | None = None
        # Navegación con flechas. En Gestión de Datos NO hay ítems con íconos,
        # así que no se le pasan ni `seleccion` ni `ejecutar_accion`: sin modelo
        # de selección `ControlTeclado` nunca dispara acciones de ítem, que es
        # justo lo que se quiere acá — las teclas de función no hacen nada.
        self._cuerpo_scroll: ft.Column | None = None
        self._scrolls_dialogo: list[tuple] = []
        self._teclado = ControlTeclado(
            # Lambda y no `self.get_current_page` directo: así la página se
            # resuelve a través de la instancia en cada pulsación, y no queda
            # congelado el método ligado del momento de construir la vista.
            obtener_pagina=lambda e=None: self.get_current_page(e),
            destino_vertical=self._destino_vertical,
            destino_horizontal=self._destino_horizontal,
            registro_foco=RegistroFoco(),
            # Identidad logica de la vista: el Dashboard la reemplaza en cada
            # repintado, asi que el control nuevo RELEVA al de la instancia
            # anterior en vez de encadenarse a el. Sin esto la cadena de
            # handlers crece sin tope y las instancias viejas siguen actuando
            # sobre controles que ya no estan en pantalla.
            identidad="gestion_datos",
        )
        super().__init__(route="/gestion-datos", title="Gestión de Datos y Respaldos")

    @property
    def es_admin(self) -> bool:
        """Criterio fail-closed: sin `user_data` NO es administrador.

        De este rol dependen las dos operaciones que pueden reescribir o
        llevarse la base entera, así que el valor por omisión tiene que ser el
        restrictivo: una vista construida sin usuario —por error, o aislada en
        una prueba— no puede habilitar la Carga Masiva.
        """
        return es_admin((self.user_data or {}).get("role"))

    def _exigir_admin(self, e=None) -> bool:
        """Corta la operación si quien la pide no es administrador.

        Ocultar la tarjeta no es autorizar: el handler sigue siendo invocable
        por código y estas dos operaciones reescriben o se llevan la base
        completa. La comprobación se repite aquí a propósito, en el punto
        donde la acción ocurre y no solo donde se dibuja el botón.
        """
        if self.es_admin:
            return True
        self.show_alert_error(
            e, "Esta operación está reservada a los administradores del sistema."
        )
        return False

    # =========================================================================
    # NAVEGACIÓN CON FLECHAS
    # =========================================================================
    # Con solo las flechas se desplaza la vista según los scrolls que haya, y
    # con Ctrl+flecha se va hasta el final de ese eje. Las flechas navegan solo
    # cuando ningún campo de texto tiene el foco: si el cursor está en un campo,
    # mueven el cursor como en cualquier programa (esa regla la aplica
    # `ControlTeclado` consultando el `RegistroFoco` que se le pasó).
    #
    # Los destinos son MÉTODOS, no controles guardados, porque `ControlTeclado`
    # los resuelve en el momento de la pulsación: los diálogos se construyen y
    # se destruyen, y un control guardado al instalar sería un control que ya no
    # está en pantalla.

    def _destinos_activos(self) -> tuple:
        """Los dos destinos de scroll vigentes AHORA: `(vertical, horizontal)`.

        Con un modal arriba se desplaza lo que ese modal registró, y nada si no
        registró nada: mover la pantalla que está DETRÁS de un modal mientras el
        usuario lo lee es desorientador, y el modal tapa el resultado.
        """
        activo = self._dialog
        if activo is not None:
            # Comparación por identidad a propósito: son controles de Flet y no
            # hace falta suponer nada sobre su igualdad ni su hash.
            for dialogo, vertical, horizontal in self._scrolls_dialogo:
                if dialogo is activo:
                    return vertical, horizontal
            return None, None
        return self._cuerpo_scroll, None

    def _destino_vertical(self):
        return self._destinos_activos()[0]

    def _destino_horizontal(self):
        return self._destinos_activos()[1]

    def _registrar_scrolls(self, dialog, vertical=None, horizontal=None) -> None:
        """Anota qué controles desplazan las flechas mientras `dialog` sea el
        modal de arriba. Un diálogo sin scroll propio simplemente no llama acá."""
        self._scrolls_dialogo = [
            entrada for entrada in self._scrolls_dialogo if entrada[0] is not dialog
        ]
        self._scrolls_dialogo.append((dialog, vertical, horizontal))

    def _enlazar_foco(self, campo, nombre: str):
        """Conecta un `TextField` al registro de foco del teclado.

        Todos los campos de texto de la vista pasan por acá —los del asistente
        de mapeo, los del alta de proveedores y los del flujo del pedido—
        porque el registro es contabilidad explícita: Flet no expone un "¿quién
        tiene el foco?" global, así que un campo que no avise deja las flechas
        moviendo la pantalla mientras el usuario escribe dentro de él.
        """
        return self._teclado.foco.enlazar(campo, nombre)

    # =========================================================================
    # PILA DE DIÁLOGOS (API nativa de Flet 0.86)
    # =========================================================================

    @property
    def _dialog(self) -> "ft.AlertDialog | None":
        """Diálogo activo (tope de la pila) o `None` si no hay ninguno."""
        return self._dialog_stack[-1] if self._dialog_stack else None

    def _open_dialog(self, dialog: ft.AlertDialog, e=None):
        """Apila un diálogo y lo muestra sobre el que hubiera debajo."""
        # Un diálogo que Flet descarte solo (tocando fuera, si no es modal)
        # dejaría un fantasma en esta pila y el siguiente cierre descartaría
        # el diálogo equivocado. Ver `ui/components/pila_dialogos.py`.
        sincronizar_al_descartar(dialog, self._dialog_stack)
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

    def _close_dialog(self, e=None, dialog: ft.AlertDialog = None):
        """Descarta el diálogo del tope y deja activo el que estaba debajo.

        `pop_dialog()` cierra el diálogo más alto que siga ABIERTO, así que se
        llama ANTES de bajar la bandera `open`: si se baja primero, el que Flet
        encuentra como tope es el de abajo y se cierra el equivocado (el modal
        quedaría pegado en pantalla, o activo pero invisible recibiendo clics).
        """
        if dialog is None:
            dialog = self._dialog
        if dialog is None:
            return
        if dialog in self._dialog_stack:
            self._dialog_stack.remove(dialog)
        # El diálogo se va: sus scrolls dejan de ser destino de las flechas.
        self._scrolls_dialogo = [
            entrada for entrada in self._scrolls_dialogo if entrada[0] is not dialog
        ]

        p = self.get_current_page(e)
        if p is not None and hasattr(p, "pop_dialog"):
            p.pop_dialog()
            dialog.open = False
            # Mismo motivo que al abrir: Esc cierra desde el teclado y sin
            # repintado explícito el diálogo seguiría dibujado.
            _repintar(p)
            return

        dialog.open = False
        if p is None:
            return
        if dialog in getattr(p, "overlay", []):
            p.overlay.remove(dialog)
        p.update()

    def abrir_dialogo_guardado(self, initial_dir: str, sugerencia_nombre: str) -> str:
        """Abre un cuadro de diálogo nativo de Windows (Tkinter) para seleccionar dónde guardar el respaldo Excel."""
        root = tk.Tk()
        root.attributes("-topmost", True)  # Ventana en primer plano
        root.withdraw()  # Ocultar la ventana principal de Tkinter
        ruta = filedialog.asksaveasfilename(
            initialdir=initial_dir,
            initialfile=sugerencia_nombre,
            title="Guardar Copia de Seguridad Excel",
            defaultextension=".xlsx",
            filetypes=[("Archivos de Excel", "*.xlsx")]
        )
        root.destroy()
        return ruta

    def abrir_dialogo_abrir(self) -> str:
        """Abre un cuadro de diálogo nativo de Windows (Tkinter) para seleccionar un archivo Excel a importar."""
        try:
            print(">>> [abrir_dialogo_abrir] Instanciando ventana oculta tk.Tk()...")
            root = tk.Tk()
            root.attributes("-topmost", True)  # Ventana en primer plano
            root.withdraw()
            print(">>> [abrir_dialogo_abrir] Lanzando filedialog.askopenfilename...")
            ruta = filedialog.askopenfilename(
                title="Seleccionar Archivo Excel para Carga Masiva",
                filetypes=[("Archivos de Excel", "*.xlsx;*.xls"), ("Todos los archivos", "*.*")]
            )
            print(f">>> [abrir_dialogo_abrir] Diálogo cerrado. Ruta obtenida: '{ruta}'")
            root.destroy()
            print(">>> [abrir_dialogo_abrir] Ventana tk destruida con éxito.")
            return ruta
        except Exception as ex:
            import traceback
            print(f">>> [abrir_dialogo_abrir] EXCEPCIÓN en diálogo de archivo:\n{traceback.format_exc()}")
            raise ex

    def get_body(self) -> ft.Control:
        accent = self.get_accent_color()
        text_color = self.get_text_color()
        subtext_color = self.get_subtext_color()
        card_bg = self.get_card_bg()

        # ── Tarjeta 1: Carga Masiva (Importar Excel - ERS 1.1) ─────────────────
        card_importar = self.create_card(
            content=ft.Column([
                ft.Row([
                    ft.Icon(ft.Icons.UPLOAD_FILE_ROUNDED, size=40, color=accent),
                    ft.Column([
                        ft.Text("Carga Masiva de Datos", size=16, weight=ft.FontWeight.BOLD, color=text_color),
                        ft.Text("Importación masiva de inventario y catálogos en lote desde Excel.", size=12, color=subtext_color)
                    ], spacing=2)
                ], spacing=15),
                ft.Divider(),
                ft.Text("Permite cargar o actualizar simultáneamente productos, clientes y proveedores desde plantillas estructuradas.", size=13, color=subtext_color),
                ft.Container(height=10),
                ft.Button(
                    content=ft.Row([
                        ft.Icon(ft.Icons.FILE_UPLOAD_OUTLINED, color=ft.Colors.WHITE),
                        ft.Text("IMPORTAR DESDE EXCEL", weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE)
                    ], alignment=ft.MainAxisAlignment.CENTER),
                    style=ft.ButtonStyle(bgcolor=accent, shape=ft.RoundedRectangleBorder(radius=12)),
                    on_click=self.handle_importar_click
                )
            ], spacing=12),
            padding=20,
            border_radius=16
        )
        card_importar.col = {"sm": 12, "lg": 6}

        # ── Tarjeta 2: Copias de Seguridad (Exportar a Excel - ERS 1.1) ───────
        card_exportar = self.create_card(
            content=ft.Column([
                ft.Row([
                    ft.Icon(ft.Icons.SAVINGS_ROUNDED, size=40, color=accent),
                    ft.Column([
                        ft.Text("Copias de Seguridad (Backup)", size=16, weight=ft.FontWeight.BOLD, color=text_color),
                        ft.Text("Exportación completa a libro Excel (.xlsx) con pestañas separadas.", size=12, color=subtext_color)
                    ], spacing=2)
                ], spacing=15),
                ft.Divider(),
                ft.Text("Genera un respaldo integral exportando Productos, Clientes y Proveedores en hojas separadas.", size=13, color=subtext_color),
                ft.Container(height=10),
                ft.Button(
                    content=ft.Row([
                        ft.Icon(ft.Icons.DOWNLOAD_ROUNDED, color=ft.Colors.WHITE),
                        ft.Text("GENERAR COPIA DE SEGURIDAD (.XLSX)", weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE)
                    ], alignment=ft.MainAxisAlignment.CENTER),
                    style=ft.ButtonStyle(bgcolor=accent, shape=ft.RoundedRectangleBorder(radius=12)),
                    on_click=self.handle_exportar_excel
                )
            ], spacing=12),
            padding=20,
            border_radius=16
        )
        card_exportar.col = {"sm": 12, "lg": 6}

        # ── Tarjeta 3: Generador de Archivo por Nueva Mercancía ───────────────
        # Disponible para TODOS los roles a propósito (Nueva Función 6): es el
        # punto del requisito — el empleado que recibe la mercancía arma el
        # pedido en un Excel sin poder modificar el stock, y el Administrador
        # lo supervisa y lo ingresa después por Carga Masiva de Datos.
        card_pedido = self.create_card(
            content=ft.Column([
                ft.Row([
                    ft.Icon(ft.Icons.ADD_SHOPPING_CART_ROUNDED, size=40, color=accent),
                    ft.Column([
                        ft.Text("Generador de Archivo por Nueva Mercancía", size=16, weight=ft.FontWeight.BOLD, color=text_color),
                        ft.Text("Arma el pedido de mercancía recibida y lo exporta en el formato de Carga Masiva.", size=12, color=subtext_color)
                    ], spacing=2, expand=True)
                ], spacing=15),
                ft.Divider(),
                ft.Text(
                    "Busque el item en el banco de datos, complete solo Costo, Precio de Venta, Marca y "
                    "Cantidad, y al cerrar indique Proveedor y Fecha de Recepción. El archivo NO modifica "
                    "el inventario: se le entrega al Administrador para que lo cargue supervisado.",
                    size=13, color=subtext_color,
                ),
                # El archivo es una ENTRADA de mercancía, no un catálogo: al
                # cargarlo suma las cantidades al stock. Se dice acá, en el
                # diálogo del pedido y otra vez al cerrarlo, porque es la
                # diferencia entre registrar lo que llegó y reemplazar el
                # inventario — y quien lo carga no es quien armó el pedido.
                ft.Text(
                    "Al cargarlo, las cantidades SE SUMAN al stock que cada producto ya tiene "
                    "(no lo reemplazan).",
                    size=13, weight=ft.FontWeight.BOLD, color=accent,
                ),
                ft.Container(height=10),
                ft.Button(
                    content=ft.Row([
                        ft.Icon(ft.Icons.PLAYLIST_ADD_ROUNDED, color=ft.Colors.WHITE),
                        ft.Text("ARMAR PEDIDO DE NUEVA MERCANCÍA", weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE)
                    ], alignment=ft.MainAxisAlignment.CENTER),
                    style=ft.ButtonStyle(bgcolor=accent, shape=ft.RoundedRectangleBorder(radius=12)),
                    on_click=self.mostrar_generador_pedido
                )
            ], spacing=12),
            padding=20,
            border_radius=16
        )
        card_pedido.col = {"sm": 12, "lg": 6}

        # La Carga Masiva REESCRIBE el stock de todo el catálogo y la Copia de
        # Seguridad se lleva la base completa —incluidos los costos, que son
        # información reservada a la administración—, así que las dos quedan
        # solo para administradores. El Generador de Pedido, en cambio, sigue
        # visible para todos: es el punto de la Nueva Función 6, que el
        # empleado registre la mercancía recibida SIN poder tocar el
        # inventario. Sin esta separación, un vendedor podía reescribir el
        # stock entero desde el mismo módulo que existe para que no pudiera.
        tarjetas = (
            [card_importar, card_exportar, card_pedido] if self.es_admin
            else [card_pedido]
        )

        # Único dueño del eje vertical de la vista, y por eso el destino de las
        # flechas arriba/abajo. No hay scroll horizontal en el cuerpo: las
        # tarjetas se reacomodan con `ResponsiveRow` en vez de desbordarse.
        self._cuerpo_scroll = ft.Column([
            ft.Row([
                ft.Icon(ft.Icons.DATASET_ROUNDED, size=28, color=accent),
                ft.Text("Módulo de Gestión de Datos y Respaldos", size=20, weight=ft.FontWeight.BOLD, color=text_color)
            ], spacing=10),
            ft.Text("Administre las importaciones masivas y la exportación de copias de seguridad de la base de datos.", color=subtext_color),
            ft.Divider(height=20, color=self.get_border_color()),
            ft.ResponsiveRow(tarjetas, spacing=20, vertical_alignment=ft.CrossAxisAlignment.START)
        ], spacing=15, scroll=ft.ScrollMode.AUTO, expand=True)

        # Instalación perezosa: al construir la vista todavía no hay `page` (se
        # instancia headless y el Dashboard le asigna la página antes de pedirle
        # el cuerpo), así que se intenta acá y en cada handler que trae evento.
        # `instalar()` es idempotente y respeta el handler anterior de la
        # página, que la vista comparte con el Dashboard.
        self._teclado.instalar()

        return ft.Container(
            content=self._cuerpo_scroll,
            padding=15,
            expand=True
        )

    def handle_importar_click(self, e):
        """Ejecuta la Carga Masiva: selecciona el archivo y abre el asistente
        de mapeo de columnas (el usuario decide a qué campo de la BD
        corresponde cada columna del Excel, sin importar cómo se llame)."""
        self._teclado.instalar(e)
        if not self._exigir_admin(e):
            return
        try:
            print("\n>>> [GestionDatosView] Clic en IMPORTAR DESDE EXCEL")
            with open("import_debug.log", "a", encoding="utf-8") as f:
                f.write(f"\n[{datetime.now()}] Iniciando handle_importar_click\n")

            print(">>> [GestionDatosView] Abriendo diálogo de selección de archivo...")
            ruta_archivo = self.abrir_dialogo_abrir()
            with open("import_debug.log", "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now()}] Ruta seleccionada: {ruta_archivo}\n")
            print(f">>> [GestionDatosView] Ruta de archivo seleccionada: '{ruta_archivo}'")

            if not ruta_archivo:
                print(">>> [GestionDatosView] Cancelado: No se seleccionó ningún archivo.")
                with open("import_debug.log", "a", encoding="utf-8") as f:
                    f.write(f"[{datetime.now()}] No se seleccionó archivo\n")
                return

            self.mostrar_asistente_mapeo(e, ruta_archivo)
        except Exception as ex:
            import traceback
            err_msg = traceback.format_exc()
            with open("import_debug.log", "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now()}] EXCEPCIÓN: {err_msg}\n")
            print(f"\n>>> [GestionDatosView] EXCEPCIÓN CRÍTICA en handle_importar_click:\n{err_msg}")
            try:
                self.show_alert_error(e, f"Excepción crítica: {str(ex)}")
            except Exception:
                pass

    def mostrar_asistente_mapeo(self, e, ruta_archivo: str, hoja_forzada: str | None = None):
        """Asistente de mapeo de columnas para la importación de inventario:
        muestra las columnas reales del archivo con una muestra de filas y
        deja que el usuario decida explícitamente a qué campo de la base de
        datos corresponde cada una — funciona sin importar los nombres de
        las columnas del Excel."""
        p = self.get_current_page(e)
        if not p:
            return

        try:
            hojas = listar_hojas_excel(ruta_archivo)
        except Exception as ex:
            self.show_alert_error(e, f"Error al abrir el archivo Excel: {ex}")
            return

        hoja_actual = hoja_forzada or detectar_hoja_productos(ruta_archivo)
        if not hoja_actual and hojas:
            hoja_actual = hojas[0]
        if not hoja_actual:
            self.show_alert_error(e, "El archivo no tiene ninguna hoja legible.")
            return

        info = obtener_columnas_y_muestra(ruta_archivo, hoja_actual)
        columnas_excel = info["columnas"]
        muestra = info["muestra"]
        sugerido = sugerir_mapeo_columnas(columnas_excel)

        if not columnas_excel:
            self.show_alert_error(e, f"La hoja '{hoja_actual}' no tiene columnas.")
            return

        NO_IMPORTAR = ""
        opciones_columna = [ft.dropdown.Option(NO_IMPORTAR, "— No importar —")] + [
            ft.dropdown.Option(c, c) for c in columnas_excel
        ]

        lbl_muestra_por_campo: dict[str, ft.Text] = {}
        dd_por_campo: dict[str, ft.Dropdown] = {}

        def _texto_muestra(columna: str) -> str:
            valores = muestra.get(columna, [])
            if not valores:
                return "(sin datos de muestra)"
            return "Ej: " + ", ".join(v if v else "∅" for v in valores[:4])

        def _campo_mapeo_row(campo: str, etiqueta: str, obligatorio: bool) -> ft.Row:
            valor_inicial = sugerido.get(campo, NO_IMPORTAR)
            dd = ft.Dropdown(
                value=valor_inicial if valor_inicial in columnas_excel else NO_IMPORTAR,
                options=opciones_columna,
                width=240,
                border_radius=10,
                dense=True,
            )
            lbl_muestra = ft.Text(
                _texto_muestra(valor_inicial) if valor_inicial else "",
                size=11, color=self.get_subtext_color(), italic=True, expand=True,
            )

            def _on_change(ev, lbl=lbl_muestra):
                lbl.value = _texto_muestra(dd.value) if dd.value else ""
                p.update()

            dd.on_change = _on_change
            dd_por_campo[campo] = dd
            lbl_muestra_por_campo[campo] = lbl_muestra

            etiqueta_texto = f"{etiqueta} *" if obligatorio else etiqueta
            return ft.Row(
                controls=[
                    ft.Text(etiqueta_texto, size=13, weight=ft.FontWeight.BOLD if obligatorio else ft.FontWeight.NORMAL,
                             color=self.get_text_color(), width=180),
                    dd,
                    lbl_muestra,
                ],
                spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )

        filas_mapeo = [
            _campo_mapeo_row(campo, etiqueta, obligatorio)
            for campo, etiqueta, obligatorio in CAMPOS_PRODUCTO_MAPEO
        ]

        # ── Vista previa cruda del archivo (encabezados + primeras filas) ────
        # Deja ver el contenido real sin depender de que el usuario recuerde
        # los nombres de columna mientras completa el mapeo de arriba.
        preview_table = ft.DataTable(
            columns=[ft.DataColumn(ft.Text(c, weight=ft.FontWeight.BOLD, size=12)) for c in columnas_excel],
            rows=[
                ft.DataRow(cells=[
                    ft.DataCell(ft.Text(muestra[c][i] if i < len(muestra[c]) else "", size=12))
                    for c in columnas_excel
                ])
                for i in range(max((len(v) for v in muestra.values()), default=0))
            ],
            column_spacing=20,
        )
        preview_row = ft.Row(controls=[preview_table], scroll=ft.ScrollMode.AUTO)

        lbl_err = ft.Text("", color=ft.Colors.RED_500, size=12, weight=ft.FontWeight.BOLD)

        def _confirmar(ev):
            mapeo = {campo: dd_por_campo[campo].value for campo, *_ in CAMPOS_PRODUCTO_MAPEO if dd_por_campo[campo].value}
            if not mapeo.get("codigo"):
                lbl_err.value = "Debe mapear una columna al campo obligatorio 'Código'."
                p.update()
                return

            self._close_dialog(ev, dialog=dlg)

            analisis = analizar_proveedores_con_mapeo(ruta_archivo, hoja_actual, mapeo.get("proveedor"))
            if not analisis.get("exito"):
                self.show_alert_error(ev, analisis.get("mensaje"))
                return

            faltantes = analisis.get("proveedores_faltantes", [])
            if faltantes:
                self.mostrar_asistente_proveedores_faltantes(
                    ev, ruta_archivo, faltantes,
                    on_completado=lambda ev2: self.ejecutar_importacion_final_mapeada(ev2, ruta_archivo, hoja_actual, mapeo),
                )
            else:
                self.ejecutar_importacion_final_mapeada(ev, ruta_archivo, hoja_actual, mapeo)

        def _cancelar(ev):
            self._close_dialog(ev, dialog=dlg)

        def _cambiar_hoja(ev):
            self._close_dialog(ev, dialog=dlg)
            self.mostrar_asistente_mapeo(ev, ruta_archivo, hoja_forzada=dd_hoja.value)

        contenido = [
            ft.Text(
                f"Se detectaron {len(columnas_excel)} columnas en la hoja seleccionada. Indique a qué campo "
                "de la base de datos corresponde cada una (o déjelo en 'No importar'). El nombre de las "
                "columnas del archivo no importa — usted decide el mapeo.",
                size=12, color=self.get_subtext_color(),
            ),
        ]

        # El otro lado del aviso que se le da a quien exporta el pedido: quien
        # CARGA el archivo tiene que saber, antes de confirmar, si lo que tiene
        # en la mano es una entrada de mercancía (las cantidades se suman) o un
        # catálogo/respaldo (la existencia queda en el número del archivo). Es
        # la diferencia entre registrar lo que llegó y reemplazar el inventario,
        # y mirando las columnas no se distingue.
        if detectar_modo_existencia(ruta_archivo) == MODO_SUMAR:
            contenido.append(ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.ADD_CIRCLE_OUTLINE_ROUNDED, color=self.get_accent_color(), size=22),
                    ft.Text(
                        "Este archivo es una ENTRADA DE MERCANCÍA generada por el asistente de "
                        "pedidos: la columna Existencia es la cantidad recibida y SE SUMARÁ al "
                        "stock actual de cada producto, no lo reemplazará.",
                        size=12, weight=ft.FontWeight.BOLD, color=self.get_text_color(),
                        expand=True, no_wrap=False,
                    ),
                ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.START),
                padding=10, border_radius=10,
                bgcolor=self.get_card_bg(),
                border=ft.Border.all(1, self.get_accent_color()),
            ))

        if len(hojas) > 1:
            dd_hoja = ft.Dropdown(
                label="Hoja del archivo a importar como Productos",
                value=hoja_actual,
                options=[ft.dropdown.Option(h) for h in hojas],
                width=320, border_radius=10,
            )
            dd_hoja.on_change = _cambiar_hoja
            contenido.append(dd_hoja)

        col_mapeo = ft.Column(controls=filas_mapeo, spacing=6, scroll=ft.ScrollMode.ALWAYS, height=260)
        container_mapeo = ft.Container(
            content=col_mapeo,
            padding=6,
            border_radius=10,
            bgcolor=self.get_card_bg(),
            border=ft.Border.all(1, self.get_border_color()),
        )

        contenido += [
            ft.Divider(height=10),
            ft.Row([
                ft.Text("MAPEO DE COLUMNAS", size=12, weight=ft.FontWeight.BOLD, color=self.get_accent_color()),
                build_scroll_nav(col_mapeo, "vertical", self.get_accent_color(), step=180, tooltip_prefix="Columnas: "),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            container_mapeo,
            ft.Divider(height=10),
            ft.Row([
                ft.Text("VISTA PREVIA DEL ARCHIVO", size=12, weight=ft.FontWeight.BOLD, color=self.get_accent_color()),
                build_scroll_nav(preview_row, "horizontal", self.get_accent_color(), tooltip_prefix="Vista previa: "),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.Container(content=preview_row, padding=6, border_radius=10,
                         bgcolor=self.get_card_bg(), border=ft.Border.all(1, self.get_border_color())),
            lbl_err,
        ]

        col_contenido = ft.Column(contenido, spacing=10, tight=True, scroll=ft.ScrollMode.AUTO)

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.Icons.RULE_ROUNDED, color=self.get_accent_color()),
                ft.Text(f"Mapeo de Columnas — Hoja '{hoja_actual}'", weight=ft.FontWeight.BOLD),
            ], spacing=10),
            content=ft.Container(
                content=col_contenido,
                # Diálogo amplio: hay 11 campos a mapear + una vista previa
                # tabular del archivo, no caben cómodos en un modal chico.
                width=900,
                height=680,
            ),
            actions=[
                ft.TextButton("Cancelar", on_click=_cancelar),
                ft.Button(
                    content=ft.Row([ft.Icon(ft.Icons.PLAY_ARROW_ROUNDED), ft.Text("Confirmar Mapeo e Importar")], tight=True),
                    bgcolor=self.get_accent_color(), color=ft.Colors.WHITE,
                    style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=12)),
                    on_click=_confirmar,
                ),
            ],
        )

        # Este diálogo tiene los dos ejes: su contenido se desplaza en vertical
        # y la vista previa del archivo en horizontal (es una tabla ancha, y es
        # justo el caso donde las flechas ahorran arrastrar una barra fina).
        self._registrar_scrolls(dlg, vertical=col_contenido, horizontal=preview_row)
        self._open_dialog(dlg, e)

    def mostrar_asistente_proveedores_faltantes(self, e, ruta_archivo, faltantes, idx=0, on_completado=None):
        """Muestra un diálogo dinámico secuencial para completar información
        de proveedores nuevos. Al terminar con todos, invoca `on_completado`
        (por defecto, la importación clásica por heurística de nombres de
        columna); el asistente de mapeo de columnas pasa aquí su propia
        continuación para usar el mapeo explícito que el usuario confirmó."""
        p = self.get_current_page(e)
        if not p:
            print(">>> [mostrar_asistente_proveedores_faltantes] ERROR: No se pudo obtener la instancia de Page activa.")
            return

        nombre_prov = faltantes[idx]
        total_faltantes = len(faltantes)
        print(f">>> [mostrar_asistente_proveedores_faltantes] Abriendo modal para proveedor '{nombre_prov}' ({idx + 1} de {total_faltantes})...")

        # Controles del formulario. Todos van al registro de foco: mientras el
        # usuario escribe el RIF o el teléfono, las flechas tienen que mover el
        # cursor dentro del campo y no la pantalla de atrás.
        txt_empresa = self._enlazar_foco(ft.TextField(
            label="Razón Social / Empresa (Obligatorio)*",
            value=nombre_prov,
            disabled=True,
            prefix_icon=ft.Icons.BUSINESS
        ), "prov_empresa")
        txt_rif = self._enlazar_foco(ft.TextField(
            label="Cédula / RIF (Obligatorio)*",
            prefix_icon=ft.Icons.BADGE
        ), "prov_rif")
        txt_contacto = self._enlazar_foco(ft.TextField(
            label="Persona de Contacto (Opcional)",
            prefix_icon=ft.Icons.PERSON
        ), "prov_contacto")
        txt_telefono = self._enlazar_foco(ft.TextField(
            label="Teléfono de Contacto (Obligatorio)*",
            prefix_icon=ft.Icons.PHONE,
            keyboard_type=ft.KeyboardType.PHONE
        ), "prov_telefono")
        txt_correo = self._enlazar_foco(ft.TextField(
            label="Correo Electrónico (Opcional)",
            prefix_icon=ft.Icons.EMAIL,
            keyboard_type=ft.KeyboardType.EMAIL
        ), "prov_correo")
        txt_descripcion = self._enlazar_foco(ft.TextField(
            label="Descripción / Notas (Opcional)",
            multiline=True,
            min_lines=2,
            max_lines=3,
            prefix_icon=ft.Icons.NOTE
        ), "prov_descripcion")
        lbl_error = ft.Text(
            "", 
            color=ft.Colors.RED_500, 
            size=12, 
            weight=ft.FontWeight.BOLD
        )

        def cerrar_asistente(e_close):
            print(">>> [mostrar_asistente_proveedores_faltantes] Asistente cancelado por el usuario.")
            self._close_dialog(e_close, dialog=dlg)
            self.show_alert_info(e, "Importación cancelada por el usuario.")

        def registrar_proveedor(e_reg):
            lbl_error.value = ""
            p.update()

            empresa = txt_empresa.value.strip()
            rif = txt_rif.value.strip()
            contacto = txt_contacto.value.strip()
            telefono = txt_telefono.value.strip()
            correo = txt_correo.value.strip()
            descripcion = txt_descripcion.value.strip()

            print(f">>> [registrar_proveedor] Intentando registrar: Empresa='{empresa}', RIF='{rif}', Teléfono='{telefono}'...")

            if not rif:
                print(">>> [registrar_proveedor] ERROR: RIF vacío")
                lbl_error.value = "La Cédula / RIF es obligatoria."
                p.update()
                return

            if not empresa:
                print(">>> [registrar_proveedor] ERROR: Empresa vacía")
                lbl_error.value = "La Razón Social / Empresa es obligatoria."
                p.update()
                return

            if not telefono:
                print(">>> [registrar_proveedor] ERROR: Teléfono vacío")
                lbl_error.value = "El Teléfono de Contacto es obligatorio por regla de negocio."
                p.update()
                return

            try:
                from services.cartera_service import crear_proveedor
                crear_proveedor(
                    empresa=empresa,
                    contacto=contacto if contacto else None,
                    telefono=telefono,
                    correo=correo if correo else None,
                    rif=rif if rif else None,
                    descripcion=descripcion if descripcion else f"Creado automáticamente durante la importación masiva."
                )
                print(f">>> [registrar_proveedor] Registrado exitosamente en SQLite.")
                
                self._close_dialog(e_reg, dialog=dlg)

                # Siguiente o iniciar importación final
                sig_idx = idx + 1
                if sig_idx < total_faltantes:
                    self.mostrar_asistente_proveedores_faltantes(e, ruta_archivo, faltantes, sig_idx, on_completado=on_completado)
                else:
                    print(">>> [registrar_proveedor] Todos los proveedores registrados. Procediendo a la importación final...")
                    self.show_alert_success(e, "Todos los proveedores nuevos se registraron correctamente.")
                    (on_completado or (lambda ev: self.ejecutar_importacion_final(ev, ruta_archivo)))(e)

            except Exception as ex:
                import traceback
                print(f">>> [registrar_proveedor] EXCEPCIÓN al registrar: {traceback.format_exc()}")
                lbl_error.value = f"Error al registrar: {str(ex)}"
                p.update()

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.Icons.ADD_BUSINESS, color=self.get_accent_color(), size=28),
                ft.Text(f"Proveedor Faltante ({idx + 1} de {total_faltantes})", weight=ft.FontWeight.BOLD)
            ], spacing=10),
            content=ft.Container(
                content=ft.Column([
                    ft.Text(f"El proveedor '{nombre_prov}' no existe. Por favor, completa su información para proceder con la importación.", size=13, color=self.get_subtext_color()),
                    ft.Divider(height=10),
                    txt_empresa,
                    txt_rif,
                    txt_contacto,
                    txt_telefono,
                    txt_correo,
                    txt_descripcion,
                    lbl_error
                ], spacing=12, tight=True),
                width=480,
                padding=10
            ),
            actions=[
                ft.TextButton("Cancelar Importación", on_click=cerrar_asistente),
                ft.Button(
                    content=ft.Row([ft.Icon(ft.Icons.SAVE), ft.Text("Guardar y Continuar")], tight=True),
                    bgcolor=self.get_accent_color(),
                    color=ft.Colors.WHITE,
                    on_click=registrar_proveedor
                )
            ],
            actions_alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )

        self._open_dialog(dlg, e)

    def ejecutar_importacion_final(self, e, ruta_archivo):
        """Llama al servicio de importación real para los productos del Excel."""
        try:
            print(f">>> [ejecutar_importacion_final] Iniciando importación de productos desde: '{ruta_archivo}'")
            from services.importacion_service import procesar_importacion_excel
            with open("import_debug.log", "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now()}] Iniciando ejecutar_importacion_final para: {ruta_archivo}\n")
            
            res = procesar_importacion_excel(ruta_archivo)
            
            with open("import_debug.log", "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now()}] Resultado de la importación final: {res}\n")
            print(f">>> [ejecutar_importacion_final] Resultado de la importación: {res}")

            if res.get("exito"):
                print(">>> [ejecutar_importacion_final] Importación exitosa, mostrando snackbar verde.")
                self.show_alert_success(e, res.get("mensaje"))
            else:
                print(f">>> [ejecutar_importacion_final] Falla en importación: {res.get('mensaje')}. Mostrando diálogo de error.")
                self.mostrar_dialogo_error(e, res.get("mensaje"))
        except Exception as ex:
            import traceback
            err_msg = traceback.format_exc()
            with open("import_debug.log", "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now()}] EXCEPCIÓN EN IMPORTACIÓN FINAL: {err_msg}\n")
            print(f"\n>>> [ejecutar_importacion_final] EXCEPCIÓN en importación final:\n{err_msg}")
            try:
                self.show_alert_error(e, f"Excepción crítica en importación final: {str(ex)}")
            except Exception:
                pass

    def ejecutar_importacion_final_mapeada(self, e, ruta_archivo, hoja_productos, mapeo):
        """Ejecuta la importación usando el mapeo de columnas explícito que el
        usuario confirmó en el asistente (services.ejecutar_importacion_completa_mapeada)."""
        try:
            print(f">>> [ejecutar_importacion_final_mapeada] hoja='{hoja_productos}' mapeo={mapeo}")
            with open("import_debug.log", "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now()}] Iniciando ejecutar_importacion_final_mapeada: hoja={hoja_productos} mapeo={mapeo}\n")

            res = ejecutar_importacion_completa_mapeada(ruta_archivo, hoja_productos, mapeo)

            with open("import_debug.log", "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now()}] Resultado de la importación mapeada: {res}\n")
            print(f">>> [ejecutar_importacion_final_mapeada] Resultado: {res}")

            if res.get("exito"):
                self.show_alert_success(e, res.get("mensaje"))
            else:
                self.mostrar_dialogo_error(e, res.get("mensaje"))
        except Exception as ex:
            import traceback
            err_msg = traceback.format_exc()
            with open("import_debug.log", "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now()}] EXCEPCIÓN EN IMPORTACIÓN MAPEADA: {err_msg}\n")
            print(f"\n>>> [ejecutar_importacion_final_mapeada] EXCEPCIÓN:\n{err_msg}")
            try:
                self.show_alert_error(e, f"Excepción crítica en importación: {str(ex)}")
            except Exception:
                pass

    def mostrar_dialogo_error(self, e, error_msg: str):
        """Muestra un AlertDialog emergente cuando la importación transaccional falla y ejecuta ROLLBACK."""
        p = self.get_current_page(e)
        if not p:
            return

        def cerrar_dialogo(e_close):
            self._close_dialog(e_close, dialog=dlg)

        dlg = ft.AlertDialog(
            title=ft.Row([
                ft.Icon(ft.Icons.ERROR_OUTLINED, color=ft.Colors.RED_500, size=28),
                ft.Text("Error en Carga Masiva de Excel", weight=ft.FontWeight.BOLD, color=ft.Colors.RED_500)
            ], spacing=10),
            content=ft.Container(
                content=ft.Column([
                    ft.Text("Se ha realizado un ROLLBACK automático en la base de datos.", weight=ft.FontWeight.BOLD, size=13),
                    ft.Divider(height=10),
                    ft.Text(error_msg, color=self.get_text_color(), size=13),
                ], spacing=10, tight=True),
                width=450,
                padding=10
            ),
            actions=[
                ft.TextButton("Entendido", on_click=cerrar_dialogo)
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

        self._open_dialog(dlg, e)

    def handle_exportar_excel(self, e):
        """Exporta la base de datos completa a un libro Excel (.xlsx) con pestañas separadas (ERS 1.1)."""
        self._teclado.instalar(e)
        if not self._exigir_admin(e):
            return
        last_dir = get_setting("last_excel_dir", default=None)
        if last_dir and not os.path.exists(last_dir):
            last_dir = None

        sugerencia = f"Backup_Inventario_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        ruta_destino = self.abrir_dialogo_guardado(last_dir, sugerencia)

        if not ruta_destino:
            return

        try:
            conn = get_connection()

            # 1. Cargar DataFrames de cada tabla
            # Los encabezados de costo y sub-departamento son EXACTAMENTE los
            # que la Carga Masiva reconoce (ver `CAMPOS_PRODUCTO_MAPEO` en
            # `services/importacion_service.py`), porque un respaldo que no se
            # puede volver a importar no es un respaldo. Antes el respaldo no
            # los traía, así que restaurarlo en una base vacía perdía los
            # costos de todo el catálogo: el dato que nadie puede reconstruir
            # de memoria.
            df_productos = pd.read_sql_query("""
                SELECT
                    codigo AS [Código],
                    referencia AS [Referencia],
                    departamento AS [Departamento],
                    sub_departamento AS [Sub-Departamento],
                    descripcion_general AS [Descripción General],
                    marca AS [Marca],
                    precio_dolares AS [Precio USD (Efectivo)],
                    precio_bcv AS [Precio USD (BCV)],
                    costo_usd_efectivo AS [Costo USD (Efectivo)],
                    costo_usd_bcv AS [Costo USD (BCV)],
                    proveedor_id AS [ID Proveedor],
                    existencia AS [Existencia],
                    codigo_barras AS [Código Barras],
                    nombre_referencia_corto AS [Nombre Referencia Corto],
                    fecha_ultima_modificacion AS [Última Modificación]
                FROM productos
            """, conn)

            df_clientes = pd.read_sql_query("""
                SELECT 
                    cedula_rif AS [Cédula / RIF],
                    nombre AS [Razón Social / Nombre],
                    direccion AS [Dirección],
                    telefono AS [Teléfono],
                    correo AS [Correo Electrónico]
                FROM clientes
            """, conn)

            df_proveedores = pd.read_sql_query("""
                SELECT 
                    id AS [ID],
                    empresa AS [Razón Social / Empresa],
                    contacto AS [Persona de Contacto],
                    telefono AS [Teléfono],
                    correo AS [Correo Electrónico],
                    descripcion AS [Descripción / Notas]
                FROM proveedores
            """, conn)

            conn.close()

            # 2. Generar archivo Excel con pestañas separadas usando openpyxl
            with pd.ExcelWriter(ruta_destino, engine="openpyxl") as writer:
                df_productos.to_excel(writer, sheet_name="Productos", index=False)
                df_clientes.to_excel(writer, sheet_name="Clientes", index=False)
                df_proveedores.to_excel(writer, sheet_name="Proveedores", index=False)

            # 3. Guardar el directorio contenedor en app_settings
            directorio = os.path.dirname(ruta_destino)
            if directorio:
                set_setting("last_excel_dir", directorio)

            self.show_alert_success(e, f"Copia de seguridad guardada exitosamente en:\n{ruta_destino}")

        except Exception as ex:
            self.show_alert_error(e, f"Error al generar la copia de seguridad Excel: {ex}")

    # =========================================================================
    # GENERADOR DE ARCHIVO POR NUEVA MERCANCÍA (Nueva Función 6)
    # =========================================================================
    # La vista solo orquesta: el borrador, las validaciones y la generación del
    # Excel viven en `services.pedidos_service` (testeable sin interfaz). Nada
    # de este flujo escribe en la base de datos — ver el docstring del servicio.

    def _refrescar_pedido(self, e=None):
        """Redibuja la tabla del pedido en borrador y su resumen.

        Se reconstruye desde el servicio en cada cambio (agregar, editar,
        quitar) en vez de mutar los controles: el borrador es la única fuente
        de verdad y así la pantalla no puede quedar desincronizada de él.
        """
        if self._pedido_lista_col is None:
            return
        sid = self.get_session_id(e)
        renglones = pedidos_service.obtener_renglones(sid)

        if not renglones:
            self._pedido_lista_col.controls = [
                ft.Text("El pedido está vacío. Busque un item arriba para agregarlo.",
                        size=12, italic=True, color=self.get_subtext_color())
            ]
        else:
            filas = [
                ft.Row([
                    ft.Text("ITEM", size=11, weight=ft.FontWeight.BOLD, color=self.get_accent_color(), width=220),
                    ft.Text("MARCA", size=11, weight=ft.FontWeight.BOLD, color=self.get_accent_color(), width=110),
                    ft.Text("CANT.", size=11, weight=ft.FontWeight.BOLD, color=self.get_accent_color(), width=60),
                    ft.Text("COSTO $", size=11, weight=ft.FontWeight.BOLD, color=self.get_accent_color(), width=80),
                    ft.Text("VENTA $", size=11, weight=ft.FontWeight.BOLD, color=self.get_accent_color(), width=80),
                    ft.Text("", expand=True),
                ], spacing=8)
            ]
            for indice, r in enumerate(renglones):
                etiqueta = f"{r['codigo']} — {r['nombre_referencia_corto'] or r['descripcion_general']}"
                if r["origen"] == "manual":
                    # El alta manual queda identificada: son piezas que todavía
                    # no existen en el sistema y el Administrador las creará al
                    # importar, así que merecen una mirada aparte.
                    etiqueta += "  (nueva)"
                filas.append(ft.Row([
                    ft.Text(etiqueta, size=12, color=self.get_text_color(), width=220, no_wrap=False),
                    ft.Text(r["marca"] or "—", size=12, color=self.get_subtext_color(), width=110),
                    ft.Text(f"{r['cantidad']:g}", size=12, color=self.get_text_color(), width=60),
                    ft.Text(f"{r['costo_usd_efectivo']:.2f}", size=12, color=self.get_subtext_color(), width=80),
                    ft.Text(f"{r['precio_usd_efectivo']:.2f}", size=12, color=self.get_subtext_color(), width=80),
                    ft.TextButton(
                        content=ft.Text("Editar", size=12),
                        on_click=lambda ev, i=indice: self.mostrar_dialogo_editar_renglon(ev, i),
                    ),
                    ft.TextButton(
                        content=ft.Text("Quitar", size=12, color=ft.Colors.RED_400),
                        on_click=lambda ev, i=indice: self.quitar_renglon_pedido(ev, i),
                    ),
                ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER))
            self._pedido_lista_col.controls = filas

        if self._pedido_resumen_lbl is not None:
            self._pedido_resumen_lbl.value = (
                f"{len(renglones)} renglón(es) · {pedidos_service.total_unidades(sid):g} unidades · "
                f"Costo total ${pedidos_service.total_costo_efectivo(sid):.2f}"
            )
        self.safe_update(e)

    def mostrar_generador_pedido(self, e):
        """Diálogo principal: buscar el item en el banco de datos, armar el
        pedido y cerrarlo exportando el Excel."""
        p = self.get_current_page(e)
        if not p:
            return
        self._teclado.instalar(e)

        txt_busqueda = self._enlazar_foco(ft.TextField(
            label="Buscar item registrado (código, descripción o referencia)",
            prefix_icon=ft.Icons.SEARCH, dense=True, border_radius=10, expand=True,
            on_submit=lambda ev: self._buscar_items(ev, txt_busqueda, dd_criterio),
        ), "pedido_busqueda")
        dd_criterio = ft.Dropdown(
            label="Buscar por",
            value=CRITERIO_POR_DEFECTO,
            options=[ft.dropdown.Option(c) for c in CRITERIOS_BUSQUEDA],
            width=180, border_radius=10, dense=True,
        )
        self._pedido_resultados_col = ft.Column(controls=[], spacing=2)
        self._pedido_lista_col = ft.Column(controls=[], spacing=4)
        self._pedido_resumen_lbl = ft.Text("", size=12, weight=ft.FontWeight.BOLD, color=self.get_text_color())

        contenido = ft.Column([
            ft.Text(
                "El archivo que genere este asistente NO modifica el inventario: es el pedido que se le "
                "entrega al Administrador para que lo cargue por Carga Masiva de Datos una vez supervisado. "
                "Al cargarlo, la Cantidad recibida SE SUMA al stock que cada producto ya tiene.",
                size=12, color=self.get_subtext_color(),
            ),
            ft.Row([
                txt_busqueda,
                dd_criterio,
                ft.Button(
                    content=ft.Text("Buscar"),
                    bgcolor=self.get_accent_color(), color=ft.Colors.WHITE,
                    on_click=lambda ev: self._buscar_items(ev, txt_busqueda, dd_criterio),
                ),
            ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Container(
                content=self._pedido_resultados_col,
                padding=6, border_radius=10,
                bgcolor=self.get_card_bg(), border=ft.Border.all(1, self.get_border_color()),
            ),
            ft.Row([
                ft.Text("PEDIDO EN CURSO", size=12, weight=ft.FontWeight.BOLD, color=self.get_accent_color()),
                self._pedido_resumen_lbl,
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.Container(
                content=self._pedido_lista_col,
                padding=6, border_radius=10,
                bgcolor=self.get_card_bg(), border=ft.Border.all(1, self.get_border_color()),
            ),
            # El alta manual va separada del flujo principal: el PDF solo
            # contempla items ya registrados y esta es la excepción para las
            # piezas que llegan y todavía no existen en el banco de datos.
            ft.Row([
                ft.TextButton(
                    content=ft.Row([
                        ft.Icon(ft.Icons.NEW_LABEL_ROUNDED, size=18),
                        ft.Text("Agregar mercancía nueva (no registrada en el sistema)", size=12),
                    ], tight=True, spacing=6),
                    on_click=self.mostrar_dialogo_renglon_manual,
                ),
            ]),
        # Un solo dueño del eje vertical: el scroll vive acá y los bloques de
        # adentro crecen; anidar otro scroll vertical rompe el arrastre.
        ], spacing=10, tight=True, scroll=ft.ScrollMode.AUTO)

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.Icons.ADD_SHOPPING_CART_ROUNDED, color=self.get_accent_color()),
                ft.Text("Pedido de Nueva Mercancía", weight=ft.FontWeight.BOLD),
            ], spacing=10),
            content=ft.Container(content=contenido, width=900, height=620),
            actions=[
                ft.TextButton(content=ft.Text("Cerrar sin exportar"), on_click=self._cerrar_generador),
                ft.Button(
                    content=ft.Text("CERRAR PEDIDO Y EXPORTAR"),
                    bgcolor=self.get_accent_color(), color=ft.Colors.WHITE,
                    style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=12)),
                    on_click=self.mostrar_dialogo_cierre_pedido,
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )
        self._pedido_dlg = dlg
        # Mientras este modal esté arriba, las flechas arriba/abajo desplazan su
        # contenido (el único dueño del eje vertical del diálogo).
        self._registrar_scrolls(dlg, vertical=contenido)
        self._open_dialog(dlg, e)
        self._refrescar_pedido(e)

    def _cerrar_generador(self, e):
        """Cierra el asistente dejando el borrador intacto en memoria: el
        usuario puede volver más tarde y seguir armando el mismo pedido."""
        self._close_dialog(e, dialog=getattr(self, "_pedido_dlg", None))
        self.safe_update(e)

    def _buscar_items(self, e, txt_busqueda: ft.TextField, dd_criterio: ft.Dropdown):
        """Busca en el banco de datos de items registrados para no tener que
        rellenar todas las casillas del item (requisito del PDF)."""
        try:
            resultados = pedidos_service.buscar_items_para_pedido(
                txt_busqueda.value or "", criterio=dd_criterio.value or CRITERIO_POR_DEFECTO
            )
        except ValueError as ex:
            self.show_alert_error(e, str(ex))
            return

        if not resultados:
            self._pedido_resultados_col.controls = [
                ft.Text("Sin coincidencias en el banco de datos. Si la mercancía es nueva, use "
                        "'Agregar mercancía nueva'.", size=12, italic=True, color=self.get_subtext_color())
            ]
        else:
            self._pedido_resultados_col.controls = [
                ft.Row([
                    ft.Text(f"{prod['codigo']} — {prod.get('descripcion_general') or prod.get('nombre_referencia_corto') or ''}",
                            size=12, color=self.get_text_color(), expand=True),
                    ft.Text(prod.get("marca") or "—", size=12, color=self.get_subtext_color(), width=110),
                    ft.TextButton(
                        content=ft.Text("Agregar al pedido", size=12),
                        on_click=lambda ev, pr=prod: self.mostrar_dialogo_renglon(ev, pr),
                    ),
                ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)
                for prod in resultados
            ]
        self.safe_update(e)

    def _campos_casillas_renglon(self, valores: dict | None = None) -> dict:
        """Las pocas casillas que el PDF pide por renglón: Costo $/BCV, Precio
        Venta $/BCV, Marca y Cantidad. Todo lo demás lo trae el sistema."""
        v = valores or {}
        campos = {
            "costo_usd_efectivo": ft.TextField(
                label="Costo USD Efectivo", value=self._valor_texto(v.get("costo_usd_efectivo")),
                dense=True, border_radius=10, width=200),
            "costo_usd_bcv": ft.TextField(
                label="Costo USD BCV", value=self._valor_texto(v.get("costo_usd_bcv")),
                dense=True, border_radius=10, width=200),
            "precio_usd_efectivo": ft.TextField(
                label="Precio Venta USD Efectivo", value=self._valor_texto(v.get("precio_usd_efectivo")),
                dense=True, border_radius=10, width=200),
            "precio_usd_bcv": ft.TextField(
                label="Precio Venta USD BCV", value=self._valor_texto(v.get("precio_usd_bcv")),
                dense=True, border_radius=10, width=200),
            "marca": ft.TextField(
                label="Marca", value=str(v.get("marca") or ""),
                dense=True, border_radius=10, width=200),
            "cantidad": ft.TextField(
                label="Cantidad recibida", value=self._valor_texto(v.get("cantidad")),
                dense=True, border_radius=10, width=200),
        }
        # Son casillas numéricas que se corrigen con las flechas: si no
        # avisaran del foco, cada corrección movería la pantalla de atrás.
        for nombre, campo in campos.items():
            self._enlazar_foco(campo, f"renglon_{nombre}")
        return campos

    @staticmethod
    def _valor_texto(valor) -> str:
        """Número a texto para los TextField (sin decimales inútiles)."""
        if valor is None or valor == "":
            return ""
        try:
            return f"{float(valor):g}"
        except (TypeError, ValueError):
            return str(valor)

    def mostrar_dialogo_renglon(self, e, producto: dict):
        """Casillas a completar de un item YA REGISTRADO. La Marca viene
        pre-rellenada con la del producto y queda editable: la misma pieza puede
        llegar de otra marca en este pedido."""
        campos = self._campos_casillas_renglon({"marca": producto.get("marca") or ""})
        lbl_err = ft.Text("", color=ft.Colors.RED_500, size=12, weight=ft.FontWeight.BOLD)

        def _agregar(ev):
            try:
                pedidos_service.agregar_renglon_desde_banco(
                    self.get_session_id(ev),
                    codigo=producto["codigo"],
                    cantidad=campos["cantidad"].value,
                    costo_usd_efectivo=campos["costo_usd_efectivo"].value,
                    costo_usd_bcv=campos["costo_usd_bcv"].value,
                    precio_usd_efectivo=campos["precio_usd_efectivo"].value,
                    precio_usd_bcv=campos["precio_usd_bcv"].value,
                    marca=campos["marca"].value,
                )
            except ValueError as ex:
                lbl_err.value = str(ex)
                self.safe_update(ev)
                return
            self._close_dialog(ev, dialog=dlg)
            self._refrescar_pedido(ev)

        ficha = ft.Column([
            ft.Text(f"Código: {producto['codigo']}", size=13, weight=ft.FontWeight.BOLD, color=self.get_text_color()),
            ft.Text(f"Descripción: {producto.get('descripcion_general') or ''}", size=12, color=self.get_subtext_color()),
            ft.Text(f"Referencia: {producto.get('referencia') or '—'} · Departamento: "
                    f"{producto.get('departamento') or '—'} / {producto.get('sub_departamento') or '—'}",
                    size=12, color=self.get_subtext_color()),
        ], spacing=2)

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Completar casillas del renglón", weight=ft.FontWeight.BOLD),
            content=ft.Container(
                content=ft.Column([
                    ficha,
                    ft.Divider(height=10),
                    ft.ResponsiveRow([campos[c] for c in pedidos_service.CAMPOS_EDITABLES_RENGLON], spacing=10),
                    lbl_err,
                ], spacing=10, tight=True),
                width=520,
            ),
            actions=[
                ft.TextButton(content=ft.Text("Cancelar"), on_click=lambda ev: self._close_dialog(ev, dialog=dlg)),
                ft.Button(
                    content=ft.Text("Agregar al pedido"),
                    bgcolor=self.get_accent_color(), color=ft.Colors.WHITE, on_click=_agregar,
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )
        self._open_dialog(dlg, e)

    def mostrar_dialogo_renglon_manual(self, e):
        """Alta de un renglón para mercancía que NO está en el banco de datos.

        Flujo aparte del principal a propósito: el PDF solo contempla items ya
        registrados, pero un pedido real trae piezas nuevas y el empleado no
        puede crearlas en el sistema. Se piden los datos que la Carga Masiva
        necesita para poder abrir la ficha al importar.
        """
        campos = self._campos_casillas_renglon()
        txt_codigo = self._enlazar_foco(
            ft.TextField(label="Código (obligatorio)", dense=True, border_radius=10, width=200), "manual_codigo")
        txt_desc = self._enlazar_foco(
            ft.TextField(label="Descripción General (obligatoria)", dense=True, border_radius=10, expand=True), "manual_desc")
        txt_ref = self._enlazar_foco(
            ft.TextField(label="Referencia", dense=True, border_radius=10, width=200), "manual_ref")
        txt_depto = self._enlazar_foco(
            ft.TextField(label="Departamento", dense=True, border_radius=10, width=200), "manual_depto")
        txt_subdepto = self._enlazar_foco(
            ft.TextField(label="Sub-Departamento", dense=True, border_radius=10, width=200), "manual_subdepto")
        txt_barras = self._enlazar_foco(
            ft.TextField(label="Código de Barras", dense=True, border_radius=10, width=200), "manual_barras")
        lbl_err = ft.Text("", color=ft.Colors.RED_500, size=12, weight=ft.FontWeight.BOLD)

        def _agregar(ev):
            try:
                pedidos_service.agregar_renglon_manual(
                    self.get_session_id(ev),
                    codigo=txt_codigo.value,
                    descripcion_general=txt_desc.value,
                    cantidad=campos["cantidad"].value,
                    costo_usd_efectivo=campos["costo_usd_efectivo"].value,
                    costo_usd_bcv=campos["costo_usd_bcv"].value,
                    precio_usd_efectivo=campos["precio_usd_efectivo"].value,
                    precio_usd_bcv=campos["precio_usd_bcv"].value,
                    marca=campos["marca"].value,
                    referencia=txt_ref.value,
                    departamento=txt_depto.value,
                    sub_departamento=txt_subdepto.value,
                    codigo_barras=txt_barras.value,
                )
            except ValueError as ex:
                lbl_err.value = str(ex)
                self.safe_update(ev)
                return
            self._close_dialog(ev, dialog=dlg)
            self._refrescar_pedido(ev)

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.Icons.NEW_LABEL_ROUNDED, color=self.get_accent_color()),
                ft.Text("Mercancía nueva (no registrada)", weight=ft.FontWeight.BOLD),
            ], spacing=10),
            content=ft.Container(
                content=ft.Column([
                    ft.Text("Esta pieza no existe en el banco de datos. El Administrador la creará al "
                            "cargar el archivo; indique los datos mínimos para identificarla.",
                            size=12, color=self.get_subtext_color()),
                    ft.Divider(height=10),
                    ft.Row([txt_codigo, txt_desc], spacing=10),
                    ft.ResponsiveRow([txt_ref, txt_depto, txt_subdepto, txt_barras], spacing=10),
                    ft.Divider(height=10),
                    ft.ResponsiveRow([campos[c] for c in pedidos_service.CAMPOS_EDITABLES_RENGLON], spacing=10),
                    lbl_err,
                ], spacing=10, tight=True),
                width=560,
            ),
            actions=[
                ft.TextButton(content=ft.Text("Cancelar"), on_click=lambda ev: self._close_dialog(ev, dialog=dlg)),
                ft.Button(
                    content=ft.Text("Agregar al pedido"),
                    bgcolor=self.get_accent_color(), color=ft.Colors.WHITE, on_click=_agregar,
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )
        self._open_dialog(dlg, e)

    def mostrar_dialogo_editar_renglon(self, e, indice: int):
        """Edita las casillas de un renglón ya agregado (el pedido se revisa
        completo antes de exportarlo)."""
        sid = self.get_session_id(e)
        renglones = pedidos_service.obtener_renglones(sid)
        if not (0 <= indice < len(renglones)):
            return
        renglon = renglones[indice]
        campos = self._campos_casillas_renglon(renglon)
        lbl_err = ft.Text("", color=ft.Colors.RED_500, size=12, weight=ft.FontWeight.BOLD)

        def _guardar(ev):
            try:
                pedidos_service.editar_renglon(
                    self.get_session_id(ev), indice,
                    **{campo: campos[campo].value for campo in pedidos_service.CAMPOS_EDITABLES_RENGLON},
                )
            except ValueError as ex:
                lbl_err.value = str(ex)
                self.safe_update(ev)
                return
            self._close_dialog(ev, dialog=dlg)
            self._refrescar_pedido(ev)

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text(f"Editar renglón — {renglon['codigo']}", weight=ft.FontWeight.BOLD),
            content=ft.Container(
                content=ft.Column([
                    ft.Text(renglon["descripcion_general"], size=12, color=self.get_subtext_color()),
                    ft.Divider(height=10),
                    ft.ResponsiveRow([campos[c] for c in pedidos_service.CAMPOS_EDITABLES_RENGLON], spacing=10),
                    lbl_err,
                ], spacing=10, tight=True),
                width=520,
            ),
            actions=[
                ft.TextButton(content=ft.Text("Cancelar"), on_click=lambda ev: self._close_dialog(ev, dialog=dlg)),
                ft.Button(
                    content=ft.Text("Guardar cambios"),
                    bgcolor=self.get_accent_color(), color=ft.Colors.WHITE, on_click=_guardar,
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )
        self._open_dialog(dlg, e)

    def quitar_renglon_pedido(self, e, indice: int):
        """Quita un renglón del pedido en borrador."""
        pedidos_service.quitar_renglon(self.get_session_id(e), indice)
        self._refrescar_pedido(e)

    def mostrar_dialogo_cierre_pedido(self, e):
        """Cierre del pedido: Proveedor y Fecha de Recepción se piden UNA SOLA
        VEZ (así lo exige el PDF), no renglón por renglón.

        El Proveedor se elige entre los ya registrados en Cartera: el archivo
        viaja con su nombre de empresa y la Carga Masiva lo usa para enlazar el
        proveedor del producto al importar.
        """
        sid = self.get_session_id(e)
        if not pedidos_service.obtener_renglones(sid):
            self.show_alert_error(e, "El pedido está vacío: agregue al menos un renglón antes de exportarlo.")
            return

        from services.cartera_service import listar_proveedores
        proveedores = listar_proveedores()
        if not proveedores:
            self.show_alert_error(
                e, "No hay proveedores registrados. Registre el proveedor en Cartera antes de cerrar el pedido."
            )
            return

        dd_proveedor = ft.Dropdown(
            label="Proveedor (obligatorio)",
            options=[ft.dropdown.Option(pr["empresa"]) for pr in proveedores if pr.get("empresa")],
            width=360, border_radius=10,
        )
        txt_fecha = self._enlazar_foco(ft.TextField(
            label=f"Fecha de Recepción ({pedidos_service.FORMATO_FECHA_RECEPCION})",
            value=datetime.now().strftime("%d/%m/%Y"),
            dense=True, border_radius=10, width=200,
        ), "cierre_fecha")
        lbl_err = ft.Text("", color=ft.Colors.RED_500, size=12, weight=ft.FontWeight.BOLD)

        def _exportar(ev):
            try:
                proveedor = pedidos_service.validar_proveedor(dd_proveedor.value)
                fecha = pedidos_service.validar_fecha_recepcion(txt_fecha.value)
            except ValueError as ex:
                lbl_err.value = str(ex)
                self.safe_update(ev)
                return

            # El diálogo se cierra ANTES de abrir el selector nativo de archivo:
            # el modal de Tkinter bloquea el hilo y quedaría por encima.
            self._close_dialog(ev, dialog=dlg)
            self.exportar_pedido(ev, proveedor, fecha)

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.Icons.FACT_CHECK_ROUNDED, color=self.get_accent_color()),
                ft.Text("Cerrar pedido y exportar", weight=ft.FontWeight.BOLD),
            ], spacing=10),
            content=ft.Container(
                content=ft.Column([
                    ft.Text("Estos dos datos se piden una sola vez para todo el pedido.",
                            size=12, color=self.get_subtext_color()),
                    dd_proveedor,
                    txt_fecha,
                    ft.Text(
                        f"{len(pedidos_service.obtener_renglones(sid))} renglón(es) · "
                        f"{pedidos_service.total_unidades(sid):g} unidades",
                        size=12, weight=ft.FontWeight.BOLD, color=self.get_text_color(),
                    ),
                    # Último aviso antes de generar el archivo, y el más
                    # importante de los tres: el Administrador que lo reciba
                    # tiene que saber que está cargando una ENTRADA DE
                    # MERCANCÍA y no un catálogo. Si lo confundiera con un
                    # catálogo esperaría que el stock quedara en estos números,
                    # cuando en realidad se van a sumar a los actuales.
                    ft.Container(
                        content=ft.Row([
                            ft.Icon(ft.Icons.ADD_CIRCLE_OUTLINE_ROUNDED, color=self.get_accent_color(), size=20),
                            ft.Text(
                                "Este archivo es una ENTRADA DE MERCANCÍA: al cargarlo por Carga "
                                "Masiva, las cantidades SE SUMAN al stock existente de cada producto. "
                                "No es un catálogo ni una copia de seguridad.",
                                size=12, color=self.get_text_color(), expand=True, no_wrap=False,
                            ),
                        ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.START),
                        padding=10, border_radius=10,
                        bgcolor=self.get_card_bg(),
                        border=ft.Border.all(1, self.get_accent_color()),
                    ),
                    lbl_err,
                ], spacing=12, tight=True),
                width=420,
            ),
            actions=[
                ft.TextButton(content=ft.Text("Volver al pedido"), on_click=lambda ev: self._close_dialog(ev, dialog=dlg)),
                ft.Button(
                    content=ft.Text("GENERAR ARCHIVO EXCEL"),
                    bgcolor=self.get_accent_color(), color=ft.Colors.WHITE, on_click=_exportar,
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )
        self._open_dialog(dlg, e)

    def exportar_pedido(self, e, proveedor: str, fecha_recepcion: str):
        """Pide la ruta con el mismo diálogo nativo que la Copia de Seguridad y
        delega la escritura del Excel en el servicio."""
        last_dir = get_setting("last_excel_dir", default=None)
        if last_dir and not os.path.exists(last_dir):
            last_dir = None

        ruta_destino = self.abrir_dialogo_guardado(
            last_dir, pedidos_service.nombre_archivo_sugerido(proveedor)
        )
        if not ruta_destino:
            return

        try:
            resultado = pedidos_service.generar_archivo_pedido(
                self.get_session_id(e), ruta_destino, proveedor, fecha_recepcion
            )
        except ValueError as ex:
            self.show_alert_error(e, str(ex))
            return
        except Exception as ex:
            self.show_alert_error(e, f"Error al generar el archivo del pedido: {ex}")
            return

        directorio = os.path.dirname(ruta_destino)
        if directorio:
            set_setting("last_excel_dir", directorio)

        # Exportado el archivo, el borrador se descarta: el pedido ya salió del
        # sistema y dejarlo cargado haría que el siguiente pedido arrancara con
        # los renglones del anterior.
        pedidos_service.vaciar_pedido(self.get_session_id(e))
        self._cerrar_generador(e)
        self._refrescar_pedido(e)
        self.show_alert_success(
            e,
            f"{resultado['mensaje']}\nGuardado en: {resultado['ruta']}\n"
            "Es una ENTRADA DE MERCANCÍA: al cargarla por Carga Masiva, las cantidades "
            "se SUMAN al stock existente.",
        )
