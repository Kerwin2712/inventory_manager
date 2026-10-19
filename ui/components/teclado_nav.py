"""Modelo de los atajos de teclado: navegación con flechas y acciones F1–F6.

Este módulo es **lógica pura, sin Flet**: traduce un evento de teclado a una
*intención* y deja que la vista decida cómo ejecutarla. Está separado así por
dos razones concretas:

1. Las mismas teclas tienen que funcionar en cuatro listas distintas
   (Inventario separado, Inventario agrupado, carrito de Ventas y Deudas por
   Cobrar). Si la decisión de "qué significa esta tecla" viviera en cada
   vista, tendríamos cuatro interpretaciones que se van separando con el
   tiempo.
2. El comportamiento delicado —cuándo una flecha navega la vista y cuándo
   edita texto— se puede testear sin levantar la interfaz.

## La regla del foco (decisión del usuario del proyecto)

Las flechas desplazan la vista **solo cuando ningún campo de texto tiene el
foco**. Si el cursor está dentro de un `TextField` (el buscador, un filtro, un
formulario), las flechas mueven el cursor como en cualquier programa: nadie
espera que al corregir una palabra se le mueva la pantalla. Flet no expone un
"¿quién tiene el foco?" global, así que el foco se lleva a mano con
`RegistroFoco`: cada campo relevante avisa al tomar y al soltar el foco, y
este módulo consulta ese registro. Es contabilidad explícita, pero es la
única forma de que la regla sea verificable.

`Escape` libera el foco además de limpiar la selección, para que el usuario
pueda volver a navegar sin tener que buscar un hueco de la pantalla donde
hacer clic.
"""
from dataclasses import dataclass, field

# ─── Intenciones de navegación ───────────────────────────────────────────────

# Las cuatro direcciones de scroll, más el salto al extremo (Ctrl + flecha).
ARRIBA = "arriba"
ABAJO = "abajo"
IZQUIERDA = "izquierda"
DERECHA = "derecha"

# Qué hacer con la dirección: un paso, o hasta el final de ese eje.
PASO = "paso"
EXTREMO = "extremo"

# Intenciones que no son de scroll.
LIMPIAR_SELECCION = "limpiar_seleccion"

# Nombres de tecla tal como los entrega Flet en `KeyboardEvent.key`.
_FLECHAS = {
    "Arrow Up": ARRIBA,
    "Arrow Down": ABAJO,
    "Arrow Left": IZQUIERDA,
    "Arrow Right": DERECHA,
}

_ESCAPE = "Escape"


@dataclass(frozen=True)
class IntencionScroll:
    """Mover la vista: `direccion` en uno de los cuatro sentidos, `alcance`
    un paso (`PASO`) o hasta el final del eje (`EXTREMO`, con Ctrl)."""
    direccion: str
    alcance: str

    @property
    def eje(self) -> str:
        return "vertical" if self.direccion in (ARRIBA, ABAJO) else "horizontal"

    @property
    def signo(self) -> int:
        """-1 hacia arriba/izquierda, +1 hacia abajo/derecha."""
        return -1 if self.direccion in (ARRIBA, IZQUIERDA) else 1


@dataclass(frozen=True)
class IntencionAccion:
    """Accionar uno de los íconos del ítem marcado (F1–F6)."""
    accion: str
    tecla: str


@dataclass(frozen=True)
class IntencionSimple:
    """Intención sin parámetros (hoy solo `LIMPIAR_SELECCION`)."""
    nombre: str


# ─── Atajos de los íconos del ítem (F1–F6) ───────────────────────────────────

# Mapeo FIJO por decisión del usuario del proyecto: la misma tecla hace lo
# mismo para todos los roles. El Historial Clínico solo existe para
# administradores, así que para un vendedor F4 simplemente no hace nada — se
# prefirió eso a correr la numeración, porque una tecla que cambia de
# significado según quién tenga la sesión abierta es una trampa para quien
# aprende los atajos en una máquina y los usa en otra.
ATAJOS_ITEM: dict[str, str] = {
    "F1": "info",
    "F2": "cobrar",
    "F3": "carrito",
    "F4": "historial",
    "F5": "editar",
    "F6": "borrar",
}

# Inverso, para que la vista pueda etiquetar cada ícono con su tecla sin
# recorrer el diccionario a mano.
TECLA_POR_ACCION: dict[str, str] = {accion: tecla for tecla, accion in ATAJOS_ITEM.items()}

# Acciones reservadas a los administradores: la tecla se reconoce igual, pero
# la vista no debe ejecutarla si el rol no corresponde.
ACCIONES_SOLO_ADMIN = ("historial",)

# Acciones que exigen la clave del usuario antes de ejecutarse.
ACCIONES_CON_CLAVE = ("borrar",)


