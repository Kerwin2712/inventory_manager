"""Controles de filtro compactos con buscador para vistas de listado.

`MultiSelectFilter` y `RangeFilter` se muestran como un botón pequeño (pill)
que resume el estado del filtro y, al pulsarlo, abre un diálogo modal con el
detalle de selección — así el panel de filtros ocupa poco espacio en pantalla
sin sacrificar potencia de búsqueda. Reutilizan los helpers de diálogo
(`_open_dialog`, `_close_dialog`, `_safe_update`) ya presentes en las vistas
que heredan de `BaseView`.
"""
import flet as ft


class MultiSelectFilter:
    """Filtro de selección múltiple con buscador en vivo.

    `options_provider` es un callable sin argumentos que devuelve
    `list[dict]` con claves `value` (identificador único), `label` (texto
    visible) y `total` (popularidad, usada para ordenar las opciones cuando
    el buscador está vacío — las más usadas aparecen primero).
    """

    def __init__(self, view, label: str, icon, options_provider, on_apply):
        self.view = view
        self.label = label
        self.icon = icon
        self.options_provider = options_provider
        self.on_apply = on_apply
        self.selected: set[str] = set()
        self.trigger = ft.OutlinedButton(
            content=self._trigger_content(),
            style=self._trigger_style(),
            on_click=self._abrir,
        )

    def control(self) -> ft.Control:
        return self.trigger

    def reset(self) -> None:
        self.selected = set()
        self.trigger.content = self._trigger_content()

    def _trigger_style(self) -> ft.ButtonStyle:
        return ft.ButtonStyle(
            shape=ft.RoundedRectangleBorder(radius=10),
            side=ft.BorderSide(1, self.view.get_border_color()),
            padding=10,
        )

    def _trigger_content(self) -> ft.Control:
        text_color = self.view.get_text_color()
        n = len(self.selected)
        texto = self.label if n == 0 else f"{self.label} ({n})"
        color = self.view.get_accent_color() if n else text_color
        return ft.Row(
            controls=[ft.Icon(self.icon, size=15, color=color), ft.Text(texto, size=12, color=color)],
            spacing=6, tight=True,
        )

    def _abrir(self, e):
        accent = self.view.get_accent_color()
        text_color = self.view.get_text_color()
        subtext = self.view.get_subtext_color()
        card_bg = self.view.get_card_bg()
        border = self.view.get_border_color()

        seleccion_temp: set[str] = set(self.selected)
        opciones_col = ft.Column(spacing=0, scroll=ft.ScrollMode.AUTO, height=280)

        search = ft.TextField(
            label="Buscar...", autofocus=True, border_radius=10, dense=True,
            color=text_color, border_color=border, focused_border_color=accent,
        )

        def _renderizar(texto_filtro: str = "") -> None:
            opciones = list(self.options_provider())
            texto_filtro = (texto_filtro or "").strip().lower()
            if texto_filtro:
                opciones = [o for o in opciones if texto_filtro in o["label"].lower()]
                opciones.sort(key=lambda o: (o["label"].lower().find(texto_filtro), -o["total"], o["label"].lower()))
            else:
                # Sin texto escrito: las opciones más usadas primero.
                opciones.sort(key=lambda o: (-o["total"], o["label"].lower()))

            filas = []
            for op in opciones:
                valor = op["value"]
                cb = ft.Checkbox(
                    label=f"{op['label']}  ·  {op['total']}",
                    value=valor in seleccion_temp,
                    label_style=ft.TextStyle(color=text_color, size=13),
                )

                def _toggle(ev, v=valor, box=cb):
                    if box.value:
                        seleccion_temp.add(v)
                    else:
                        seleccion_temp.discard(v)

                cb.on_change = _toggle
                filas.append(cb)

            if not filas:
                filas = [ft.Container(
                    content=ft.Text("Sin coincidencias.", size=12, color=subtext),
                    padding=10,
                )]
            opciones_col.controls = filas
            self.view._safe_update(e)

        search.on_change = lambda ev: _renderizar(search.value)
        _renderizar()

        def _limpiar(ev):
            seleccion_temp.clear()
            _renderizar(search.value)

        def _aplicar(ev):
            self.selected = set(seleccion_temp)
            self.trigger.content = self._trigger_content()
            self.view._close_dialog(ev)
            self.on_apply(sorted(self.selected))

        def _cancelar(ev):
            self.view._close_dialog(ev)

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row(
                [ft.Icon(self.icon, color=accent), ft.Text(self.label, color=text_color, weight=ft.FontWeight.BOLD)],
                spacing=8,
            ),
            content=ft.Container(content=ft.Column([search, opciones_col], spacing=10, tight=True), width=320),
            actions=[
                ft.TextButton("Limpiar", on_click=_limpiar),
                ft.TextButton("Cancelar", on_click=_cancelar),
                ft.Button(
                    "Aplicar",
                    style=ft.ButtonStyle(bgcolor=accent, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=10)),
                    on_click=_aplicar,
                ),
            ],
            bgcolor=card_bg,
        )
        self.view._open_dialog(dlg, e)


