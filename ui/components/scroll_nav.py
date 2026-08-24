"""Botones de navegación rápida para listas/tablas con scroll.

Flet permite desplazar un `Column`/`Row`/`ListView` con scroll habilitado
mediante `.scroll_to(delta=..., duration=...)`. Este helper arma una fila
compacta de botones (extremo, paso, extremo) para moverse rápidamente sin
depender de la rueda del mouse o de arrastrar barras de scroll finas —
particularmente útil en tablas anchas (Inventario, Carrito de Ventas) y en
listas largas de resultados dentro de diálogos modales.
"""
import flet as ft

_PASO_GRANDE = 999999  # clamma al límite real del scroll (Flutter lo acota).


def build_scroll_nav(target: ft.Control, axis: str, accent, step: float = 260, tooltip_prefix: str = "") -> ft.Row:
    """`target` debe ser un control con scroll habilitado (`ft.Column`,
    `ft.Row` o `ft.ListView` con `scroll=ft.ScrollMode.AUTO`). `axis` es
    `"horizontal"` (Izquierda/Derecha) o `"vertical"` (Arriba/Abajo)."""
    if axis == "horizontal":
        botones = [
            (ft.Icons.FIRST_PAGE_ROUNDED, "Ir al inicio", -_PASO_GRANDE),
            (ft.Icons.CHEVRON_LEFT_ROUNDED, "Desplazar a la izquierda", -step),
            (ft.Icons.CHEVRON_RIGHT_ROUNDED, "Desplazar a la derecha", step),
            (ft.Icons.LAST_PAGE_ROUNDED, "Ir al final", _PASO_GRANDE),
        ]
    else:
        botones = [
            (ft.Icons.VERTICAL_ALIGN_TOP_ROUNDED, "Ir arriba del todo", -_PASO_GRANDE),
            (ft.Icons.KEYBOARD_ARROW_UP_ROUNDED, "Subir", -step),
            (ft.Icons.KEYBOARD_ARROW_DOWN_ROUNDED, "Bajar", step),
            (ft.Icons.VERTICAL_ALIGN_BOTTOM_ROUNDED, "Ir abajo del todo", _PASO_GRANDE),
        ]

    def _mover(delta):
        def handler(e):
            target.scroll_to(delta=delta, duration=200)
        return handler

    return ft.Row(
        controls=[
            ft.IconButton(
                icon=icon, icon_size=16, icon_color=accent,
                tooltip=f"{tooltip_prefix}{tip}",
                style=ft.ButtonStyle(padding=4),
                on_click=_mover(delta),
            )
            for icon, tip, delta in botones
        ],
        spacing=0, tight=True,
    )


def build_floating_nav(
    h_target: ft.Control, v_target: ft.Control, accent,
    right: float = 10, bottom: float = 10,
) -> ft.Container:
    """Cruceta de 4 flechas flotantes, ancladas a una esquina fija dentro de
    un `ft.Stack` (posición `right`/`bottom`) — a diferencia de
    `build_scroll_nav`, esta no vive junto al contenido que se desplaza, así
    que sigue al alcance de un clic sin importar hasta dónde se haya
    scrolleado la tabla. Pensada para tablas anchas y largas (Inventario):
    izquierda/derecha saltan al inicio/final de la fila (Código ↔ Acciones),
    arriba/abajo saltan al primer/último ítem de la página actual.
    """
    _SALTO = 999999  # el scroll real lo acota a su límite disponible.

    def _mover(target, delta):
        def handler(e):
            target.scroll_to(delta=delta, duration=250)
        return handler

    def _flecha(icon, tooltip, handler):
        return ft.IconButton(
            icon=icon, icon_size=20, icon_color=ft.Colors.WHITE,
            tooltip=tooltip, on_click=handler,
            style=ft.ButtonStyle(
                bgcolor={ft.ControlState.DEFAULT: accent, ft.ControlState.HOVERED: accent},
                shape=ft.CircleBorder(),
                padding=8,
                elevation={ft.ControlState.DEFAULT: 3},
            ),
        )

    def _espaciador():
        return ft.Container(width=36, height=36)

    cruceta = ft.Column(
        controls=[
            ft.Row(
                [_espaciador(), _flecha(ft.Icons.KEYBOARD_DOUBLE_ARROW_UP_ROUNDED, "Ir al primer ítem", _mover(v_target, -_SALTO)), _espaciador()],
                spacing=4, alignment=ft.MainAxisAlignment.CENTER,
            ),
            ft.Row(
                [
                    _flecha(ft.Icons.KEYBOARD_DOUBLE_ARROW_LEFT_ROUNDED, "Ir al Código (inicio de la fila)", _mover(h_target, -_SALTO)),
                    _flecha(ft.Icons.KEYBOARD_DOUBLE_ARROW_RIGHT_ROUNDED, "Ir a Acciones (final de la fila)", _mover(h_target, _SALTO)),
                ],
                spacing=4, alignment=ft.MainAxisAlignment.CENTER,
            ),
            ft.Row(
                [_espaciador(), _flecha(ft.Icons.KEYBOARD_DOUBLE_ARROW_DOWN_ROUNDED, "Ir al último ítem", _mover(v_target, _SALTO)), _espaciador()],
                spacing=4, alignment=ft.MainAxisAlignment.CENTER,
            ),
        ],
        spacing=4, tight=True,
    )

    return ft.Container(
        content=cruceta,
        bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK),
        border_radius=50,
        padding=6,
        right=right,
        bottom=bottom,
    )
