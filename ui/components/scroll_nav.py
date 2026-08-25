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


def _mover_async(target: ft.Control, offset: float | None = None, delta: float | None = None, duration: int = 200):
    async def handler(e):
        try:
            if offset is not None:
                await target.scroll_to(offset=offset, duration=duration)
            elif delta is not None:
                await target.scroll_to(delta=delta, duration=duration)
        except Exception:
            pass
    return handler


def build_scroll_nav(target: ft.Control, axis: str, accent, step: float = 260, tooltip_prefix: str = "") -> ft.Row:
    """`target` debe ser un control con scroll habilitado (`ft.Column`,
    `ft.Row` o `ft.ListView` con `scroll=ft.ScrollMode.AUTO`). `axis` es
    `"horizontal"` (Izquierda/Derecha) o `"vertical"` (Arriba/Abajo)."""
    if axis == "horizontal":
        botones = [
            (ft.Icons.FIRST_PAGE_ROUNDED, "Ir al inicio", 0.0, None),
            (ft.Icons.CHEVRON_LEFT_ROUNDED, "Desplazar a la izquierda", None, -step),
            (ft.Icons.CHEVRON_RIGHT_ROUNDED, "Desplazar a la derecha", None, step),
            (ft.Icons.LAST_PAGE_ROUNDED, "Ir al final", None, 99999.0),
        ]
    else:
        botones = [
            (ft.Icons.VERTICAL_ALIGN_TOP_ROUNDED, "Ir arriba del todo", 0.0, None),
            (ft.Icons.KEYBOARD_ARROW_UP_ROUNDED, "Subir", None, -step),
            (ft.Icons.KEYBOARD_ARROW_DOWN_ROUNDED, "Bajar", None, step),
            (ft.Icons.VERTICAL_ALIGN_BOTTOM_ROUNDED, "Ir abajo del todo", None, 99999.0),
        ]

    return ft.Row(
        controls=[
            ft.IconButton(
                icon=icon, icon_size=16, icon_color=accent,
                tooltip=f"{tooltip_prefix}{tip}",
                style=ft.ButtonStyle(padding=4),
                on_click=_mover_async(target, offset=offset, delta=delta),
            )
            for icon, tip, offset, delta in botones
        ],
        spacing=0, tight=True,
    )


def _mini_flecha(icon, tooltip: str, accent, handler) -> ft.IconButton:
    """Botón circular cómodo (14px de ícono) para los clusters flotantes."""
    return ft.IconButton(
        icon=icon, icon_size=14, icon_color=ft.Colors.WHITE,
        tooltip=tooltip, on_click=handler,
        style=ft.ButtonStyle(
            bgcolor={ft.ControlState.DEFAULT: ft.Colors.with_opacity(0.75, accent)},
            shape=ft.CircleBorder(),
            padding=2,
        ),
        width=28, height=28,
    )


def build_floating_corner_nav(
    h_target: ft.Control, v_target: ft.Control, accent,
    right: float = 6,
) -> list[ft.Container]:
    """Dos clusters flotantes discretos, pensados para vivir como hijos
    adicionales dentro de un `ft.Stack` (posición `right`/`top`/`bottom`
    fija) — permanecen anclados a la esquina del viewport de la tabla:

    - Esquina superior derecha: ← / → (desplazamiento horizontal paso a paso y saltos a extremos).
    - Esquina inferior derecha: ↑ / ↓ (desplazamiento vertical paso a paso y saltos a extremos).
    """
    horizontal = ft.Container(
        content=ft.Row(
            [
                _mini_flecha(ft.Icons.FIRST_PAGE_ROUNDED, "Ir al Código (inicio)", accent, _mover_async(h_target, offset=0.0, duration=250)),
                _mini_flecha(ft.Icons.CHEVRON_LEFT_ROUNDED, "Desplazar a la izquierda", accent, _mover_async(h_target, delta=-280.0, duration=250)),
                _mini_flecha(ft.Icons.CHEVRON_RIGHT_ROUNDED, "Desplazar a la derecha", accent, _mover_async(h_target, delta=280.0, duration=250)),
                _mini_flecha(ft.Icons.LAST_PAGE_ROUNDED, "Ir a Acciones (final)", accent, _mover_async(h_target, delta=99999.0, duration=250)),
            ],
            spacing=3, tight=True,
        ),
        padding=3, border_radius=16,
        bgcolor=ft.Colors.with_opacity(0.2, accent),
        right=right, top=4,
    )

    vertical = ft.Container(
        content=ft.Row(
            [
                _mini_flecha(ft.Icons.VERTICAL_ALIGN_TOP_ROUNDED, "Ir al primer ítem", accent, _mover_async(v_target, offset=0.0, duration=250)),
                _mini_flecha(ft.Icons.KEYBOARD_ARROW_UP_ROUNDED, "Subir", accent, _mover_async(v_target, delta=-200.0, duration=250)),
                _mini_flecha(ft.Icons.KEYBOARD_ARROW_DOWN_ROUNDED, "Bajar", accent, _mover_async(v_target, delta=200.0, duration=250)),
                _mini_flecha(ft.Icons.VERTICAL_ALIGN_BOTTOM_ROUNDED, "Ir al último ítem", accent, _mover_async(v_target, delta=99999.0, duration=250)),
            ],
            spacing=3, tight=True,
        ),
        padding=3, border_radius=16,
        bgcolor=ft.Colors.with_opacity(0.2, accent),
        right=right, bottom=4,
    )

    return [horizontal, vertical]
