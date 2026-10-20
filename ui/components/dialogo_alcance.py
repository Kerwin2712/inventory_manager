"""Diálogos para decidir SOBRE QUÉ ítems actúa una acción.

Con varios ítems marcados, una acción deja de tener un destinatario evidente, y
hay dos preguntas distintas que hacerle al usuario:

1. **¿Este o todos?** (`DialogoAlcance`) — Pulsó el ícono de una fila concreta
   teniendo varias marcadas. Puede querer actuar solo sobre esa, o sobre todo
   el lote. Adivinar es inaceptable en las dos direcciones: aplicar a todo lo
   que creía ser uno borra de más, y aplicar a uno lo que creía ser todo deja
   trabajo a medias sin avisar.
2. **¿Cuál de todos?** (`DialogoElegirItem`) — La acción no tiene sentido en
   lote (ver el detalle de cinco productos a la vez, o editarlos juntos), así
   que hay que elegir uno. Se muestra la lista de lo marcado en vez de pedirle
   al usuario que vuelva atrás y desmarque.

Las acciones que SÍ tienen sentido en lote (añadir al carrito, procesar venta,
borrar) no usan `DialogoElegirItem`: se aplican a todo lo marcado.

Los dos componentes siguen el patrón de `dialogo_clave`: no saben de la vista
ni de los servicios, reciben callables y paleta, y viajan pegados a su
`AlertDialog` en `data` para que la vista y las pruebas puedan alcanzarlos.
"""
import flet as ft

# Las dos respuestas posibles de `DialogoAlcance`.
ALCANCE_UNO = "uno"
ALCANCE_TODOS = "todos"


class DialogoAlcance:
    """Pregunta si la acción va sobre un ítem o sobre todos los marcados.

    Parámetros:
      - `titulo` / `accion`: qué se va a hacer, en palabras del usuario
        ("Añadir al carrito"), para que la pregunta no sea abstracta.
      - `codigo`: el ítem sobre cuyo ícono se hizo clic.
      - `marcados`: la lista completa de códigos marcados. Debe incluir a
        `codigo`; si hay uno solo, este diálogo no hace falta y quien llama no
        debería construirlo (`hace_falta_preguntar` lo resuelve).
      - `on_elegir`: callable `(alcance, e)` con `ALCANCE_UNO` o
        `ALCANCE_TODOS`.
      - `on_cerrar`: callable `(e)` que saca el diálogo de la pila, igual que
        en `DialogoClave`: cerrar es responsabilidad de quien apiló.
    """

    def __init__(
        self,
        titulo: str,
        accion: str,
        codigo: str,
        marcados,
        on_elegir,
        on_cerrar=None,
        paleta: dict | None = None,
        icono=ft.Icons.HELP_OUTLINE_ROUNDED,
    ):
        p = paleta or {}
        texto = p.get("texto", ft.Colors.BLACK)
        subtexto = p.get("subtexto", ft.Colors.GREY_600)
        acento = p.get("acento", ft.Colors.BLUE_600)
        fondo = p.get("fondo")

        self.codigo = codigo
        self.marcados = list(marcados)
        self._on_elegir = on_elegir
        self._on_cerrar = on_cerrar

        cantidad = len(self.marcados)
        # Se nombran unos pocos códigos para que el usuario reconozca el lote
        # sin convertir el diálogo en una lista interminable.
        muestra = ", ".join(self.marcados[:6])
        if cantidad > 6:
            muestra += f" y {cantidad - 6} más"

        self.boton_uno = ft.Button(
            content=ft.Column([
                ft.Text("Solo este ítem", size=13, weight=ft.FontWeight.BOLD),
                ft.Text(codigo, size=11),
            ], spacing=2, tight=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=12)),
            on_click=self.elegir_uno,
        )
        self.boton_todos = ft.Button(
            content=ft.Column([
                ft.Text(f"Los {cantidad} marcados", size=13, weight=ft.FontWeight.BOLD),
                ft.Text("Todo el lote", size=11),
            ], spacing=2, tight=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            style=ft.ButtonStyle(
                bgcolor=acento, color=ft.Colors.WHITE,
                shape=ft.RoundedRectangleBorder(radius=12),
            ),
            on_click=self.elegir_todos,
        )
        self.boton_cancelar = ft.TextButton("Cancelar", on_click=self.cancelar)

        self.dialogo = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(icono, color=acento),
                ft.Text(titulo, color=texto),
            ], spacing=10),
            content=ft.Column([
                ft.Text(
                    f"Tiene {cantidad} ítems marcados. ¿Sobre cuáles quiere "
                    f"{accion.lower()}?",
                    color=texto, size=13, no_wrap=False,
                ),
                ft.Text(f"Marcados: {muestra}", color=subtexto, size=12, no_wrap=False),
                ft.Row(
                    [self.boton_uno, self.boton_todos],
                    spacing=10,
                    alignment=ft.MainAxisAlignment.CENTER,
                ),
            ], spacing=14, tight=True, width=420),
            actions=[self.boton_cancelar],
            bgcolor=fondo,
            data=self,
        )

    def elegir_uno(self, e=None):
        return self._responder(ALCANCE_UNO, e)

    def elegir_todos(self, e=None):
        return self._responder(ALCANCE_TODOS, e)

    def cancelar(self, e=None):
        """Cancelar no ejecuta nada: no es "solo este" por omisión."""
        if self._on_cerrar is not None:
            self._on_cerrar(e)

    def _responder(self, alcance: str, e=None):
        if self._on_cerrar is not None:
            self._on_cerrar(e)
        if self._on_elegir is not None:
            self._on_elegir(alcance, e)
        return alcance


