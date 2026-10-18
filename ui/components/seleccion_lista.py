"""Modelo de selección de ítems para listas y tablas de la aplicación.

Nace del marcador del Inventario (Nueva Función 3 de la actualización de
octubre 2026), pero se escribe DESACOPLADO de esa vista a propósito: aquí no se
importa Flet ni ningún servicio, solo se guarda qué claves están marcadas y se
contesta quién puede accionar sus botones. Así el mismo modelo sirve para el
carrito de Ventas y para la lista de Deudas por Cobrar sin duplicar la
mecánica, y se puede probar sin montar interfaz.

Regla de oro del diseño (la más fácil de romper al cablear una vista):
SIN SELECCIÓN, TODO FUNCIONA COMO ANTES. Mientras no haya nada marcado,
`puede_accionar()` dice "sí" para cualquier ítem, de modo que los botones de
todas las filas siguen activos igual que en versiones anteriores. En cuanto hay
algo marcado, solo los ítems marcados pueden accionar; el resto debe quedar
deshabilitado VISIBLEMENTE (no ignorado en silencio: un botón que no responde
sin explicación se lee como un cuelgue).

Dos modos que conviven sobre el MISMO estado (un solo modelo por tabla, para
que no existan dos selecciones compitiendo por la misma fila):

  - `MODO_UNICO`: el marcador del PDF. Como máximo una clave marcada. Un clic
    en otra fila mueve el marcador; `alternar()` sobre la fila ya marcada la
    desmarca (es el "clic dentro de la casilla marcada"), y `limpiar()` es la
    tecla Esc.
  - `MODO_MULTIPLE`: el modo de lote para el borrado masivo. Varias claves
    marcadas a la vez, `alternar()` suma o quita y el orden de marcado se
    conserva (el diálogo de clave enumera el lote en el orden en que el usuario
    lo armó).

Transiciones entre modos, deliberadas:
  - Entrar al modo múltiple CONSERVA lo que ya estaba marcado: el ítem que el
    usuario venía señalando pasa a ser el primero del lote, sin obligarlo a
    volver a marcarlo.
  - Salir del modo múltiple LIMPIA todo. Volver al marcador único con cinco
    ítems marcados dejaría un estado que el modo único no puede representar
    (`seleccionado` sería arbitrario) y una tabla sombreada a medias; salir es
    la forma evidente de cancelar el lote.
"""

# Modos de selección (ver el encabezado del módulo para su semántica).
MODO_UNICO = "unico"
MODO_MULTIPLE = "multiple"

MODOS_VALIDOS = (MODO_UNICO, MODO_MULTIPLE)


