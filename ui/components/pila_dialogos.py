"""Sincronización de la pila de diálogos propia de cada vista con la de Flet.

Cada vista que encadena modales lleva su propia lista (`_dialog_stack`) para
saber cuál es el tope y poder cerrarlos en orden. Esa lista se mantiene sola
mientras los diálogos se abran y se cierren por los botones de la vista.

El problema es que **Flet también los cierra por su cuenta**: un `AlertDialog`
que no es `modal=True` se descarta tocando fuera de él, y ahí la vista nunca se
entera. Su lista queda con un fantasma: una entrada de un diálogo que ya no
está en pantalla. A partir de ese momento el tope que la vista cree tener no es
el que Flet tiene, y el siguiente cierre descarta el diálogo equivocado — el
usuario pulsa Cancelar, no se cierra nada visible, y la pantalla parece
colgada. Es exactamente el defecto que se corrigió en septiembre, por otro
camino.

`sincronizar_al_descartar` cierra ese hueco: engancha `on_dismiss` para que,
cuando Flet descarte el diálogo, la lista de la vista se entere.
"""


def sincronizar_al_descartar(dialog, pila: list) -> None:
    """Hace que `dialog` se saque de `pila` cuando Flet lo descarte solo.

    Se conserva el `on_dismiss` que el diálogo ya tuviera: la sincronización
    es un añadido, no un reemplazo de lo que la vista quisiera hacer ahí.

    NO se llama a `pop_dialog()`: para cuando este handler corre, Flet ya
    cerró el diálogo. Llamarlo otra vez cerraría el que haya quedado debajo,
    que es justo el error que este módulo existe para evitar.
    """
    previo = getattr(dialog, "on_dismiss", None)

    def al_descartar(e=None, _dialog=dialog, _previo=previo):
        if _dialog in pila:
            pila.remove(_dialog)
        _dialog.open = False
        if _previo is not None and _previo is not al_descartar:
            _previo(e)

    dialog.on_dismiss = al_descartar