def etiqueta_atajo(accion: str) -> str:
    """Texto corto para mostrar sobre el ícono (`"F1"`, `"F6"`, …).

    El PDF pide que los atajos estén a la vista para "siempre ser consciente
    de ellos": un atajo que hay que recordar de memoria no se usa.
    """
    return TECLA_POR_ACCION.get(accion, "")


def tooltip_con_atajo(descripcion: str, accion: str) -> str:
    """`"Editar"` → `"Editar (F5)"`. Devuelve la descripción intacta si la
    acción no tiene atajo asignado."""
    tecla = etiqueta_atajo(accion)
    return f"{descripcion} ({tecla})" if tecla else descripcion


# ─── Registro de foco ────────────────────────────────────────────────────────

@dataclass
class RegistroFoco:
    """Lleva la cuenta de qué campos de texto tienen el foco.

    Se usa un conjunto y no una bandera booleana porque los eventos de foco
    llegan desordenados: al pasar de un campo a otro, Flet puede entregar el
    `on_focus` del nuevo antes que el `on_blur` del anterior. Con una bandera,
    ese cruce la dejaría en `False` teniendo todavía el cursor dentro de un
    campo, y las flechas empezarían a mover la pantalla mientras el usuario
    escribe. Con un conjunto el orden deja de importar.
    """
    _con_foco: set[str] = field(default_factory=set)

    def tomar(self, nombre: str) -> None:
        self._con_foco.add(nombre)

    def soltar(self, nombre: str) -> None:
        self._con_foco.discard(nombre)

    def limpiar(self) -> None:
        """Suelta todo (lo que hace `Escape`)."""
        self._con_foco.clear()

    @property
    def hay_campo_con_foco(self) -> bool:
        return bool(self._con_foco)

    def enlazar(self, campo, nombre: str):
        """Conecta un `TextField` de Flet a este registro.

        No importa Flet: solo asigna `on_focus`/`on_blur`, así que funciona
        igual con un doble de prueba. Devuelve el campo para poder encadenar.
        """
        campo.on_focus = lambda _e, n=nombre: self.tomar(n)
        campo.on_blur = lambda _e, n=nombre: self.soltar(n)
        return campo


# ─── Traducción del evento ───────────────────────────────────────────────────

def interpretar(
    tecla: str,
    ctrl: bool = False,
    shift: bool = False,
    alt: bool = False,
    meta: bool = False,
    hay_campo_con_foco: bool = False,
    hay_seleccion: bool = False,
):
    """Traduce una pulsación a una intención, o `None` si no significa nada.

    - Flechas → `IntencionScroll` con alcance `PASO`, o `EXTREMO` con Ctrl.
      Se ignoran si hay un campo de texto con el foco (ahí las flechas son
      del cursor) o si vienen con Alt/Meta, que son combinaciones del sistema
      operativo y de la propia aplicación.
    - `F1`–`F6` → `IntencionAccion` sobre el ítem marcado. Requieren
      selección: sin ítem marcado no hay sobre qué actuar, y adivinar uno
      sería disparar una acción —incluido un borrado— sobre algo que el
      usuario no eligió.
    - `Escape` → `LIMPIAR_SELECCION`. Es la única intención que sigue viva
      con un campo enfocado, precisamente porque su trabajo es soltar el
      foco y devolver la navegación.
    """
    nombre = (tecla or "").strip()
    if not nombre:
        return None

    if nombre == _ESCAPE:
        return IntencionSimple(LIMPIAR_SELECCION)

    # Shift no se mira: un Shift+flecha dentro de un campo es una selección de
    # texto, y fuera de un campo no tiene un significado propio todavía.
    if alt or meta:
        return None

    if nombre in _FLECHAS:
        if hay_campo_con_foco:
            return None
        return IntencionScroll(
            direccion=_FLECHAS[nombre],
            alcance=EXTREMO if ctrl else PASO,
        )

    if nombre in ATAJOS_ITEM:
        # Con el foco en un campo de texto las teclas de función no editan
        # nada, así que sí pueden actuar; lo que no puede faltar es el ítem
        # marcado.
        if ctrl or not hay_seleccion:
            return None
        return IntencionAccion(accion=ATAJOS_ITEM[nombre], tecla=nombre)

    return None


def interpretar_evento(evento, hay_campo_con_foco: bool = False, hay_seleccion: bool = False):
    """Igual que `interpretar`, tomando directamente el `KeyboardEvent` de
    Flet (`page.on_keyboard_event`). Los atributos se leen con `getattr` para
    que un doble de prueba pueda traer solo `key`."""
    return interpretar(
        tecla=getattr(evento, "key", "") or "",
        ctrl=bool(getattr(evento, "ctrl", False)),
        shift=bool(getattr(evento, "shift", False)),
        alt=bool(getattr(evento, "alt", False)),
        meta=bool(getattr(evento, "meta", False)),
        hay_campo_con_foco=hay_campo_con_foco,
        hay_seleccion=hay_seleccion,
    )


