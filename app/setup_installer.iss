; DEPRECATED — use packaging\setup_installer.iss (output goes to repo-root release\).
; Kept so old docs that mention app\setup_installer.iss still find a file.
; Prefer: packaging\build_installer.bat

#define MyAppName "Ignite Chat"
#define MyAppVersion "1.0.0"

[Setup]
AppId={{C789233D-BD91-443B-9BFD-E22A26C6B0F9}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\{#MyAppName}
OutputDir=..\release
OutputBaseFilename=IgniteChat_Setup
SetupIconFile=icon.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
Source: "dist\Ignite Chat\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion; Excludes: ".env,.env.local,.env.staging,.env.prod"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\Ignite Chat.exe"

[Run]
Filename: "{app}\Ignite Chat.exe"; Flags: nowait postinstall skipifsilent
