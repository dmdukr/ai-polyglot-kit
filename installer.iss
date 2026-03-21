; Inno Setup script for Groq Dictation
; Requires Inno Setup 6+ (https://jrsoftware.org/isinfo.php)

#define MyAppName "Groq Dictation"
#define MyAppVersion "2.0.6"
#define MyAppPublisher "dmdukr"
#define MyAppURL "https://github.com/dmdukr/groq-dictation"
#define MyAppExeName "GroqDictation.exe"

[Setup]
AppId={{B7F3A8D1-2E5C-4A9B-8D1F-3C6E9A7B5D2F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=installer_output
OutputBaseFilename=GroqDictation-{#MyAppVersion}-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
UninstallDisplayName={#MyAppName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
; Autostart managed by app Settings, not installer

[Files]
; Onedir mode: copy entire dist\GroqDictation\ folder
Source: "dist\GroqDictation\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "config.yaml"; DestDir: "{app}"; Flags: ignoreversion onlyifdoesntexist

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

; Registry autostart managed by app Settings (not installer)

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall

[UninstallRun]
Filename: "taskkill"; Parameters: "/F /IM {#MyAppExeName}"; Flags: runhidden; RunOnceId: "KillApp"

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if CurStep = ssInstall then
  begin
    // Kill running instance before install
    Exec('taskkill', '/F /IM ' + '{#MyAppExeName}', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    // Wait for process to fully exit and release file locks
    Sleep(2000);
  end;
end;
