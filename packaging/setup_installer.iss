; Ignite Chat — Windows installer (Inno Setup 6)
; Source : app\dist\Ignite Chat\   (PyInstaller onedir)
; Output : release\IgniteChat_Setup.exe  (gitignored)
;
; Design:
; - Per-user install under %LOCALAPPDATA%\Programs\Ignite Chat (no admin)
; - User data/logs under %LOCALAPPDATA%\Ignite Chat (kept across reinstalls)
; - Never ships .env secrets; seeds .env from .env.example on first install
; - Checks WebView2 Runtime and offers the official evergreen bootstrapper URL

#define MyAppName "Ignite Chat"
#define MyAppVersion "1.1.0"
#define MyAppPublisher "Ignite"
#define MyAppURL "https://github.com/Razor2296/IgniteChat"
#define MyAppExeName "Ignite Chat.exe"
#define MyAppId "{{C789233D-BD91-443B-9BFD-E22A26C6B0F9}"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=..\release
OutputBaseFilename=IgniteChat_Setup
SetupIconFile=..\app\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
WizardSizePercent=120
DisableProgramGroupPage=yes
DisableWelcomePage=no
DisableDirPage=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
MinVersion=10.0
CloseApplications=yes
CloseApplicationsFilter={#MyAppExeName},msedgewebview2.exe
RestartApplications=no
VersionInfoVersion={#MyAppVersion}.0
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} Setup
VersionInfoProductName={#MyAppName}
SetupLogging=yes

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"; InfoBeforeFile: "info_before.es.txt"
Name: "english"; MessagesFile: "compiler:Default.isl"; InfoBeforeFile: "info_before.en.txt"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce

[Dirs]
; User data root (sessions, logs, RAG) — survives app uninstall of Programs\
Name: "{localappdata}\{#MyAppName}"
Name: "{localappdata}\{#MyAppName}\log"

[Files]
Source: "..\app\dist\Ignite Chat\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion; Excludes: ".env,.env.local,.env.staging,.env.prod,.env.*~"
Source: "..\app\.env.example"; DestDir: "{app}"; DestName: ".env.example"; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\app\icon.ico"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\icon.ico"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\icon.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent unchecked
Filename: "https://go.microsoft.com/fwlink/p/?LinkId=2124703"; Description: "Descargar / Install Microsoft Edge WebView2 Runtime (si falta)"; Flags: postinstall shellexec skipifsilent unchecked; Check: not IsWebView2RuntimeInstalled

[Code]
function IsWebView2RuntimeInstalled: Boolean;
begin
  Result :=
    RegKeyExists(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}') or
    RegKeyExists(HKLM, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}') or
    RegKeyExists(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}');
end;

function InitializeSetup: Boolean;
begin
  Result := True;
  if not IsWebView2RuntimeInstalled then
  begin
    if MsgBox(
      'Microsoft Edge WebView2 Runtime no está instalado / is not installed.' + #13#10 + #13#10 +
      'Ignite Chat lo necesita para la interfaz.' + #13#10 +
      'Puedes continuar e instalar WebView2 al final del asistente.' + #13#10 + #13#10 +
      'Continue anyway?',
      mbConfirmation, MB_YESNO) = IDNO then
      Result := False;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ExamplePath, EnvPath, DataMarker: string;
begin
  if CurStep = ssPostInstall then
  begin
    ExamplePath := ExpandConstant('{app}\.env.example');
    EnvPath := ExpandConstant('{app}\.env');
    if (not FileExists(EnvPath)) and FileExists(ExamplePath) then
      CopyFile(ExamplePath, EnvPath, False);

    { Hint file for support — data lives beside LocalAppData\Ignite Chat }
    DataMarker := ExpandConstant('{app}\DATA_LOCATION.txt');
    SaveStringToFile(
      DataMarker,
      'User data (logs, chats, RAG):' + #13#10 +
      ExpandConstant('{localappdata}\{#MyAppName}') + #13#10 + #13#10 +
      'Install folder (binaries):' + #13#10 +
      ExpandConstant('{app}') + #13#10,
      False);
  end;
end;
