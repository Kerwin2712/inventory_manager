"""Botones de navegación rápida para listas/tablas con scroll.

Flet permite desplazar un `Column`/`Row`/`ListView` con scroll habilitado
mediante `.scroll_to(delta=..., duration=...)`. Este helper arma botones
compactos para moverse rápidamente sin depender de la rueda del mouse o de
arrastrar barras de scroll finas — particularmente útil en tablas anchas
(Inventario, Carrito de Ventas) y en listas largas de resultados dentro de
diálogos modales.

IMPORTANTE: `Control.scroll_to(...)` es un método `async def` en esta
versión de Flet (0.86.1) — un `on_click` normal (función sync) que lo llama
sin `await` solo crea una coroutine y la descarta sin ejecutarla nunca (no
lanza error, simplemente no pasa nada). Flet sí soporta manejadores de
evento `async def` de forma nativa (los detecta y los espera), así que
todos los botones de este módulo usan handlers asíncronos.
"""
import flet as ft

_PASO_GRANDE = 999999  # clamma al límite real del scroll (Flutter lo acota).


def _mover_async(target: ft.Control, delta: float, duration: int = 200):
    async def handler(e):
        await target.scroll_to(delta=delta, duration=duration)
    return handler


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

    return ft.Row(
        controls=[
            ft.IconButton(
                icon=icon, icon_size=16, icon_color=accent,
                tooltip=f"{tooltip_prefix}{tip}",
                style=ft.ButtonStyle(padding=4),
                on_click=_mover_async(target, delta),
            )
            for icon, tip, delta in botones
        ],
        spacing=0, tight=True,
    )


def _mini_flecha(icon, tooltip: str, accent, handler) -> ft.IconButton:
    """Botón circular pequeño y discreto (12px de ícono) para los clusters
    flotantes — deliberadamente chico para no tapar datos de la tabla."""
    return ft.IconButton(
        icon=icon, icon_size=12, icon_color=ft.Colors.WHITE,
        tooltip=tooltip, on_click=handler,
        style=ft.ButtonStyle(
            bgcolor={ft.ControlState.DEFAULT: ft.Colors.with_opacity(0.65, accent)},
            shape=ft.CircleBorder(),
            padding=2,
        ),
        width=24, height=24,
    )


def build_floating_corner_nav(
    h_target: ft.Control, v_target: ft.Control, accent,
    right: float = 6,
) -> list[ft.Container]:
    """Dos clusters flotantes pequeños, pensados para vivir como hijos
    adicionales dentro de un `ft.Stack` (posición `right`/`top`/`bottom`
    fija) — permanecen anclados a una esquina del viewport de la tabla
    (no de la página), siempre al alcance sin importar cuánto se haya
    scrolleado:

    - Esquina superior derecha: ← / → (saltan al Código / a Acciones,
      inicio y final de la fila).
    - Esquina inferior derecha: ↑ / ↓ (saltan al primer / último ítem).
    """
    horizontal = ft.Container(
        content=ft.Row(
            [
                _mini_flecha(ft.Icons.CHEVRON_LEFT_ROUNDED, "Ir al Código (inicio de la fila)", accent, _mover_async(h_target, -_PASO_GRANDE, 250)),
                _mini_flecha(ft.Icons.CHEVRON_RIGHT_ROUNDED, "Ir a Acciones (final de la fila)", accent, _mover_async(h_target, _PASO_GRANDE, 250)),
            ],
            spacing=3, tight=True,
        ),
        padding=2, border_radius=16,
        right=right, top=4,
    )

    vertical = ft.Container(
        content=ft.Row(
            [
                _mini_flecha(ft.Icons.KEYBOARD_ARROW_UP_ROUNDED, "Ir al primer ítem", accent, _mover_async(v_target, -_PASO_GRANDE, 250)),
                _mini_flecha(ft.Icons.KEYBOARD_ARROW_DOWN_ROUNDED, "Ir al último ítem", accent, _mover_async(v_target, _PASO_GRANDE, 250)),
            ],
            spacing=3, tight=True,
        ),
        padding=2, border_radius=16,
        right=right, bottom=4,
    )

    return [horizontal, vertical]
