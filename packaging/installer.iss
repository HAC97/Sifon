; Inno Setup script for sifón. Built by packaging/build.py --installer, which passes:
;   /DAppVersion=0.2.1 /DSourceDir=<dist\sifon> /DOutputDir=<dist> /DIconFile=<build\sifon.ico>
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #error SourceDir is required
#endif
#ifndef OutputDir
  #define OutputDir "."
#endif

[Setup]
; Fixed: it identifies this app for upgrades and for the uninstaller. Never change it.
AppId={{6F1D2E8B-3B7A-4C55-9E0A-5A1F2C7D9B31}
AppName=sifón
AppVersion={#AppVersion}
AppVerName=sifón {#AppVersion}
AppPublisher=HAC97
AppPublisherURL=https://github.com/HAC97/Sifon
AppSupportURL=https://github.com/HAC97/Sifon/issues
VersionInfoVersion={#AppVersion}
; Per-user install: no administrator prompt, nothing outside the user's own folders.
PrivilegesRequired=lowest
DefaultDirName={autopf}\sifon
DefaultGroupName=sifón
DisableProgramGroupPage=yes
OutputDir={#OutputDir}
OutputBaseFilename=sifon-{#AppVersion}-setup
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\sifon.exe
LicenseFile={#SourceDir}\licenses\LICENSE
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; An update replaces files that a running sifón holds: ask Windows to close it first.
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[InstallDelete]
; An upgrade replaces the bundled libraries wholesale: files of an older layout must not linger.
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\bin"

[Icons]
Name: "{autoprograms}\sifón"; Filename: "{app}\sifon.exe"
Name: "{autodesktop}\sifón"; Filename: "{app}\sifon.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\sifon.exe"; Description: "Iniciar sifón"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Logs, preferences and downloaded yt-dlp updates live here; downloaded media never does.
Type: filesandordirs; Name: "{localappdata}\sifon"
