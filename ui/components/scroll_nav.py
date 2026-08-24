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
