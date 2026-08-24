"""Genera el icono de la aplicación (icon.ico multi-resolución + PNGs sueltos)
a partir de formas vectoriales dibujadas con Pillow — no depende de ningún
archivo de arte externo, así que se puede regenerar o ajustar el diseño
editando este script y volviendo a ejecutarlo:

    env/Scripts/python.exe installer/assets/generate_icon.py

Diseño: una caja de inventario isométrica (semejante al ícono de Material
"Inventory2" ya usado en la UI) sobre una insignia cuadrada redondeada del
color de acento de la app (#2196F3), simple y reconocible incluso a 16x16.
Se dibuja a 1024x1024 y se reduce con remuestreo LANCZOS para bordes nítidos
en todos los tamaños del .ico.
"""
import math
from pathlib import Path
from PIL import Image, ImageDraw

OUT_DIR = Path(__file__).parent
CANVAS = 1024

ACCENT = (33, 150, 243, 255)       # #2196F3 (azul de acento de la app)
ACCENT_DARK = (13, 71, 161, 255)   # sombra/borde
BOX_TOP = (255, 255, 255, 255)     # cara superior de la caja
BOX_LEFT = (210, 227, 252, 255)    # cara izquierda (más clara)
BOX_RIGHT = (161, 196, 244, 255)   # cara derecha (intermedia)
SEAM = (120, 160, 224, 255)        # línea de cinta/costura


def _rounded_square_badge(draw: ImageDraw.ImageDraw, size: int, radius: int):
    draw.rounded_rectangle(
        (0, 0, size - 1, size - 1), radius=radius, fill=ACCENT,
    )


def _isometric_box(draw: ImageDraw.ImageDraw, cx: int, cy: int, half_w: int, top_h: int, side_h: int):
    """Caja isométrica de 3 caras: superior (rombo), izquierda y derecha."""
    top = [
        (cx, cy - top_h),
        (cx + half_w, cy - top_h // 2),
        (cx, cy),
        (cx - half_w, cy - top_h // 2),
    ]
    left = [
        (cx - half_w, cy - top_h // 2),
        (cx, cy),
        (cx, cy + side_h),
        (cx - half_w, cy + side_h - top_h // 2),
    ]
    right = [
        (cx + half_w, cy - top_h // 2),
        (cx, cy),
        (cx, cy + side_h),
        (cx + half_w, cy + side_h - top_h // 2),
    ]
    draw.polygon(right, fill=BOX_RIGHT, outline=ACCENT_DARK, width=6)
    draw.polygon(left, fill=BOX_LEFT, outline=ACCENT_DARK, width=6)
    draw.polygon(top, fill=BOX_TOP, outline=ACCENT_DARK, width=6)

    # Línea de cinta vertical sobre la cara superior (costura de la caja).
    draw.line([(cx, cy - top_h), (cx, cy)], fill=SEAM, width=8)


def build_master_image() -> Image.Image:
    img = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    _rounded_square_badge(draw, CANVAS, radius=int(CANVAS * 0.22))

    cx, cy = CANVAS // 2, int(CANVAS * 0.58)
    half_w = int(CANVAS * 0.30)
    top_h = int(CANVAS * 0.20)
    side_h = int(CANVAS * 0.26)
    _isometric_box(draw, cx, cy, half_w, top_h, side_h)

    return img


def main():
    master = build_master_image()

    # icon.ico: multi-resolución estándar de Windows (usada por PyInstaller
    # --icon y por el instalador de Inno Setup).
    ico_sizes = [16, 24, 32, 48, 64, 128, 256]
    frames = [master.resize((s, s), Image.LANCZOS) for s in ico_sizes]
    ico_path = OUT_DIR / "icon.ico"
    frames[0].save(ico_path, format="ICO", sizes=[(s, s) for s in ico_sizes])
    print(f"Generado: {ico_path}")

    # PNG de referencia en alta resolución (para el asistente de Inno Setup,
    # el README, o cualquier otro uso que requiera un PNG en vez de .ico).
    png_path = OUT_DIR / "icon_512.png"
    master.resize((512, 512), Image.LANCZOS).save(png_path, format="PNG")
    print(f"Generado: {png_path}")


if __name__ == "__main__":
    main()
