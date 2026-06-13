# AGENTS.md — Turbo MD Converter

Guida rapida per chi (umano o agente) lavora su questo repository.

## Cos'è
App desktop **Windows in Python puro** (CustomTkinter) che converte documenti
eterogenei in **Markdown**: PDF, immagini, audio/video, email (`.eml`/`.msg`),
archivi, firmati `.p7m` e **conversazioni WhatsApp**. Usa OCR (Google Gemini),
trascrizione audio (Mistral Voxtral) ed estrazione strutturata opzionale
(LangExtract). Nessun runtime Node/JS.

## Avvio, test, build
- **Eseguire da sorgente**: `py main.py` (oppure `python main.py`)
- **Test**: `python -m unittest discover -s tests`
- **Build .exe + installer**: `python build_installer.py` (cx_Freeze + Inno Setup)
- **Config utente**: `%APPDATA%\OCRLangExtract\config.json` (chiavi API in chiaro)

## Architettura (cartelle)
- `main.py` — entry point GUI
- `gui/` — interfaccia: `app.py` (finestra principale), `frames/` (pannelli),
  `theme.py` (stile paper+amber), `resources.py` (path risorse + cartelle output)
- `pipeline/` — `processor.py` (acquire→extract→write), `attachment_processor.py`
  (router file→testo), `email_sources.py` / `archive_sources.py` /
  `whatsapp_sources.py`, `constants.py`
- `ocr/` — `gemini_ocr.py`, `ocr_pipeline.py`, `audio_transcriber.py`
- `extraction/` — wrapper LangExtract · `output/` — formatter MD/JSON + writer
- `config/` — `AppConfig` dataclass + persistenza JSON
- `whatsapp/` — importazione conversazioni (vedi sotto)
- `vendor/adb/` — `adb.exe` + DLL impacchettati (necessari per WhatsApp)
- `tests/` — unittest

## Modello dati della pipeline
Ogni input è un `Path`; **ogni input → un file `.md`**.
`processor._acquire_text()` instrada per estensione: audio→trascrizione,
immagini/PDF→OCR, suffissi in `DIRECT_READ_FORMATS`→lettura diretta
(email, archivi, `.wachat`). Email e WhatsApp **uniscono corpo + media in un
unico testo** → un solo MD (vedi `join_email_and_attachments` /
`extract_whatsapp_parts`).

## Funzione "Importa da WhatsApp" (Android, tutto in locale)
Estrae conversazioni dal **backup locale** del telefono — niente cloud, niente
login, nessun rischio ban. Wizard: `gui/frames/whatsapp_import_window.py`.

Flusso:
1. **adb** (`vendor/adb`) rileva il telefono via USB (Debug USB attivo).
2. `pull` di `msgstore.db.crypt15` da
   `/sdcard/Android/media/com.whatsapp/WhatsApp/Databases` (accessibile senza root).
3. **decifratura** con `wa-crypt-tools` usando la chiave E2E a 64 cifre
   (inserita in Impostazioni → WhatsApp).
4. **rubrica** via `adb shell content query` (niente root) per risolvere i nomi.
5. **parse SQLite** (`whatsapp/msgstore_reader.py`) → lista chat ricercabile.
6. L'utente sceglie una chat + periodo (preset "Oggi/Ieri/7g/30g" o calendario),
   poi `pull` dei **soli media di quella chat** → si costruisce un pacchetto
   **`.wachat`** (zip: `transcript.txt` con placeholder media + i file media).
7. Il `.wachat` entra nella pipeline come singolo input;
   `pipeline/whatsapp_sources.py` inlinea testo + OCR immagini + trascrizione
   note vocali → un unico MD.

Moduli `whatsapp/`: `adb_bridge`, `backup_decryptor`, `msgstore_reader`,
`package_builder`.

Dettagli operativi:
- Il `.wachat` è un **intermedio** in `%TEMP%\TurboMD_WhatsApp` (cancellato alla
  chiusura dell'app); l'**MD** finale va in `Download\Turbo MD Converter`.
- L'estrazione è **messa in cache per sessione**; pulsante "Aggiorna" per
  ri-scaricare il backup. Importare i media richiede il telefono collegato.
- **Setup utente una-tantum**: Debug USB + backup cifrato end-to-end di WhatsApp
  con chiave a 64 cifre.

## Convenzioni e gotcha
- **UI e commenti in italiano.**
- I subprocess adb usano `encoding="utf-8"`: l'output (rubrica, nomi) contiene
  caratteri non-ASCII/emoji e con il codec locale Windows (cp1252) andrebbe in crash.
- Le note vocali WhatsApp sono **`.opus`** (in `AUDIO_EXTENSIONS` e
  `AUDIO_MIME_TYPES` → `audio/ogg`). Anche `to_text()` ora trascrive l'audio
  (vale per allegati `.eml`/`.zip`).
- `AudioTranscriber`: gli errori client 4xx (es. video senza traccia audio) **non
  vengono ritentati** (fail-fast).
- `AppConfig`: aggiungere un campo alla dataclass basta (load/save automatici).
- I partecipanti gruppo con jid **`@lid`** (numeri "privacy" di WhatsApp) non sono
  abbinabili alla rubrica e restano come numero.