# ─── Traducción de la intención a un desplazamiento ──────────────────────────

# Un paso de scroll por pulsación. El vertical es menor que el horizontal
# porque una fila mide bastante menos que una columna de la tabla ancha.
PASO_VERTICAL = 200.0
PASO_HORIZONTAL = 280.0

# Valor grande que Flutter acota al límite real del scroll: es como se
# implementa "hasta el final" sin tener que medir el contenido.
_EXTREMO = 999999.0


def desplazamiento(intencion: IntencionScroll) -> dict:
    """Convierte una `IntencionScroll` en los argumentos de `scroll_to`.

    Devuelve `{"offset": 0.0}` para el inicio del eje (Ctrl+Arriba o
    Ctrl+Izquierda) y `{"delta": ...}` en los demás casos. Se usa `offset` y
    no un delta negativo enorme para ir al principio porque `offset=0` es
    exacto, mientras que un delta se acumula sobre la posición actual.
    """
    if intencion.alcance == EXTREMO:
        if intencion.signo < 0:
            return {"offset": 0.0}
        return {"delta": _EXTREMO}

    paso = PASO_VERTICAL if intencion.eje == "vertical" else PASO_HORIZONTAL
    return {"delta": paso * intencion.signo}


# ─── Instalación en una página de Flet ───────────────────────────────────────

