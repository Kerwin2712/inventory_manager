"""Selectores jerárquicos Departamento → Sub-Departamento.

Toda la lógica vive aquí (no en la vista) y las fuentes de datos entran por
INYECCIÓN DE DEPENDENCIAS: el componente recibe funciones proveedoras, nunca
importa `departamentos_service`. Así se puede probar con proveedores falsos y
sin base de datos, y la vista solo cablea los servicios reales.

Reglas de la jerarquía:
  - El dropdown de Departamento lista el catálogo ordenado y termina SIEMPRE
    con "Registrar nuevo departamento", que despliega un campo de texto.
  - El dropdown de Sub-Departamento solo es visible/habilitado cuando
    Departamento tiene un valor real seleccionado (ni vacío ni la opción
    especial), y lista únicamente los hijos de ese padre.
  - Cambiar de padre RESETEA la selección de sub-departamento y recarga su
    lista: un sub-departamento nunca queda colgando de otro departamento.

Headless-safe: ningún método asume que exista una `page` viva; los refrescos
van por el callback `on_cambio` o por `control.update()` protegido.
"""
import flet as ft

# Claves sentinela de las opciones especiales (no son nombres de departamento).
OPCION_NUEVO_DEPARTAMENTO = "__nuevo_departamento__"
OPCION_NUEVO_SUB_DEPARTAMENTO = "__nuevo_sub_departamento__"

ETIQUETA_NUEVO_DEPARTAMENTO = "Registrar nuevo departamento"
ETIQUETA_NUEVO_SUB_DEPARTAMENTO = "Registrar nuevo sub-departamento"


def _ordenar_alfabetico(valores) -> list[str]:
    """Orden alfabético estricto, insensible a mayúsculas y estable.

    Mismo criterio que `departamentos_service._ordenar_alfabetico` para que el
    catálogo se vea igual en los selectores y en los filtros: la clave es
    `(valor.lower(), valor)`, de modo que las vocales acentuadas ordenan por su
    punto de código (después de la `z`).
    """
    return sorted(valores, key=lambda v: (v.lower(), v))


def _limpiar(valores) -> list[str]:
    """Descarta vacíos y deduplica (case-insensitive, gana la primera forma)."""
    vistos: dict[str, str] = {}
    for v in valores or []:
        limpio = (str(v) if v is not None else "").strip()
        if limpio and limpio.lower() not in vistos:
            vistos[limpio.lower()] = limpio
    return list(vistos.values())


def construir_opciones(valores: list[str], etiqueta_nuevo: str, clave_nueva: str) -> list[ft.dropdown.Option]:
    """Opciones de un dropdown del catálogo: valores ordenados y sin repetir,
    con la opción especial "Registrar nuevo…" SIEMPRE en la última posición."""
    opciones = [
        ft.dropdown.Option(key=v, text=v)
        for v in _ordenar_alfabetico(_limpiar(valores))
    ]
    opciones.append(ft.dropdown.Option(key=clave_nueva, text=etiqueta_nuevo))
    return opciones