class SeleccionLista:
    """Estado de selección de una lista, independiente de la interfaz.

    `on_cambio` es un callable sin argumentos que se invoca SOLO cuando el
    estado cambió de verdad (marcar lo ya marcado en modo único, por ejemplo,
    no notifica): la vista lo usa para repintar una vez por interacción real y
    no una por clic.
    """

    def __init__(self, on_cambio=None, modo: str = MODO_UNICO):
        if modo not in MODOS_VALIDOS:
            raise ValueError(f"Modo de selección desconocido: {modo!r}")
        self._modo = modo
        # `dict` y no `set`: las claves conservan el orden de marcado, que es el
        # orden en que se enumeran los ítems del lote ante el usuario.
        self._marcados: dict[str, None] = {}
        self._on_cambio = on_cambio

    # ── Lectura de estado ────────────────────────────────────────────────────
    @property
    def modo(self) -> str:
        return self._modo

    @property
    def es_multiple(self) -> bool:
        return self._modo == MODO_MULTIPLE

    @property
    def cantidad(self) -> int:
        return len(self._marcados)

    @property
    def hay_seleccion(self) -> bool:
        return bool(self._marcados)

    @property
    def seleccionado(self) -> str | None:
        """Última clave marcada, o `None` si no hay ninguna.

        En modo único es "la" clave marcada. En modo múltiple devuelve la más
        reciente, que es lo que necesita un atajo de teclado que actúa "sobre
        el ítem marcado" cuando hay un lote armado.
        """
        if not self._marcados:
            return None
        return next(reversed(self._marcados))

    @property
    def seleccionados(self) -> tuple[str, ...]:
        """Claves marcadas en orden de marcado (copia inmutable)."""
        return tuple(self._marcados)

    def esta_seleccionado(self, clave) -> bool:
        return self._normalizar(clave) in self._marcados

    def puede_accionar(self, clave) -> bool:
        """¿Este ítem puede accionar sus botones (info, cobrar, carrito,
        historial, editar, borrar)?

        Sin selección: SÍ para todos (regla "Importante" del PDF — el sistema
        sigue trabajando igual que la versión anterior). Con selección: solo
        los ítems marcados.
        """
        if not self._marcados:
            return True
        return self.esta_seleccionado(clave)

    def descripcion_estado(self) -> str:
        """Texto corto para que el usuario vea cuántos ítems lleva marcados."""
        n = self.cantidad
        if n == 0:
            return "Sin selección"
        return f"{n} ítem marcado" if n == 1 else f"{n} ítems marcados"

    # ── Mutación de estado ───────────────────────────────────────────────────
    def seleccionar(self, clave) -> bool:
        """Marca `clave`. En modo único desplaza el marcador; en múltiple suma.

        Nunca desmarca: es el clic en cualquier parte de la fila, que según el
        PDF solo puede marcar (para desmarcar están la casilla y Esc). Devuelve
        True si el estado cambió.
        """
        clave = self._normalizar(clave)
        if not clave:
            return False
        if self._modo == MODO_UNICO:
            if tuple(self._marcados) == (clave,):
                return False
            self._marcados = {clave: None}
            return self._notificar()
        if clave in self._marcados:
            return False
        self._marcados[clave] = None
        return self._notificar()

    def alternar(self, clave) -> bool:
        """Marca o desmarca `clave`: es el clic DENTRO de la casilla marcadora.

        Es la primera de las dos únicas formas de deseleccionar que admite el
        PDF (la otra es `limpiar()`, la tecla Esc).
        """
        clave = self._normalizar(clave)
        if not clave:
            return False
        if clave in self._marcados:
            del self._marcados[clave]
            return self._notificar()
        return self.seleccionar(clave)

    def limpiar(self) -> bool:
        """Quita toda la selección (tecla Esc). No cambia el modo."""
        if not self._marcados:
            return False
        self._marcados = {}
        return self._notificar()

    def activar_modo_multiple(self) -> bool:
        """Entra al modo de lote conservando lo ya marcado (ver encabezado)."""
        if self._modo == MODO_MULTIPLE:
            return False
        self._modo = MODO_MULTIPLE
        return self._notificar()

    def desactivar_modo_multiple(self) -> bool:
        """Sale del modo de lote y limpia la selección (ver encabezado)."""
        if self._modo == MODO_UNICO and not self._marcados:
            return False
        self._modo = MODO_UNICO
        self._marcados = {}
        return self._notificar()

    def alternar_modo(self) -> bool:
        """Entrar/salir del modo de lote con un solo control de interfaz."""
        if self.es_multiple:
            return self.desactivar_modo_multiple()
        return self.activar_modo_multiple()

    def descartar(self, claves) -> bool:
        """Olvida claves que ya no existen (p. ej. tras borrar el lote).

        Sin esto, el código de un ítem borrado seguiría marcado y bloquearía
        los botones de todas las filas vivas por una selección fantasma.
        """
        objetivo = {self._normalizar(c) for c in (claves or ())}
        restantes = {k: None for k in self._marcados if k not in objetivo}
        if len(restantes) == len(self._marcados):
            return False
        self._marcados = restantes
        return self._notificar()

    # ── Internos ─────────────────────────────────────────────────────────────
    @staticmethod
    def _normalizar(clave) -> str:
        """Las claves viajan como texto (códigos de producto, ids): se compara
        siempre sobre `str` sin espacios para que `1` y `"1"` no sean dos ítems."""
        if clave is None:
            return ""
        return str(clave).strip()

    def _notificar(self) -> bool:
        if self._on_cambio is not None:
            self._on_cambio()
        return True
