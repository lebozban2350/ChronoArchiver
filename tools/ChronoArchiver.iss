; Inno Setup script for ChronoArchiver (Windows x64)
; Run after: pyinstaller tools/chronoarchiver.spec
; Requires: dist/ChronoArchiver/ folder from PyInstaller

#define MyAppName "ChronoArchiver"
#define MyAppVersion "3.5.2"
#define MyAppPublisher "UnDadFeated"
#define MyAppURL "https://github.com/UnDadFeated/ChronoArchiver"
#define MyAppExeName "ChronoArchiver.exe"
#define MyAppAssocName "ChronoArchiver"
#define MyAppAssocExt ""
#define BuildDir "..\dist\ChronoArchiver"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={autopf}\{#MyAppName}
; User can change install directory on the Select Destination Location page
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Output (relative to script dir; pyinstaller puts build in repo_root/dist/)
OutputDir=..\dist
OutputBaseFilename=ChronoArchiver-{#MyAppVersion}-win64
SetupIconFile=..\src\ui\assets\icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
; x64 only
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#BuildDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

; Remove entire install dir on uninstall (static_ffmpeg creates win32.zip + bin/win32 at runtime)
[UninstallDelete]
Type: filesandordirs; Name: "{app}"
