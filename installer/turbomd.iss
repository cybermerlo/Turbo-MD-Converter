; ============================================================
;  Turbo MD Converter – script Inno Setup
;  Non modificare AppVersion e BuildDir: vengono iniettati
;  automaticamente da build_installer.py tramite version.iss
; ============================================================

#include "version.iss"

; ── Informazioni applicazione ────────────────────────────────────────────────
[Setup]
AppId={{A7F3C2D1-8B4E-4A9F-B612-3E5D7C8A0F21}
AppName=Turbo MD Converter
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}
AppCopyright=© {#AppYear} {#AppPublisher}

; Cartella di installazione (non richiede admin grazie a "lowest")
DefaultDirName={autopf}\Turbo MD Converter
DefaultGroupName=Turbo MD Converter
DisableProgramGroupPage=yes

; Output installer
OutputDir={#SourcePath}\output
OutputBaseFilename=TurboMDConverter_Setup_{#AppVersion}

; Aspetto
SetupIconFile={#SourcePath}\..\logo.ico
WizardStyle=modern

; Compressione
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes

; Privilegi: "lowest" → installa per l'utente corrente senza UAC
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; Requisiti Windows
MinVersion=10.0

; Disinstallatore
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName=Turbo MD Converter {#AppVersion}

; Altre opzioni
ShowLanguageDialog=no
CloseApplications=yes
RestartApplications=no

; ── Lingue ───────────────────────────────────────────────────────────────────
[Languages]
Name: "italian"; MessagesFile: "compiler:Languages\Italian.isl"

; ── Task opzionali (mostrati nella procedura guidata) ────────────────────────
[Tasks]
Name: "desktopicon";     Description: "Crea un'icona sul Desktop";              GroupDescription: "Icone aggiuntive:"; Flags: unchecked
Name: "sendtoicon";      Description: "Aggiungi al menu contestuale 'Invia a'"; GroupDescription: "Icone aggiuntive:"; Flags: unchecked

; ── File da installare ───────────────────────────────────────────────────────
[Files]
; Tutta la cartella build cx_Freeze (ricorsiva)
Source: "{#BuildDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; ── Icone Start Menu / Desktop / SendTo ──────────────────────────────────────
[Icons]
; Start Menu
Name: "{group}\Turbo MD Converter";             Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\{#AppExeName}"
Name: "{group}\Disinstalla Turbo MD Converter"; Filename: "{uninstallexe}";      IconFilename: "{uninstallexe}"

; Desktop (opzionale) – {userdesktop} non richiede admin (compatibile con PrivilegesRequired=lowest)
Name: "{userdesktop}\Turbo MD Converter";       Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\{#AppExeName}"; Tasks: desktopicon

; Menu "Invia a" di Windows (opzionale)
Name: "{sendto}\Turbo MD Converter";            Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\{#AppExeName}"; Comment: "Invia file a Turbo MD Converter"; Tasks: sendtoicon

; ── Avvia l'app al termine dell'installazione ─────────────────────────────────
[Run]
Filename: "{app}\{#AppExeName}"; Description: "Avvia Turbo MD Converter"; Flags: nowait postinstall skipifsilent

; ── Pagina API key e scrittura config ────────────────────────────────────────
[Code]

var
  ApiKeyPage: TInputQueryWizardPage;

procedure InitializeWizard;
begin
  ApiKeyPage := CreateInputQueryPage(
    wpSelectTasks,
    'Chiave API Google Gemini',
    'Configura l''accesso all''intelligenza artificiale',
    'Turbo MD Converter usa Google Gemini per l''OCR e l''estrazione dati.' + #13#10 +
    'Ottieni una chiave gratuita su: https://aistudio.google.com/apikey' + #13#10#13#10 +
    'Puoi lasciare vuoto e inserirla in seguito dalle Impostazioni dell''app.'
  );
  ApiKeyPage.Add('Chiave API Gemini:', True);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ConfigDir, ConfigFile, ApiKey, Json: string;
begin
  if CurStep <> ssPostInstall then Exit;

  ApiKey := Trim(ApiKeyPage.Values[0]);
  if ApiKey = '' then Exit;

  ConfigDir  := ExpandConstant('{userappdata}\OCRLangExtract');
  ConfigFile := ConfigDir + '\config.json';

  if not DirExists(ConfigDir) then
    ForceDirectories(ConfigDir);

  { Scrivi solo se il file non esiste (installazione nuova).
    In caso di aggiornamento l'utente ha già la sua chiave nel config. }
  if not FileExists(ConfigFile) then
  begin
    Json := '{' + #13#10 +
            '  "gemini_api_key": "' + ApiKey + '",' + #13#10 +
            '  "langextract_api_key": "' + ApiKey + '"' + #13#10 +
            '}';
    SaveStringToFile(ConfigFile, Json, False);
  end;
end;
