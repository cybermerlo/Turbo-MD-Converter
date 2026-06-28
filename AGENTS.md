# AGENTS.md — Turbo MD Converter

Guida rapida per chi (umano o agente) lavora su questo repository.

## Cos'è
App desktop **Windows in Python puro** (CustomTkinter) che converte documenti
eterogenei in **Markdown**: PDF, immagini, audio/video, email (`.eml`/`.msg`),
documenti Office (`.docx`/`.doc`/`.rtf`/`.odt`), fogli di calcolo
(`.xlsx`/`.ods`/`.csv`), presentazioni (`.pptx`/`.odp`), `.xml`, archivi e
firmati `.p7m`. Usa
OCR (Google Gemini), trascrizione audio (ElevenLabs Scribe v2, con diarization)
ed estrazione strutturata opzionale (LangExtract). Nessun runtime Node/JS.

## Avvio, test, build
- **Eseguire da sorgente**: `py main.py` (oppure `python main.py`)
- **Test**: `python -m unittest discover -s tests`
- **Build .exe + installer**: `python build_installer.py` (cx_Freeze + Inno Setup)
- **Config utente**: `%APPDATA%\OCRLangExtract\config.json` (le chiavi API stanno
  nel keyring di sistema, vedi sotto)

## Architettura (cartelle)
- `main.py` — entry point GUI
- `gui/` — interfaccia: `app.py` (finestra principale), `frames/` (pannelli),
  `options_panel.py` (rail opzioni), `pipeline_event_handler.py` (eventi worker→UI),
  `theme.py` (stile paper+amber), `toast.py`, `resources.py` (path risorse + output)
- `pipeline/` — `processor.py` (`DocumentProcessor`: acquire→extract→write),
  `attachment_processor.py` (router file→testo), `text_extractors.py`
  (docx/doc/xml/html/rtf→testo), `email_sources.py` / `archive_sources.py`
  (sorgenti), `rename_coordinator.py` (`RenameCoordinator`: rinomina LLM),
  `final_check.py` (QA finale LLM), `worker.py` (thread di lavoro),
  `events.py` / `models.py`, `constants.py`
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
  `logging_config.py`, `system.py` (helper OS condivisi: `no_window_kwargs`,
  `open_with_system`)
- ffmpeg arriva da `imageio-ffmpeg` (bundle pip); nel build è in `ffmpeg/ffmpeg.exe`
- `tests/` — unittest

## Modello dati della pipeline
Ogni input è un `Path`; **ogni input → un file `.md`**.
`DocumentProcessor._acquire_text()` instrada per estensione: video→trascrizione
audio + descrizione visiva, audio→trascrizione, immagini/PDF→OCR, suffissi in
`DIRECT_READ_FORMATS`→lettura diretta (email, archivi, `.docx`/`.doc`, fogli di
calcolo `.xlsx`/`.ods`/`.csv`, presentazioni `.pptx`/`.odp`, `.odt`, `.xml`,
`.rtf`, `.html`, `.p7m`). Le email **uniscono corpo + allegati in un unico
testo** → un solo MD (vedi `join_email_and_attachments`).
`AttachmentProcessor.to_text()` è **ricorsivo**: allegati annidati (una `.eml`
inoltrata dentro un'altra `.eml`, archivi dentro archivi) vengono espansi a
testo invece di essere saltati.

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

## Formati a lettura diretta (no OCR)
`pipeline/text_extractors.py` estrae il testo dai formati non-OCR cablati in
`pipeline/attachment_processor.py` (sia come input top-level via `read_text_file`,
sia come allegato via `to_text`): `.docx` (python-docx), `.doc` legacy Word
97-2003 (`extract_doc_text`, parser pure-python su `olefile` — gia' nel bundle
come dipendenza di `extract-msg` — che legge lo stream `WordDocument`+piece table;
se cifrato/danneggiato solleva un errore chiaro che invita a risalvare in
`.docx`/`.rtf`), `.rtf` (striprtf), `.html`/`.htm` (BeautifulSoup), `.xml`
(`extract_xml_text`: ElementTree→BeautifulSoup→raw) e `.txt`/`.md` (lettura
diretta). **Fogli di calcolo e presentazioni** (`extract_xlsx_text` su openpyxl
in `data_only` → tabelle Markdown con date/numeri formattati; `extract_ods_text`,
`extract_odt_text`, `extract_odp_text`, `extract_pptx_text` sono pure-python
zip+xml con ElementTree; `extract_csv_text` su `csv` stdlib con rilevamento del
delimitatore). I fogli diventano una tabella Markdown per foglio, le presentazioni
una sezione `## Diapositiva N` per slide; un helper condiviso `_rows_to_markdown`
rifila righe/colonne vuote ed esegue l'escape di `|`. Aggiungere un formato =
nuova `extract_*` + suffisso in `DIRECT_READ_FORMATS`, `SUPPORTED_EXTENSIONS`, i
due dispatch e (cosmetico) `gui/theme.py EXT_TO_BADGE`.

## Convenzioni e gotcha
- **UI e commenti in italiano.**
- **Modalità output** (`config.output_mode`): `accanto` (di fianco al sorgente,
  default), `sottocartella` (in `output_subfolder_name` accanto al sorgente),
  `cartella` (cartella fissa `output_directory`; ripristinata a `accanto` a fine
  batch se `cartella_output_one_shot`).
- Le note vocali `.opus` sono in `AUDIO_EXTENSIONS` e `AUDIO_MIME_TYPES`
  (→ `audio/ogg`). `to_text()` trascrive l'audio anche negli allegati (`.eml`/`.zip`).
- `AudioTranscriber`: gli errori client 4xx (es. video senza traccia audio) **non
  vengono ritentati** (fail-fast).
- `AppConfig`: aggiungere un campo alla dataclass basta (load/save automatici).
  I campi in `secret_store.SECRET_FIELDS` (chiavi API) sono **segreti**:
  `save_config` li mette nel keyring di sistema (Credential
  Manager/DPAPI su Windows) e scrive `""` nel JSON; `load_config` li rilegge dal
  keyring (priorità: `.env` > keyring > JSON-legacy). Senza keyring (o con
  `TURBOMD_DISABLE_KEYRING=1`) ricadono nel JSON in chiaro. I test usano la env
  var o un backend fittizio per restare deterministici.
- Durante un batch `OptionsPanel.set_running(True)` **blocca** toggle, menu e
  radio delle opzioni: cambiarli a metà elaborazione muterebbe la `config` che il
  worker sta leggendo. `set_running(False)` ripristina via `_refresh_states()`.
- La geometria della finestra (`config.window_geometry`) è salvata alla chiusura
  (`_on_close`) e ripristinata all'avvio, mantenendola visibile sullo schermo.