class DialogoElegirItem:
    """Lista los ítems marcados para que el usuario elija UNO.

    Para las acciones que no tienen sentido en lote: ver el detalle de cinco
    productos a la vez no significa nada, y editarlos juntos tampoco.

    `etiquetas` permite mostrar algo más reconocible que el código (por
    ejemplo la descripción corta); si falta la de un código, se muestra el
    código, que siempre existe.
    """

    def __init__(
        self,
        titulo: str,
        accion: str,
        marcados,
        on_elegir,
        on_cerrar=None,
        etiquetas: dict | None = None,
        paleta: dict | None = None,
        icono=ft.Icons.RULE_ROUNDED,
    ):
        p = paleta or {}
        texto = p.get("texto", ft.Colors.BLACK)
        subtexto = p.get("subtexto", ft.Colors.GREY_600)
        acento = p.get("acento", ft.Colors.BLUE_600)
        fondo = p.get("fondo")

        self.marcados = list(marcados)
        self._on_elegir = on_elegir
        self._on_cerrar = on_cerrar
        etiquetas = etiquetas or {}

        self.opciones = [
            ft.ListTile(
                leading=ft.Icon(ft.Icons.CHEVRON_RIGHT_ROUNDED, color=acento),
                title=ft.Text(etiquetas.get(codigo) or codigo, color=texto, size=13),
                subtitle=ft.Text(codigo, color=subtexto, size=11),
                on_click=lambda e, c=codigo: self.elegir(c, e),
                data=codigo,
            )
            for codigo in self.marcados
        ]

        self.boton_cancelar = ft.TextButton("Cancelar", on_click=self.cancelar)

        self.dialogo = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(icono, color=acento),
                ft.Text(titulo, color=texto),
            ], spacing=10),
            content=ft.Column(
                [
                    ft.Text(
                        f"Tiene {len(self.marcados)} ítems marcados y "
                        f"{accion.lower()} se hace de a uno. Elija cuál:",
                        color=texto, size=13, no_wrap=False,
                    ),
                    ft.Column(
                        self.opciones,
                        spacing=0,
                        tight=True,
                        # Lote largo: el diálogo no puede crecer sin fin, así
                        # que la lista es la dueña de su propio eje vertical.
                        scroll=ft.ScrollMode.AUTO,
                        height=min(300, 56 * max(1, len(self.opciones))),
                    ),
                ],
                spacing=10, tight=True, width=420,
            ),
            actions=[self.boton_cancelar],
            bgcolor=fondo,
            data=self,
        )

    def elegir(self, codigo: str, e=None):
        if self._on_cerrar is not None:
            self._on_cerrar(e)
        if self._on_elegir is not None:
            self._on_elegir(codigo, e)
        return codigo

    def cancelar(self, e=None):
        if self._on_cerrar is not None:
            self._on_cerrar(e)


def hace_falta_preguntar(marcados) -> bool:
    """True solo si hay MÁS DE UNO marcado.

    Con cero o un ítem marcado la acción tiene un destinatario evidente y
    preguntar sería ruido: el diálogo solo aparece cuando la ambigüedad existe
    de verdad.
    """
    return len(list(marcados or [])) > 1
