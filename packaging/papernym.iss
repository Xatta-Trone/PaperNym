; PaperNym installer (Inno Setup 6). Built by scripts/build_windows.py, which passes:
;   /DAppVersion=0.1.0 /DSourceDir=<dist\PaperNym> /DOutputDir=<dist> /DRootDir=<repo>
; Per-user install: no administrator rights, nothing outside the user's profile.

#ifndef AppVersion
  #error Run through scripts/build_windows.py (AppVersion is not defined)
#endif

#define AppName "PaperNym"
#define AppExe "PaperNym.exe"
#define Repo "https://github.com/Xatta-Trone/papernym"

[Setup]
AppId={{45A3E91D-4BE9-4FDE-8CD9-6B8E52ED8481}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Xatta-Trone
AppPublisherURL={#Repo}
AppSupportURL={#Repo}/issues
AppUpdatesURL={#Repo}/releases
AppCopyright=Copyright (c) 2026 Xatta-Trone. MIT License.
VersionInfoVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\{#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename=PaperNym-Setup-{#AppVersion}
SetupIconFile={#RootDir}\src\papernym\gui\icons\papernym.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
LicenseFile={#RootDir}\LICENSE
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=force
RestartApplications=no
ChangesEnvironment=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "startatlogin"; Description: "Start PaperNym when I log in (it waits quietly in the tray)"; GroupDescription: "Options:"
Name: "addtopath"; Description: "Add the ""papernym"" command to PATH (use it in cmd or PowerShell)"; GroupDescription: "Options:"
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Options:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#RootDir}\packaging\papernym.cmd"; DestDir: "{app}\bin"; Flags: ignoreversion

[InstallDelete]
; a previous version's bundled libraries are replaced as a whole
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{userprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; Comment: "Names your research papers"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; Start at login. The marker tells the app what was chosen here, so it adopts the choice
; into its own settings on the next start instead of undoing it.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "PaperNym"; ValueData: """{app}\{#AppExe}"""; Tasks: startatlogin
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "PaperNym"; Flags: deletevalue; Tasks: not startatlogin
Root: HKCU; Subkey: "Software\PaperNym"; ValueType: dword; ValueName: "InstallerStartAtLogin"; ValueData: 1; Flags: uninsdeletekey; Tasks: startatlogin
Root: HKCU; Subkey: "Software\PaperNym"; ValueType: dword; ValueName: "InstallerStartAtLogin"; ValueData: 0; Flags: uninsdeletekey; Tasks: not startatlogin
; PATH: add {app}\bin (papernym.cmd) once; removed again by the uninstaller.
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}\bin"; Tasks: addtopath; Check: NeedsAddPath(ExpandConstant('{app}\bin'))

[Run]
Filename: "{app}\{#AppExe}"; Parameters: "--show"; Description: "Open PaperNym now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM {#AppExe}"; Flags: runhidden; RunOnceId: "StopPaperNym"

[Code]
var
  RemoveSettings: Boolean;

function NeedsAddPath(Dir: string): Boolean;
var
  Paths: string;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', Paths) then
  begin
    Result := True;
    exit;
  end;
  Result := Pos(';' + Uppercase(Dir) + ';', ';' + Uppercase(Paths) + ';') = 0;
end;

procedure RemoveFromPath(Dir: string);
var
  Paths: string;
  P: Integer;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', Paths) then
    exit;
  Paths := ';' + Paths + ';';
  P := Pos(';' + Uppercase(Dir) + ';', Uppercase(Paths));
  if P = 0 then
    exit;
  Delete(Paths, P, Length(Dir) + 1);
  Paths := Copy(Paths, 2, Length(Paths) - 2);
  RegWriteExpandStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', Paths);
end;

function InitializeUninstall(): Boolean;
begin
  RemoveSettings := False;
  if not UninstallSilent then
    RemoveSettings := MsgBox('Also remove your PaperNym settings, rename history and saved API keys?' + #13#10 + #13#10 +
      'Choose No to keep them for a later reinstall. Your PDF files are not touched either way.',
      mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES;
  Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Code: Integer;
begin
  if CurUninstallStep = usUninstall then
  begin
    if RemoveSettings then
    begin
      { forget the keys in Windows Credential Manager while the CLI is still installed }
      Exec(ExpandConstant('{app}\papernym-cli.exe'), 'set-key openalex ""', '', SW_HIDE, ewWaitUntilTerminated, Code);
      Exec(ExpandConstant('{app}\papernym-cli.exe'), 'set-key semanticscholar ""', '', SW_HIDE, ewWaitUntilTerminated, Code);
    end;
  end;
  if CurUninstallStep = usPostUninstall then
  begin
    { the app may have turned start-at-login on itself }
    RegDeleteValue(HKEY_CURRENT_USER, 'Software\Microsoft\Windows\CurrentVersion\Run', 'PaperNym');
    RemoveFromPath(ExpandConstant('{app}\bin'));
    if RemoveSettings then
      DelTree(ExpandConstant('{userappdata}\PaperNym'), True, True, True);
  end;
end;
