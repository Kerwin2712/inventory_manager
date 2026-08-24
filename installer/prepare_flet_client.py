"""Empaqueta el cliente de escritorio de Flet (el ejecutable Flutter nativo
que renderiza la ventana) como `installer/vendor/flet-windows.zip`, para que
PyInstaller lo incluya dentro del build y la app NO necesite descargarlo de
internet la primera vez que se ejecuta en la máquina del cliente.

`flet_desktop.ensure_client_cached()` (ver env/Lib/site-packages/flet_desktop/
__init__.py) busca, en este orden: (1) el caché de usuario `~/.flet/client/...`,
(2) un archivo `flet-windows.zip` embebido en `flet_desktop/app/` dentro del
propio paquete — este script prepara exactamente ese archivo — y solo si
ninguno existe, (3) lo descarga desde GitHub Releases.

Uso:
    env/Scripts/python.exe installer/prepare_flet_client.py

Requiere que el cliente ya se haya usado al menos una vez en esta máquina
(queda cacheado en `~/.flet/client/flet-desktop-full-<version>/`) tras
ejecutar la app en modo escritorio (`python main.py`); si no se encuentra
ningún caché local, se descarga el artefacto oficial desde GitHub Releases
para la versión de `flet_desktop` instalada en el entorno virtual.
"""
import os
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

import flet_desktop.version  # noqa: E402

VENDOR_DIR = Path(__file__).parent / "vendor"
ARTIFACT_NAME = "flet-windows.zip"


def _cache_dir_candidatos(version: str) -> list[Path]:
    base = Path.home() / ".flet" / "client"
    return [base / f"flet-desktop-full-{version}", base / f"flet-desktop-light-{version}"]


def _zip_desde_cache(cache_dir: Path, destino: Path) -> None:
    """Re-comprime el contenido ya extraído en `~/.flet/client/...` con la
    misma estructura interna que trae el .zip oficial (una carpeta raíz
    `flet/` con los binarios), para que `ensure_client_cached()` la
    extraiga igual que si viniera de GitHub Releases."""
    carpeta_flet = cache_dir / "flet"
    if not carpeta_flet.is_dir():
        raise FileNotFoundError(f"No se encontró la carpeta 'flet' dentro de {cache_dir}")

    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as zf:
        for archivo in carpeta_flet.rglob("*"):
            if archivo.is_file():
                zf.write(archivo, arcname=str(Path("flet") / archivo.relative_to(carpeta_flet)))


def _descargar_de_github(version: str, destino: Path) -> None:
    url = f"https://github.com/flet-dev/flet/releases/download/v{version}/{ARTIFACT_NAME}"
    print(f"No se encontró caché local. Descargando desde: {url}")
    tmp = Path(tempfile.mktemp(suffix=".zip"))
    urllib.request.urlretrieve(url, tmp)
    shutil.move(str(tmp), destino)


def main():
    version = flet_desktop.version.version
    VENDOR_DIR.mkdir(parents=True, exist_ok=True)
    destino = VENDOR_DIR / ARTIFACT_NAME

    for cache_dir in _cache_dir_candidatos(version):
        if cache_dir.exists():
            print(f"Usando caché local: {cache_dir}")
            _zip_desde_cache(cache_dir, destino)
            break
    else:
        _descargar_de_github(version, destino)

    size_mb = destino.stat().st_size / (1024 * 1024)
    print(f"Listo: {destino} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
