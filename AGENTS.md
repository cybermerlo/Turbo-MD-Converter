# AGENTS.md — Turbo MD Converter

Guida rapida per chi (umano o agente) lavora su questo repository.

## Cos'è
App desktop **Windows in Python puro** (CustomTkinter) che converte documenti
eterogenei in **Markdown**: PDF, immagini, audio/video, email (`.eml`/`.msg`),
archivi, firmati `.p7m` e **conversazioni WhatsApp**. Usa OCR (Google Gemini),
trascrizione audio (ElevenLabs Scribe v2, con diarization) ed estrazione strutturata opzionale
(LangExtract). Nessun runtime Node/JS.

## Avvio, test, build
- **Eseguire da sorgente**: `py main.py` (oppure `python main.py`)
- **Test**: `python -m unittest discover -s tests`
- **Build .exe + installer**: `python build_installer.py` (cx_Freeze + Inno Setup)
- **Config utente**: `%APPDATA%\OCRLangExtract\config.json` (chiavi API in chiaro)

## Architettura (cartelle)
- `main.py` — entry point GUI
- `gui/` — interfaccia: `app.py` (finestra principale), `frames/` (pannelli),
  `options_panel.py` (rail opzioni), `pipeline_event_handler.py` (eventi worker→UI),
  `theme.py` (stile paper+amber), `toast.py`, `resources.py` (path risorse + output)
- `pipeline/` — `processor.py` (`DocumentProcessor`: acquire→extract→write),
  `attachment_processor.py` (router file→testo), `email_sources.py` /
  `archive_sources.py` / `whatsapp_sources.py` (sorgenti), `rename_coordinator.py`
  (`RenameCoordinator`: rinomina LLM), `final_check.py` (QA finale LLM),
  `worker.py` (thread di lavoro), `events.py` / `models.py`, `constants.py`
- `ocr/` — `gemini_ocr.py`, `ocr_pipeline.py`, `page_analyzer.py`, `pdf_converter.py`,
  `audio_transcriber.py`, `video_describer.py` (descrizione visiva video)
- `extraction/` — wrapper LangExtract · `output/` — formatter MD/JSON + writer
- `config/` — `settings.py` (`AppConfig` dataclass + persistenza JSON atomica;
  i segreti vanno nel keyring, vedi sotto), `defaults.py` (prompt di default,
  `PRICING`, elenco modelli)
- `utils/` — `cost_tracker.py`, `file_renamer.py` (nome file via LLM),
  `media_duration.py` (durata video pure-python), `ffmpeg_tools.py` (rimozione
  traccia audio), `retry.py` (backoff), `updater.py` (auto-update),
  `secret_store.py` (segreti nel keyring/DPAPI), `text_utils.py`,
  `logging_config.py`
- `whatsapp/` — importazione conversazioni (vedi sotto)
- `vendor/adb/` — `adb.exe` + DLL impacchettati (necessari per WhatsApp)
- ffmpeg arriva da `imageio-ffmpeg` (bundle pip); nel build è in `ffmpeg/ffmpeg.exe`
- `tests/` — unittest

## Modello dati della pipeline
Ogni input è un `Path`; **ogni input → un file `.md`**.
`DocumentProcessor._acquire_text()` instrada per estensione: video→trascrizione
audio + descrizione visiva, audio→trascrizione, immagini/PDF→OCR, suffissi in
`DIRECT_READ_FORMATS`→lettura diretta (email, archivi, `.wachat`). Email e
WhatsApp **uniscono corpo + media in un unico testo** → un solo MD (vedi
`join_email_and_attachments` / `extract_whatsapp_parts`).

## Rinomina file (LLM)
Opzionale (`config.rename_files`). `RenameCoordinator` (`pipeline/rename_coordinator.py`)
orchestra la derivazione del nome via LLM (`utils/file_renamer.py`): da ogni testo
OCR genera un nome descrittivo. `rename_mode` ∈ {`md`,`pdf`,`both`}. Con
`rename_use_batch_context` la rinomina è **differita** a fine batch e usa il
contesto degli altri documenti (profili condivisi); `rename_use_user_context` +
`rename_user_context_text` guidano lo stile dei nomi.

## Check finale errori
Default-on (`config.final_error_check`). Dopo ogni batch, `pipeline/final_check.py`
fa **una** chiamata LLM di QA sul Markdown prodotto e segnala possibili errori OCR;
i file sospetti vengono marcati "warn" nella UI. Degrada in modo morbido se l'API
fallisce (`check_failed_technically`, nessun blocco della conversione).