class ControlTeclado:
    """Engancha los atajos a la página de Flet de una vista concreta.

    Cada vista le dice qué desplazar y qué accionar; la decisión de qué
    significa cada tecla queda en `interpretar`, compartida por todas. Así las
    cuatro listas de la aplicación se comportan igual sin repetir la mecánica.

    Puntos delicados, todos aprendidos a golpes en este proyecto:

    - **La página se comparte.** La vista vive dentro del Dashboard, que puede
      tener su propio `on_keyboard_event`. El handler anterior se guarda y se
      sigue invocando siempre, de modo que instalar los atajos de una lista no
      le roba el teclado al resto de la aplicación.
    - **La instalación es perezosa.** Al construir la vista todavía no hay
      `page` (se instancia headless y se monta después), así que `instalar()`
      se llama desde los puntos donde ya hay evento y es idempotente.
    - **El handler es `async`.** `Control.scroll_to(...)` es una corutina: un
      handler síncrono que la llamara sin `await` crearía la corutina y la
      descartaría sin ejecutarla, sin lanzar error. Las flechas simplemente no
      harían nada y no habría rastro de por qué.
    - **Los destinos de scroll son invocables.** La tabla se reconstruye en
      cada repintado, así que guardar el control desplazaría un control viejo
      que ya no está en pantalla; guardar una función que lo busca devuelve
      siempre el vigente.
    """

    def __init__(
        self,
        obtener_pagina,
        destino_vertical=None,
        destino_horizontal=None,
        seleccion=None,
        ejecutar_accion=None,
        al_limpiar=None,
        registro_foco: RegistroFoco | None = None,
        identidad: str | None = None,
    ):
        self._obtener_pagina = obtener_pagina
        self._destino_vertical = destino_vertical
        self._destino_horizontal = destino_horizontal
        self._seleccion = seleccion
        self._ejecutar_accion = ejecutar_accion
        self._al_limpiar = al_limpiar
        self.foco = registro_foco or RegistroFoco()
        self._handler_previo = None
        self._instalado = False
        # Identidad logica de la vista que instala este control, p. ej.
        # "ventas". Dos controles con la MISMA identidad son la misma pantalla
        # reconstruida, no dos pantallas distintas, y el nuevo RELEVA al viejo
        # en vez de encadenarse a el (ver `instalar`). Sin identidad se
        # encadena siempre, que es el comportamiento conservador.
        self.identidad = identidad

        # Referencia ESTABLE al handler, con el dueno colgado encima para que
        # otra instalacion pueda reconocer quien tiene hoy el teclado.
        # `self.manejar` crea un método ligado nuevo en cada acceso, así que
        # `pagina.on_keyboard_event is self.manejar` siempre era falso: la
        # guarda de reinstalación no disparaba nunca y el control acababa
        # encadenado a sí mismo, con lo que una sola flecha se procesaba
        # cientos de veces.
        self._handler = self._crear_handler()

    def _crear_handler(self):
        """Envoltorio del handler con una referencia al control que lo creó.

        Se usa una función con atributo en vez del método ligado para poder
        preguntarle a `page.on_keyboard_event` de quién es: es lo que permite
        relevar a un control de la misma vista en lugar de encadenarse a él.
        """
        async def handler(e=None):
            await self.manejar(e)

        handler._control_teclado = self
        return handler

    # ── Instalación ─────────────────────────────────────────────────────────
    @property
    def instalado(self) -> bool:
        return self._instalado

    @property
    def handler(self):
        """El invocable que queda en `page.on_keyboard_event`."""
        return self._handler

    def instalar(self, e=None) -> bool:
        """Toma el teclado de la página. Idempotente; `False` si no hay página
        o no soporta teclado (ahí los botones en pantalla suplen a las teclas)."""
        pagina = self._pagina(e)
        if pagina is None:
            return False
        try:
            actual = getattr(pagina, "on_keyboard_event", None)
            if actual is self._handler:
                self._instalado = True
                return True

            # Si quien tiene el teclado es un control de ESTA MISMA vista
            # (misma identidad), es la pantalla anterior reconstruida: la
            # relevamos y heredamos su handler previo, en vez de encadenarnos
            # a ella. Encadenarse hacía crecer la cadena sin tope — el
            # Dashboard reemplaza sus vistas en cada repintado —, de modo que
            # una sola pulsación recorría todas las instancias pasadas y las
            # viejas seguían actuando sobre controles que ya no estaban en
            # pantalla (un atajo se ejecutaba dos veces, y la segunda abría un
            # diálogo sobre una tabla invisible).
            anterior = getattr(actual, "_control_teclado", None)
            if (
                anterior is not None
                and self.identidad is not None
                and anterior.identidad == self.identidad
            ):
                self._handler_previo = anterior._handler_previo
                anterior._instalado = False
            else:
                self._handler_previo = actual

            pagina.on_keyboard_event = self._handler
        except (AttributeError, RuntimeError):
            return False
        self._instalado = True
        return True

    def desinstalar(self, e=None) -> bool:
        """Devuelve el teclado al handler anterior."""
        pagina = self._pagina(e)
        if pagina is None:
            return False
        try:
            if getattr(pagina, "on_keyboard_event", None) is self._handler:
                pagina.on_keyboard_event = self._handler_previo
        except (AttributeError, RuntimeError):
            return False
        self._instalado = False
        return True

    def _pagina(self, e=None):
        try:
            return self._obtener_pagina(e)
        except TypeError:
            return self._obtener_pagina()
        except (AttributeError, RuntimeError):
            return None

    # ── Manejo del evento ───────────────────────────────────────────────────
    async def manejar(self, e=None):
        """`page.on_keyboard_event`. Siempre cede el evento al handler previo,
        incluso cuando esta vista ya lo consumió: otra parte de la aplicación
        puede tener un atajo legítimo sobre la misma tecla."""
        intencion = interpretar_evento(
            e,
            hay_campo_con_foco=self.foco.hay_campo_con_foco,
            hay_seleccion=self.hay_seleccion,
        )
        try:
            await self._aplicar(intencion, e)
        finally:
            await self._ceder(e)

    @property
    def hay_seleccion(self) -> bool:
        seleccion = self._seleccion
        if seleccion is None:
            return False
        try:
            return bool(seleccion.hay_seleccion)
        except AttributeError:
            return False

    async def _aplicar(self, intencion, e=None) -> None:
        if intencion is None:
            return
        if isinstance(intencion, IntencionScroll):
            await self._desplazar(intencion)
        elif isinstance(intencion, IntencionAccion):
            if self._ejecutar_accion is not None:
                self._ejecutar_accion(intencion.accion, e)
        elif isinstance(intencion, IntencionSimple):
            # Escape: suelta el foco además de limpiar la selección, para que
            # las flechas vuelvan a navegar sin tener que buscar un hueco de
            # la pantalla donde hacer clic.
            self.foco.limpiar()
            if self._al_limpiar is not None:
                self._al_limpiar(e)

    async def _desplazar(self, intencion: IntencionScroll) -> None:
        obtener = (
            self._destino_vertical if intencion.eje == "vertical"
            else self._destino_horizontal
        )
        if obtener is None:
            return
        destino = obtener() if callable(obtener) else obtener
        if destino is None:
            return
        try:
            await destino.scroll_to(duration=200, **desplazamiento(intencion))
        except Exception:
            # Un destino sin scroll habilitado, o desmontado entre el repintado
            # y la pulsación, no debe tumbar el teclado de la aplicación.
            pass

    async def _ceder(self, e=None) -> None:
        previo = self._handler_previo
        if previo is None or previo is self._handler:
            return
        try:
            resultado = previo(e)
            if hasattr(resultado, "__await__"):
                await resultado
        except Exception:
            pass
