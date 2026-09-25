"""Modal reutilizable con el resumen completo de un ítem del inventario.

La especificación de campos es DECLARATIVA (`CAMPOS_DETALLE`): agregar un campo
es añadir una tupla `(etiqueta, clave, solo_admin)`. Solo se renderizan las
claves presentes en el diccionario del producto, de modo que el mismo modal
sirve para una fila de la tabla (dict parcial) y para un producto recién leído
de la base.

Gating de costos: los campos marcados `solo_admin` (los COSTOS del negocio) se
omiten por completo si `es_admin` es falso, incluso si el diccionario los trae.
El componente no importa `permisos_service`: el rol ya viene resuelto en el
parámetro `es_admin`, lo que lo mantiene puro y testeable.

La paleta entra por parámetro (no hereda de `BaseView`) para poder usarlo desde
cualquier vista o desde un test.
"""
import flet as ft

# Marcador de campo sin valor: mismo lenguaje que el paso 3 del formulario.
MARCADOR_VACIO = "— no llenado —"

# (etiqueta visible, clave del diccionario, solo para administradores)
CAMPOS_DETALLE: tuple[tuple[str, str, bool], ...] = (
    ("Código", "codigo", False),
    ("Referencia", "referencia", False),
    ("Descripción General", "descripcion_general", False),
    ("Nombre Corto", "nombre_referencia_corto", False),
    ("Código de Barras", "codigo_barras", False),
    ("Departamento", "departamento", False),
    ("Sub-Departamento", "sub_departamento", False),
    ("Marca", "marca", False),
    ("Existencia", "existencia", False),
    ("Alerta de Stock Mínimo", "alerta_stock_minimo", False),
    ("Precio USD (Efectivo)", "precio_dolares", False),
    ("Precio USD (BCV)", "precio_bcv", False),
    ("Monto Bs (BCV)", "monto_bcv_bolivares", False),
    ("Costo USD (Efectivo)", "costo_usd_efectivo", True),
    ("Costo USD (BCV)", "costo_usd_bcv", True),
    ("Proveedor ID", "proveedor_id", False),
    ("Fecha de Ingreso", "created_at", False),
    ("Última Modificación", "fecha_ultima_modificacion", False),
)

# Claves con formato monetario/numérico propio.
_CLAVES_USD = (
    "precio_dolares", "precio_bcv", "costo_usd_efectivo", "costo_usd_bcv",
)
_CLAVES_BOLIVARES = ("monto_bcv_bolivares",)

PALETA_POR_DEFECTO = {
    "texto": ft.Colors.WHITE,
    "subtexto": ft.Colors.GREY_400,
    "acento": "#2196F3",
    "fondo": "#1E293B",
    "borde": ft.Colors.GREY_800,
}


def _formatear(clave: str, valor) -> str:
    """Texto a mostrar para un valor, o `MARCADOR_VACIO` si no hay dato.

    Un `0` numérico SÍ es un dato (una existencia en cero es información
    válida): solo `None` y las cadenas en blanco cuentan como no llenado.
    """
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        return MARCADOR_VACIO
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        if clave in _CLAVES_USD:
            return f"$ {valor:,.2f}"
        if clave in _CLAVES_BOLIVARES:
            return f"Bs {valor:,.2f}"
        if clave == "existencia":
            return f"{valor:,.2f}".rstrip("0").rstrip(".")
    return str(valor).strip()


def campos_visibles(producto: dict, es_admin: bool = False) -> list[tuple[str, str]]:
    """Pares `(etiqueta, clave)` que corresponde renderizar: los presentes en
    el diccionario, descartando los de costo cuando el rol no es admin."""
    datos = producto or {}
    return [
        (etiqueta, clave)
        for etiqueta, clave, solo_admin in CAMPOS_DETALLE
        if clave in datos and (es_admin or not solo_admin)
    ]


def construir_modal_detalle_producto(
    producto: dict,
    *,
    es_admin: bool = False,
    paleta: dict | None = None,
    on_cerrar=None,
    on_editar=None,
) -> ft.AlertDialog:
    """`ft.AlertDialog` con el resumen del ítem.

    - `es_admin`: habilita los campos de costo (fail-closed: por defecto no).
    - `paleta`: dict con las claves `texto`, `subtexto`, `acento`, `fondo` y
      `borde`; las ausentes caen en `PALETA_POR_DEFECTO`.
    - `on_cerrar` / `on_editar`: manejadores de los botones. Sin `on_editar` el
      botón de editar no se dibuja.
    """
    datos = producto or {}
    p = {**PALETA_POR_DEFECTO, **(paleta or {})}

    filas = []
    for etiqueta, clave in campos_visibles(datos, es_admin):
        mostrar = _formatear(clave, datos.get(clave))
        vacio = mostrar == MARCADOR_VACIO
        filas.append(
            ft.Row(
                controls=[
                    ft.Text(f"{etiqueta}:", width=200, color=p["subtexto"], size=13),
                    # Todo valor largo (descripción, nombre corto, referencia)
                    # vive en un contenedor de ancho acotado y envuelve con
                    # elipsis: nunca desborda hacia la derecha del diálogo.
                    ft.Container(
                        content=ft.Text(
                            mostrar,
                            color=p["subtexto"] if vacio else p["texto"],
                            size=13,
                            weight=ft.FontWeight.W_400 if vacio else ft.FontWeight.W_600,
                            no_wrap=False, max_lines=4,
                            overflow=ft.TextOverflow.ELLIPSIS,
                            selectable=True,
                        ),
                        expand=True,
                    ),
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.START,
            )
        )

    if not filas:
        filas.append(ft.Text("Sin datos para mostrar.", color=p["subtexto"], size=13))

    titulo = _formatear("descripcion_general", datos.get("descripcion_general"))
    codigo = _formatear("codigo", datos.get("codigo"))

    acciones = []
    if callable(on_editar):
        acciones.append(
            ft.OutlinedButton(
                "Editar", icon=ft.Icons.EDIT_OUTLINED,
                style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=12)),
                on_click=on_editar,
            )
        )
    acciones.append(
        ft.Button(
            "Cerrar",
            style=ft.ButtonStyle(
                bgcolor=p["acento"], color=ft.Colors.WHITE,
                shape=ft.RoundedRectangleBorder(radius=12),
            ),
            on_click=on_cerrar,
        )
    )

    return ft.AlertDialog(
        modal=True,
        title=ft.Row(
            controls=[
                ft.Icon(ft.Icons.INFO_OUTLINE_ROUNDED, color=p["acento"]),
                ft.Container(
                    content=ft.Text(
                        f"{codigo} — {titulo}",
                        color=p["texto"], size=15, weight=ft.FontWeight.BOLD,
                        no_wrap=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                    expand=True,
                ),
            ],
            spacing=10,
        ),
        content=ft.Container(
            # Un ÚNICO scroll vertical (el de esta Column) sobre un alto
            # acotado: sin scrolls anidados que compitan por el gesto.
            content=ft.Column(controls=filas, spacing=6, scroll=ft.ScrollMode.AUTO),
            width=620,
            height=400,
            padding=10,
        ),
        actions=acciones,
        actions_alignment=ft.MainAxisAlignment.END,
        bgcolor=p["fondo"],
    )