## Trascrizione audio e identificazione interlocutori
La trascrizione audio/video usa **ElevenLabs Scribe v2** (`ocr/audio_transcriber.py`,
`speech_to_text.convert(model_id="scribe_v2", diarize=True)`), tariffata **a ora**
(`PRICING["scribe_v2"]["per_hour"]`, costo da `audio_duration_secs`). Le `words`
diventano turni per speaker (`segments_from_words`/`build_transcript`): testo piano
per un solo interlocutore, righe `[mm:ss] speaker_X: …` se più di uno. Per i **video**
si carica solo la traccia audio estratta a 16 kHz mono (`ffmpeg_tools.extract_audio_track`,
upload molto più leggero; fallback al file originale se ffmpeg manca).

Default-on (`config.identify_speakers`): se un file ha **più speaker**, il processor
emette `SpeakerDiarizationEvent` (chiave `input_path`, segue le rinomine). A fine
batch (`on_batch_complete`) l'app apre, in serie, `SpeakerIdentificationWindow`
(`gui/frames/speaker_id_window.py`) con spezzoni testo + audio (▶ estrae il tratto
via `ffmpeg_tools.extract_audio_segment`); i nomi scelti riscrivono l'`.md`
(`ocr/speaker_id.rewrite_transcript_in_md`). Tutto **dopo** il batch: non blocca
l'elaborazione.

## Descrizione visiva dei video
Un video (`VIDEO_EXTENSIONS`: `.mp4 .mov .m4v .mkv .webm .avi`) produce UN solo MD
con due sezioni separate: `## Trascrizione audio` (ElevenLabs) + `## Descrizione
visiva` (Gemini, riusa `ocr_model_id`). Opzionale via `config.video_describe`.
- **L'audio viene RIMOSSO prima dell'upload a Gemini** (`utils/ffmpeg_tools.strip_audio`,
  remux `-c copy -an`): altrimenti contamina la descrizione (il modello "sente" un
  cane e lo descrive a schermo anche se non inquadrato). Se ffmpeg manca, il visivo
  viene saltato (non si reintroduce l'audio).
- **Qualità per durata**: video ≤ `video_high_quality_max_min` min (def. 3) → HIGH,
  oltre → LOW (`VideoDescriber.resolution_for`).
- **Cap**: video > `video_max_duration_min` min (def. 20) → niente visivo, solo audio.
- **Override test** (env): `TURBOMD_VIDEO_MEDIA_RESOLUTION=low|medium|high` (forza la
  risoluzione), `TURBOMD_VIDEO_MAX_OUTPUT_TOKENS`.

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
- **Modalità output** (`config.output_mode`): `accanto` (di fianco al sorgente,
  default), `sottocartella` (in `output_subfolder_name` accanto al sorgente),
  `cartella` (cartella fissa `output_directory`; ripristinata a `accanto` a fine
  batch se `cartella_output_one_shot`).
- I subprocess adb usano `encoding="utf-8"`: l'output (rubrica, nomi) contiene
  caratteri non-ASCII/emoji e con il codec locale Windows (cp1252) andrebbe in crash.
- Le note vocali WhatsApp sono **`.opus`** (in `AUDIO_EXTENSIONS` e
  `AUDIO_MIME_TYPES` → `audio/ogg`). Anche `to_text()` ora trascrive l'audio
  (vale per allegati `.eml`/`.zip`).
- `AudioTranscriber`: gli errori client 4xx (es. video senza traccia audio) **non
  vengono ritentati** (fail-fast).
- `AppConfig`: aggiungere un campo alla dataclass basta (load/save automatici).
  I campi in `secret_store.SECRET_FIELDS` (chiavi API, chiave backup WhatsApp)
  sono **segreti**: `save_config` li mette nel keyring di sistema (Credential
  Manager/DPAPI su Windows) e scrive `""` nel JSON; `load_config` li rilegge dal
  keyring (priorità: `.env` > keyring > JSON-legacy). Senza keyring (o con
  `TURBOMD_DISABLE_KEYRING=1`) ricadono nel JSON in chiaro. I test usano la env
  var o un backend fittizio per restare deterministici.
- Durante un batch `OptionsPanel.set_running(True)` **blocca** toggle, menu e
  radio delle opzioni: cambiarli a metà elaborazione muterebbe la `config` che il
  worker sta leggendo. `set_running(False)` ripristina via `_refresh_states()`.
- La geometria della finestra (`config.window_geometry`) è salvata alla chiusura
  (`_on_close`) e ripristinata all'avvio, mantenendola visibile sullo schermo.
- WhatsApp moderno identifica molti contatti con un **LID** (`…@lid`, "numero
  privacy") al posto del numero. `msgstore_reader._resolve_jid()` lo traduce nel
  numero reale tramite la tabella **`jid_map`** (LID→`…@s.whatsapp.net`) prima di
  cercare in rubrica — vale sia per le chat 1:1 sia per i mittenti nei gruppi.
  I LID senza voce in `jid_map` (contatti a privacy totale, mai contattati "a
  numero") restano non risolvibili e si mostrano come numero grezzo.
