# -*- mode: python ; coding: utf-8 -*-
"""Spec de PyInstaller para el build de escritorio de producción.

Uso (desde la raíz del repo, con el entorno virtual activado):
    env/Scripts/python.exe installer/prepare_flet_client.py   # una vez
    env/Scripts/pyinstaller.exe installer/inventory_manager.spec --noconfirm

Genera `installer/dist/SistemaInventario/` (build "onedir": un ejecutable
más una carpeta `_internal` con las dependencias) — Inno Setup empaqueta
esa carpeta completa (ver installer/setup.iss). Se usa onedir en vez de
onefile porque el cliente de escritorio de Flet (`flet_desktop`) necesita
extraer ~90 MB de binarios de Flutter en cada arranque si se empaqueta en
un único .exe comprimido; onedir evita ese costo de arranque repetido.
"""
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

# `SPECPATH` es una variable global que PyInstaller inyecta al ejecutar este
# archivo (no es un script normal, así que no tiene `__file__`).
INSTALLER_DIR = Path(SPECPATH)
REPO_ROOT = INSTALLER_DIR.parent

APP_NAME = "SistemaInventario"

datas = [
    (str(INSTALLER_DIR / "vendor" / "flet-windows.zip"), "flet_desktop/app"),
]
binaries = []
hiddenimports = []

# `flet`/`flet_desktop` cargan JSON de recursos (nombres de íconos) y
# binarios propios en tiempo de ejecución que el análisis estático de
# PyInstaller no detecta solo — se recolectan explícitamente.
for paquete in ("flet", "flet_desktop"):
    d, b, h = collect_all(paquete)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    [str(REPO_ROOT / "main.py")],
    pathex=[str(REPO_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(INSTALLER_DIR / "assets" / "icon.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)
