; HandJob3000 — Inno Setup installer script
; Per-user install (no admin), Desktop icon default on, launch after install,
; clean uninstaller, optional "start control on launch" preference.
#define AppName "HandJob3000"
#define AppVersion "2.5.1"
#define AppExe "HandJob3000.exe"

[Setup]
AppId=HandJob3000.ReynardFilbertTang
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Reynard Filbert Tang
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist-installer
OutputBaseFilename={#AppName}-Setup-{#AppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
CloseApplications=yes
RestartApplications=no
DisableWelcomePage=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "startcontrol"; Description: "Start gesture control automatically when the app opens"; GroupDescription: "Options:"; Flags: unchecked

[Files]
Source: "..\dist\HandJob3000\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\README-INSTALL.txt"; DestDir: "{app}"; Flags: ignoreversion
; ready-to-use alternative model (the lite landmark bundle — ~2x faster, same accuracy class)
Source: "..\build\models_lab\hand_landmarker_lite.task"; DestDir: "{app}\models"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  Json: String;
  FileName: String;
begin
  if CurStep = ssPostInstall then
  begin
    if WizardIsTaskSelected('startcontrol') then
    begin
      FileName := ExpandConstant('{app}\settings.json');
      Json := '{' + #13#10 +
              '  "start_enabled": true' + #13#10 +
              '}';
      if not FileExists(FileName) then
        SaveStringToFile(FileName, Json, False);
    end;
  end;
end;
