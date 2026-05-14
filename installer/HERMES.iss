; HERMES.iss — Script Inno Setup pour l'installeur HERMES.
;
; Ce script suppose que `scripts/build-installer.ps1` a déjà :
;   1. Recompilé hermes.exe (npm run tauri build)
;   2. Recompilé backend.exe (scripts/build-backend.ps1)
;   3. Copié les fichiers dans installer/staging/
;
; Le résultat est `installer/dist/HERMES-Setup-<version>.exe`.

#define MyAppName "HERMES"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "HERMES"
#define MyAppURL "https://hermes.local"
#define MyAppExeName "hermes.exe"
#define MyAppId "{{9E5C8D7A-6F4B-4A2E-B1D9-A3C5E7F8B2D4}"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
LicenseFile=
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=dist
OutputBaseFilename=HERMES-Setup-{#MyAppVersion}
SetupIconFile=staging\hermes.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
WizardImageStretch=no
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName} {#MyAppVersion}
CloseApplications=force
CloseApplicationsFilter=*.exe

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "Créer un raccourci sur le Bureau"; GroupDescription: "Raccourcis :"; Flags: checkablealone

[Files]
; Application Tauri
Source: "staging\hermes.exe"; DestDir: "{app}"; Flags: ignoreversion
; Backend Python compilé (PyInstaller — onedir)
Source: "staging\backend\*"; DestDir: "{app}\backend"; Flags: ignoreversion recursesubdirs createallsubdirs
; Installeur Ollama embarqué (optionnel — si absent on prévient l'utilisateur)
Source: "staging\OllamaSetup.exe"; DestDir: "{tmp}"; Flags: ignoreversion deleteafterinstall skipifsourcedoesntexist; Check: NeedsOllama

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Désinstaller {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Install Ollama silencieux si fourni
Filename: "{tmp}\OllamaSetup.exe"; Parameters: "/SILENT /CLOSEAPPLICATIONS"; StatusMsg: "Installation de PYTHIA (Ollama)..."; Flags: waituntilterminated skipifdoesntexist; Check: NeedsOllama
; Lance HERMES à la fin (case cochée par défaut)
Filename: "{app}\{#MyAppExeName}"; Description: "Lancer {#MyAppName} maintenant"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; À la désinstallation, on tue les processus HERMES en cours.
Filename: "taskkill.exe"; Parameters: "/F /IM hermes.exe /T"; Flags: runhidden; RunOnceId: "kill_hermes"
Filename: "taskkill.exe"; Parameters: "/F /IM backend.exe /T"; Flags: runhidden; RunOnceId: "kill_backend"

[UninstallDelete]
; Nettoyage : on supprime le dossier data si l'utilisateur le demande explicitement
; (laissé en l'état par défaut — voir confirmation côté Code).
Type: filesandordirs; Name: "{app}\backend"

[Code]
function NeedsOllama: Boolean;
{ Vérifie si Ollama est déjà installé. On regarde dans les emplacements
  d'install standard pour ne pas réinstaller inutilement. }
begin
  Result :=
    not FileExists(ExpandConstant('{commonpf64}\Ollama\ollama.exe')) and
    not FileExists(ExpandConstant('{commonpf}\Ollama\ollama.exe')) and
    not FileExists(ExpandConstant('{localappdata}\Programs\Ollama\ollama.exe'));
end;

function InitializeSetup: Boolean;
var
  Reponse: Integer;
  OllamaPresent: Boolean;
  InstallerOllamaPresent: Boolean;
begin
  Result := True;
  OllamaPresent := not NeedsOllama;
  InstallerOllamaPresent := FileExists(ExpandConstant('{src}\staging\OllamaSetup.exe'));

  if (not OllamaPresent) and (not InstallerOllamaPresent) then
  begin
    Reponse := MsgBox(
      'Ollama (PYTHIA) n''est pas installé sur cette machine et ' +
      'l''installeur de Ollama n''est pas inclus dans ce package.' + #13#10#13#10 +
      'HERMES a besoin d''Ollama pour fonctionner. Tu peux :' + #13#10 +
      '  - Continuer l''installation et installer Ollama manuellement plus tard ' +
      '(téléchargement depuis https://ollama.com/download).' + #13#10 +
      '  - Annuler maintenant et relancer avec un installeur qui inclut Ollama.' + #13#10#13#10 +
      'Continuer quand même ?',
      mbConfirmation, MB_YESNO);
    if Reponse = IDNO then
      Result := False;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Reponse: Integer;
  DataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{localappdata}\HERMES');
    if DirExists(DataDir) then
    begin
      Reponse := MsgBox(
        'Conserver les données HERMES (BDD, documents téléchargés, logs) ?' + #13#10#13#10 +
        DataDir + #13#10#13#10 +
        'Choisir « Non » supprimera définitivement toutes les données locales.',
        mbConfirmation, MB_YESNO);
      if Reponse = IDNO then
        DelTree(DataDir, True, True, True);
    end;
  end;
end;
