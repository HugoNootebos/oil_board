; Windows installer for OIL (Inno Setup 6). First build the app's folder,
;   python packaging\build.py windows        -> build\windows\OIL
; then
;   iscc packaging\oil_installer.iss         -> dist\OIL-Setup.exe
; The GitHub workflow (.github/workflows/build-app.yml) does both.
;
; Installs for the current user only (no administrator needed) into
; %LOCALAPPDATA%\Programs\OIL. The game, its updates and the saves live in
; %LOCALAPPDATA%\OIL (packaging\bootstrap.py), which uninstalling leaves alone.

#define AppDir "..\build\windows\OIL"

[Setup]
AppId={{8C1F6F2E-5B7A-4E0B-9C61-0D4B2F7A9E31}
AppName=OIL
AppVersion=1.0
AppPublisher=Hugo Nootebos
AppPublisherURL=https://github.com/HugoNootebos/oil_board
DefaultDirName={localappdata}\Programs\OIL
DefaultGroupName=OIL
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=OIL-Setup
SetupIconFile={#AppDir}\OIL.ico
UninstallDisplayIcon={app}\OIL.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "nl"; MessagesFile: "compiler:Languages\Dutch.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; A newer app replaces the old one's files completely.
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\libs"
Type: filesandordirs; Name: "{app}\game"

[Files]
Source: "{#AppDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\OIL"; Filename: "{app}\python\pythonw.exe"; Parameters: "-I ""{app}\bootstrap.py"""; WorkingDir: "{app}"; IconFilename: "{app}\OIL.ico"; AppUserModelID: "HugoNootebos.OIL"
Name: "{autodesktop}\OIL"; Filename: "{app}\python\pythonw.exe"; Parameters: "-I ""{app}\bootstrap.py"""; WorkingDir: "{app}"; IconFilename: "{app}\OIL.ico"; AppUserModelID: "HugoNootebos.OIL"; Tasks: desktopicon

[Run]
Filename: "{app}\python\pythonw.exe"; Parameters: "-I ""{app}\bootstrap.py"""; WorkingDir: "{app}"; Description: "{cm:LaunchProgram,OIL}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Python's compiled files written next to the app; the saves are elsewhere.
Type: filesandordirs; Name: "{app}"