class RangeFilter:
    """Filtro de rango (mín./máx. o desde/hasta para fechas) en un diálogo
    compacto, activado por un botón pill que resume el rango aplicado."""

    def __init__(self, view, label: str, icon, on_apply, is_date: bool = False, unidad: str = ""):
        self.view = view
        self.label = label
        self.icon = icon
        self.on_apply = on_apply
        self.is_date = is_date
        self.unidad = unidad
        self.vmin = ""
        self.vmax = ""
        self.trigger = ft.OutlinedButton(
            content=self._trigger_content(),
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=10),
                side=ft.BorderSide(1, self.view.get_border_color()),
                padding=10,
            ),
            on_click=self._abrir,
        )

    def control(self) -> ft.Control:
        return self.trigger

    def reset(self) -> None:
        self.vmin = ""
        self.vmax = ""
        self.trigger.content = self._trigger_content()

    def _trigger_content(self) -> ft.Control:
        text_color = self.view.get_text_color()
        activo = bool(self.vmin or self.vmax)
        color = self.view.get_accent_color() if activo else text_color
        if not activo:
            texto = self.label
        elif self.vmin and self.vmax:
            texto = f"{self.label}: {self.vmin}{self.unidad}–{self.vmax}{self.unidad}"
        elif self.vmin:
            texto = f"{self.label}: ≥{self.vmin}{self.unidad}"
        else:
            texto = f"{self.label}: ≤{self.vmax}{self.unidad}"
        return ft.Row(
            controls=[ft.Icon(self.icon, size=15, color=color), ft.Text(texto, size=12, color=color)],
            spacing=6, tight=True,
        )

    def _abrir(self, e):
        accent = self.view.get_accent_color()
        text_color = self.view.get_text_color()
        card_bg = self.view.get_card_bg()
        border = self.view.get_border_color()

        etiqueta_min = "Desde (AAAA-MM-DD)" if self.is_date else "Mínimo"
        etiqueta_max = "Hasta (AAAA-MM-DD)" if self.is_date else "Máximo"

        f_min = ft.TextField(
            label=etiqueta_min, value=self.vmin, width=260, border_radius=10,
            color=text_color, border_color=border, focused_border_color=accent,
            keyboard_type=ft.KeyboardType.TEXT if self.is_date else ft.KeyboardType.NUMBER,
            hint_text="Ej: 2026-08-01" if self.is_date else "",
        )
        f_max = ft.TextField(
            label=etiqueta_max, value=self.vmax, width=260, border_radius=10,
            color=text_color, border_color=border, focused_border_color=accent,
            keyboard_type=ft.KeyboardType.TEXT if self.is_date else ft.KeyboardType.NUMBER,
            hint_text="Ej: 2026-08-24" if self.is_date else "",
        )

        def _aplicar(ev):
            self.vmin = (f_min.value or "").strip()
            self.vmax = (f_max.value or "").strip()
            self.trigger.content = self._trigger_content()
            self.view._close_dialog(ev)
            self.on_apply(self.vmin, self.vmax)

        def _limpiar(ev):
            f_min.value = ""
            f_max.value = ""
            self.view._safe_update(ev)

        def _cancelar(ev):
            self.view._close_dialog(ev)

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row(
                [ft.Icon(self.icon, color=accent), ft.Text(self.label, color=text_color, weight=ft.FontWeight.BOLD)],
                spacing=8,
            ),
            content=ft.Container(content=ft.Column([f_min, f_max], spacing=14, tight=True), width=280),
            actions=[
                ft.TextButton("Limpiar", on_click=_limpiar),
                ft.TextButton("Cancelar", on_click=_cancelar),
                ft.Button(
                    "Aplicar",
                    style=ft.ButtonStyle(bgcolor=accent, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=10)),
                    on_click=_aplicar,
                ),
            ],
            bgcolor=card_bg,
        )
        self.view._open_dialog(dlg, e)