class SelectorDepartamentos:
    """Par de dropdowns dependientes con sus campos de "nuevo valor".

    `obtener_departamentos()` devuelve los nombres del catálogo y
    `obtener_sub_departamentos(departamento)` los hijos de un padre concreto.
    Los callbacks `on_crear_*` son opcionales: solo los usa
    `confirmar_creacion()`, para consumidores que no persistan el catálogo por
    otra vía.
    """

    def __init__(
        self,
        obtener_departamentos,
        obtener_sub_departamentos,
        *,
        on_crear_departamento=None,
        on_crear_sub_departamento=None,
        on_cambio=None,
        ancho: int = 220,
        color_texto=None,
        color_borde=None,
        color_acento=None,
    ):
        self._obtener_departamentos = obtener_departamentos
        self._obtener_sub_departamentos = obtener_sub_departamentos
        self.on_crear_departamento = on_crear_departamento
        self.on_crear_sub_departamento = on_crear_sub_departamento
        self.on_cambio = on_cambio

        estilo = dict(
            color=color_texto, border_color=color_borde,
            focused_border_color=color_acento, border_radius=12,
        )

        self.dd_departamento = ft.Dropdown(
            label="Departamento *",
            width=ancho,
            options=[],
            on_select=self.manejar_cambio_departamento,
            **estilo,
        )
        self.tf_nuevo_departamento = ft.TextField(
            label="Nombre del nuevo departamento *",
            width=ancho,
            visible=False,
            **estilo,
        )
        self.dd_sub_departamento = ft.Dropdown(
            label="Sub-Departamento",
            width=ancho,
            options=[],
            visible=False,
            disabled=True,
            on_select=self.manejar_cambio_sub_departamento,
            **estilo,
        )
        self.tf_nuevo_sub_departamento = ft.TextField(
            label="Nombre del nuevo sub-departamento",
            width=ancho,
            visible=False,
            **estilo,
        )

        self.recargar_departamentos()

    # ── Composición ──────────────────────────────────────────────────────────
    @property
    def controles(self) -> list[ft.Control]:
        """Los cuatro controles, en orden de lectura."""
        return [
            self.dd_departamento, self.tf_nuevo_departamento,
            self.dd_sub_departamento, self.tf_nuevo_sub_departamento,
        ]

    def construir_fila(self, spacing: int = 12) -> ft.Row:
        """Fila lista para insertar en un formulario (envuelve si falta ancho)."""
        return ft.Row(controls=self.controles, spacing=spacing, wrap=True)

    # ── Lectura de valores ───────────────────────────────────────────────────
    @staticmethod
    def _es_departamento_real(valor) -> bool:
        """True solo si hay un departamento existente seleccionado (la opción
        "Registrar nuevo…" y el vacío NO cuentan como padre)."""
        return bool((valor or "").strip()) and valor != OPCION_NUEVO_DEPARTAMENTO

    @property
    def creando_departamento(self) -> bool:
        return self.dd_departamento.value == OPCION_NUEVO_DEPARTAMENTO

    @property
    def creando_sub_departamento(self) -> bool:
        return self.dd_sub_departamento.value == OPCION_NUEVO_SUB_DEPARTAMENTO

    def valor_departamento(self) -> str:
        """Nombre del departamento elegido, o el texto escrito si se está
        registrando uno nuevo. Cadena vacía si no hay nada seleccionado."""
        if self.creando_departamento:
            return (self.tf_nuevo_departamento.value or "").strip()
        return (self.dd_departamento.value or "").strip()

    def valor_sub_departamento(self) -> str:
        """Nombre del sub-departamento elegido (o el escrito). Vacío si el
        departamento padre no es real: sin padre no hay hijo."""
        if not self._es_departamento_real(self.dd_departamento.value):
            return ""
        if self.creando_sub_departamento:
            return (self.tf_nuevo_sub_departamento.value or "").strip()
        return (self.dd_sub_departamento.value or "").strip()

    # ── Carga y precarga ─────────────────────────────────────────────────────
    def recargar_departamentos(self, seleccion: str = "") -> None:
        """Relee el catálogo de padres. Si `seleccion` no está en el catálogo
        (valor histórico de un producto ya guardado) se inyecta para no
        perderlo."""
        valores = list(self._llamar(self._obtener_departamentos) or [])
        elegido = (seleccion or "").strip()
        if elegido and elegido.lower() not in {v.strip().lower() for v in _limpiar(valores)}:
            valores.append(elegido)
        self.dd_departamento.options = construir_opciones(
            valores, ETIQUETA_NUEVO_DEPARTAMENTO, OPCION_NUEVO_DEPARTAMENTO
        )
        self.dd_departamento.value = elegido or None

    def _recargar_sub_departamentos(self, padre: str, seleccion: str = "") -> None:
        """Repuebla los hijos de `padre`; sin padre real, la lista queda vacía."""
        if not self._es_departamento_real(padre):
            self.dd_sub_departamento.options = []
            self.dd_sub_departamento.value = None
            return
        valores = list(self._llamar(self._obtener_sub_departamentos, padre) or [])
        elegido = (seleccion or "").strip()
        if elegido and elegido.lower() not in {v.strip().lower() for v in _limpiar(valores)}:
            valores.append(elegido)
        self.dd_sub_departamento.options = construir_opciones(
            valores, ETIQUETA_NUEVO_SUB_DEPARTAMENTO, OPCION_NUEVO_SUB_DEPARTAMENTO
        )
        self.dd_sub_departamento.value = elegido or None

    def set_valores(self, departamento: str = "", sub_departamento: str = "") -> None:
        """Precarga el par (modo edición) y ajusta visibilidades."""
        self.recargar_departamentos(departamento)
        self._recargar_sub_departamentos(departamento, sub_departamento)
        self.tf_nuevo_departamento.value = ""
        self.tf_nuevo_sub_departamento.value = ""
        self._aplicar_visibilidad()

    # ── Handlers (invocables sin `page`, con `e=None`) ────────────────────────
    def manejar_cambio_departamento(self, e=None) -> None:
        """Cambio de padre: resetea el hijo y recarga su lista."""
        padre = self.dd_departamento.value
        self.dd_sub_departamento.value = None
        self.tf_nuevo_sub_departamento.value = ""
        if not self.creando_departamento:
            self.tf_nuevo_departamento.value = ""
        self._recargar_sub_departamentos(padre)
        self._aplicar_visibilidad()
        self._notificar(e)

    def manejar_cambio_sub_departamento(self, e=None) -> None:
        """Cambio de hijo: solo alterna el campo de "nuevo sub-departamento"."""
        if not self.creando_sub_departamento:
            self.tf_nuevo_sub_departamento.value = ""
        self._aplicar_visibilidad()
        self._notificar(e)

    def _aplicar_visibilidad(self) -> None:
        """Única fuente de verdad de la visibilidad de los cuatro controles."""
        padre_real = self._es_departamento_real(self.dd_departamento.value)

        self.tf_nuevo_departamento.visible = self.creando_departamento
        # Sin padre real no hay sub-departamento posible: ni visible ni usable
        # (tampoco al elegir "Registrar nuevo departamento": ese padre todavía
        # no existe en el catálogo).
        self.dd_sub_departamento.visible = padre_real
        self.dd_sub_departamento.disabled = not padre_real
        self.tf_nuevo_sub_departamento.visible = padre_real and self.creando_sub_departamento

    # ── Validación y persistencia del catálogo ───────────────────────────────
    def marcar_error(self, mensaje: str = "Campo obligatorio") -> None:
        """Resalta en rojo el control que falta (el dropdown o, si se está
        registrando uno nuevo, el campo de texto)."""
        if self.creando_departamento:
            self.tf_nuevo_departamento.error_text = mensaje
        else:
            self.dd_departamento.error_text = mensaje

    def limpiar_errores(self) -> None:
        self.dd_departamento.error_text = None
        self.tf_nuevo_departamento.error_text = None
        self.dd_sub_departamento.error_text = None
        self.tf_nuevo_sub_departamento.error_text = None

    def confirmar_creacion(self) -> tuple[str, str]:
        """Persiste los valores nuevos con los callbacks `on_crear_*` y
        devuelve el par canónico `(departamento, sub_departamento)`.

        Solo hace falta cuando el consumidor no guarda por un servicio que ya
        registre el catálogo (el inventario sí lo hace: `crear_producto` /
        `actualizar_producto` llaman a `registrar_desde_producto`).
        """
        depto = self.valor_departamento()
        sub = self.valor_sub_departamento()
        if depto and self.creando_departamento and self.on_crear_departamento:
            depto = self._llamar(self.on_crear_departamento, depto) or depto
        if depto and sub and self.creando_sub_departamento and self.on_crear_sub_departamento:
            sub = self._llamar(self.on_crear_sub_departamento, depto, sub) or sub
        return depto, sub

    # ── Utilidades internas ──────────────────────────────────────────────────
    @staticmethod
    def _llamar(funcion, *args):
        """Invoca un proveedor/callback inyectado sin dejar que un fallo suyo
        (base caída, servicio ausente) tumbe el formulario."""
        if not callable(funcion):
            return None
        try:
            return funcion(*args)
        except Exception:
            return None

    def _notificar(self, e=None) -> None:
        """Refresca la interfaz: por el callback inyectado si lo hay, o con un
        `update()` por control protegido (headless no hay `page`)."""
        if callable(self.on_cambio):
            try:
                self.on_cambio(e)
            except TypeError:
                try:
                    self.on_cambio()
                except Exception:
                    pass
            except Exception:
                pass
            return
        for control in self.controles:
            try:
                control.update()
            except Exception:
                pass
