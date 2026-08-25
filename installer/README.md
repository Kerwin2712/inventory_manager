# Build de escritorio e Instalador de Windows

Esta carpeta contiene todo lo necesario para empaquetar la aplicación en modo
**escritorio** (ventana nativa Flutter, `ft.run(main)` en [main.py](../main.py))
como un `.exe` autocontenido (PyInstaller) y distribuirlo como un instalador
de Windows con asistente gráfico (Inno Setup 6).

```
installer/
├── assets/
│   ├── generate_icon.py   # genera icon.ico + icon_512.png (sin arte externo)
│   ├── icon.ico           # ícono multi-resolución (16..256px)
│   └── icon_512.png       # PNG de referencia en alta resolución
├── prepare_flet_client.py # empaqueta el cliente de escritorio de Flet (offline)
├── inventory_manager.spec # spec de PyInstaller (build "onedir")
├── setup.iss              # script de Inno Setup
├── vendor/                # (generado, no versionado) flet-windows.zip
├── build/                 # (generado, no versionado) intermedios de PyInstaller
├── dist/                  # (generado, no versionado) build final "onedir"
└── Output/                # (generado, no versionado) instalador .exe final
```

## Por qué estos pasos y no simplemente `pyinstaller main.py`

Flet en modo escritorio no dibuja la ventana con Python: lanza un cliente
nativo compilado en Flutter (`flet.exe` + ~90 MB de DLLs) y Python se conecta
a él por WebSocket local. Ese cliente **no viene incluido en el paquete pip**
de `flet_desktop` — la primera vez que se ejecuta la app, `flet_desktop` lo
descarga de GitHub Releases y lo cachea en `~/.flet/client/...`. Eso es
perfecto para desarrollo, pero inaceptable para un instalador: el cliente
final necesitaría internet la primera vez que abre la app.

`flet_desktop.ensure_client_cached()` (ver
`env/Lib/site-packages/flet_desktop/__init__.py`) resuelve esto buscando,
antes de intentar descargar nada, un archivo `flet-windows.zip` embebido en
`flet_desktop/app/` dentro del propio paquete — exactamente el hueco que
`prepare_flet_client.py` + el spec de PyInstaller llenan, para que el
instalador final funcione 100% offline.

## Pasos para generar el instalador

Desde la raíz del repo, con el entorno virtual activado:

```bash
# 0. (Solo una vez, o si cambia el ícono) Regenerar los PNG/ICO del ícono:
env/Scripts/python.exe installer/assets/generate_icon.py

# 1. Empaquetar el cliente de escritorio de Flet para distribución offline.
#    Requiere haber ejecutado `python main.py` al menos una vez en esta
#    máquina (así queda cacheado en ~/.flet/client/...); si no encuentra
#    caché local, lo descarga de GitHub Releases automáticamente.
env/Scripts/python.exe installer/prepare_flet_client.py

# 2. Build de PyInstaller (genera installer/dist/SistemaInventario/).
env/Scripts/pyinstaller.exe installer/inventory_manager.spec --noconfirm --distpath installer/dist --workpath installer/build

# 3. Probar el .exe generado ANTES de empaquetarlo (importante: valida que
#    el cliente de Flet embebido arranca sin pedir descargar nada):
installer\dist\SistemaInventario\SistemaInventario.exe

# 4. Compilar el instalador con Inno Setup 6:
#    Si `iscc` está en tu PATH:
iscc installer\setup.iss

#    O usando la ruta completa en PowerShell:
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\setup.iss
```

El instalador final queda en `installer\Output\SistemaInventario_Setup_<version>.exe`.

## Notas

- **Base de datos y preferencias del usuario:** viven en
  `%APPDATA%\SistemaInventario\` (ver [core/config.py](../core/config.py)),
  nunca dentro de la carpeta de instalación — así una actualización
  (reinstalar encima) nunca borra ni sobrescribe los datos del cliente.
- **Contraseña inicial del usuario `admin`:** si no se define `RECUPERAR_PASS`
  en un `.env` (no se empaqueta ninguno por defecto), se usa el valor de
  respaldo definido en `core/config.py`. Para una build de producción real,
  considera fijar una contraseña propia antes de compilar.
- **Versión:** actualiza `MyAppVersion` en `setup.iss` en cada release —
  Inno Setup lo usa para el nombre del instalador y el registro de
  desinstalación de Windows.
- **onedir, no onefile:** el spec genera una carpeta completa (`SistemaInventario.exe`
  + `_internal/`) en vez de un único `.exe` comprimido. Un onefile
  extraería los ~90 MB del cliente de Flet a una carpeta temporal en *cada*
  arranque, haciendo que la app tarde varios segundos extra en abrir cada
  vez — onedir solo paga ese costo una vez, en la instalación.
- **Regenerar el ícono:** editar `installer/assets/generate_icon.py` (dibuja
  formas con Pillow, sin depender de ningún archivo de arte externo) y
  volver a ejecutarlo.
