; Script de Inno Setup para el instalador de Windows del
; "Sistema Integrado de Inventario y Ventas".
;
; Requiere que ya exista installer/dist/SistemaInventario/ (el build "onedir"
; de PyInstaller) — ver installer/README.md para el proceso completo.
;
; Compilar (Inno Setup 6, ISCC.exe en el PATH o su ruta de instalación):
;   iscc installer\setup.iss
;
; El instalador queda en installer\Output\SistemaInventario_Setup_<version>.exe

#define MyAppName "Sistema Integrado de Inventario y Ventas"
#define MyAppVersion "1.0.1"
#define MyAppPublisher "Kerwin Quintero"
#define MyAppExeName "SistemaInventario.exe"
#define MyAppId "{{7C6E8B6E-6C2C-4B2E-9E9C-6E0E2C1D9A31}"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; La base de datos y las preferencias del usuario viven en
; %APPDATA%\SistemaInventario (ver core/config.py) — nunca dentro de esta
; carpeta de instalación, así que reinstalar/actualizar nunca las toca.
OutputDir=Output
OutputBaseFilename=SistemaInventario_Setup_{#MyAppVersion}
SetupIconFile=assets\icon.ico
LicenseFile=LICENCIA.txt
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; Todo el contenido del build "onedir" de PyInstaller (exe + carpeta
; _internal con las dependencias, incluido el cliente de escritorio de
; Flet ya embebido — ver installer/prepare_flet_client.py).
Source: "dist\SistemaInventario\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Limpia únicamente artefactos generados por la app dentro de la carpeta de
; instalación (p.ej. import_debug.log si el usuario ejecutó una versión de
; desarrollo desde ahí); NO toca %APPDATA%\SistemaInventario, donde vive la
; base de datos real del cliente — esa carpeta se conserva a propósito
; entre instalaciones/desinstalaciones.
Type: files; Name: "{app}\import_debug.log"
