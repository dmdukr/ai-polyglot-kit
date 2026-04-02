; Inno Setup script for AI Polyglot Kit
; Requires Inno Setup 6+ (https://jrsoftware.org/isinfo.php)

#define MyAppName "AI Polyglot Kit"
#define MyAppVersion "7.0.4"
#define MyAppPublisher "dmdukr"
#define MyAppURL "https://github.com/dmdukr/ai-polyglot-kit"
#define MyAppExeName "AIPolyglotKit.exe"

; Old app IDs to uninstall before upgrade
#define OldAppId "{{B7F3A8D1-2E5C-4A9B-8D1F-3C6E9A7B5D2F}"

[Setup]
; New unique AppId — breaks link with old "Groq Dictation" installs
AppId={{A1B2C3D4-5678-90AB-CDEF-112233445566}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=installer_output
OutputBaseFilename=AIPolyglotKit-{#MyAppVersion}-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
UninstallDisplayName={#MyAppName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\AIPolyglotKit\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "config.yaml"; DestDir: "{app}"; Flags: ignoreversion onlyifdoesntexist

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall

[UninstallRun]
Filename: "taskkill"; Parameters: "/F /IM {#MyAppExeName}"; Flags: runhidden; RunOnceId: "KillApp"
Filename: "taskkill"; Parameters: "/F /IM GroqDictation.exe"; Flags: runhidden; RunOnceId: "KillOldApp"

[Code]
procedure UninstallOldVersion(UninstallKey: String; AppFolder: String);
var
  UninstallString: String;
  ResultCode: Integer;
begin
  // Try to find uninstall string in registry
  if RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\' + UninstallKey + '_is1',
     'UninstallString', UninstallString) then
  begin
    Log('Found old install: ' + UninstallString);
    Exec(RemoveQuotes(UninstallString), '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Log('Old uninstall exit code: ' + IntToStr(ResultCode));
  end;

  // Also try to delete leftover folders
  if DirExists(AppFolder) then
  begin
    Log('Removing leftover folder: ' + AppFolder);
    DelTree(AppFolder, True, True, True);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  UserPrograms: String;
begin
  if CurStep = ssInstall then
  begin
    // Kill ALL running instances (old and new names)
    Exec('taskkill', '/F /IM AIPolyglotKit.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Exec('taskkill', '/F /IM GroqDictation.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Sleep(2000);

    // Determine user programs folder
    UserPrograms := ExpandConstant('{autopf}');

    // Uninstall old "Groq Dictation" (same AppId as before)
    UninstallOldVersion('{#OldAppId}', UserPrograms + '\Groq Dictation');

    // Uninstall old "AI Polyglot Kit" with old AppId
    UninstallOldVersion('{#OldAppId}', UserPrograms + '\AI Polyglot Kit');

    // Clean up old folders that might have stale files
    if DirExists(UserPrograms + '\Groq Dictation') then
      DelTree(UserPrograms + '\Groq Dictation', True, True, True);
  end;
end;
