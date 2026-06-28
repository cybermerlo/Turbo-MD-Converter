# AGENTS.md — Turbo MD Converter

Guida rapida per chi (umano o agente) lavora su questo repository.

## Cos'è
App desktop **Windows in Python puro** (CustomTkinter) che converte documenti
eterogenei in **Markdown**: PDF, immagini, audio/video, email (`.eml`/`.msg`),
documenti Office (`.docx`/`.doc`/`.rtf`), `.xml`, archivi e firmati `.p7m`. Usa
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
`DIRECT_READ_FORMATS`→lettura diretta (email, archivi, `.docx`/`.doc`, `.xml`,
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
diretta). Aggiungere un formato = nuova `extract_*` + suffisso in
`DIRECT_READ_FORMATS`, `SUPPORTED_EXTENSIONS`, i due dispatch e (cosmetico)
`gui/theme.py EXT_TO_BADGE`.

## Import chat da WhatsApp Desktop (branch `claude/whatsapp-web-import`)
Reimporta le chat **leggendo il DB locale dell'app ufficiale WhatsApp Desktop**
(build WebView2, pacchetto `5319275A.WhatsAppDesktop_*`). **Nessuna connessione,
nessun rischio ban**: si decifra e si legge solo ciò che è già su disco.
Vincoli di prodotto fissati dall'utente: **niente export manuale**, **rischio
ban inaccettabile**, va bene rinunciare ai messaggi più vecchi di ~1 mese.

**Portabilità**: funziona su *qualunque* PC dove WhatsApp Desktop è installato e
loggato, ma ognuno legge **solo i propri dati locali** — l'ODUID deriva dal
`RandomSeed` del TPM (per-macchina) e DPAPI-NG usa `LOCAL=user` (per-utente).
Non legge PC remoti/altrui. Serve la build **WebView2** (≥ dic 2025), non la
vecchia. "WhatsApp Web" nel browser ≠ "WhatsApp Desktop" (app installata): si
legge l'app installata.

### Stato attuale
- **v2 (mittenti + nomi gruppo/contatti): FUNZIONA** end-to-end, **testato in GUI
  dall'utente** (16 test verdi). Importa testo + timestamp + **mittente per
  messaggio** (io / contatto / membro del gruppo), con **nomi dei gruppi** veri e
  nomi contatti ricchi. Raggruppato per giorno. **Non** importa i media.
- **v1 (solo testo)** resta il fallback automatico se l'IndexedDB è illeggibile;
  in GUI è anche un'opzione esplicita (checkbox "Includi mittenti" off = veloce).
- **Performance (chiave)**: indice IndexedDB e store decifrato **condivisi a livello
  di processo** (riusati tra finestre): **~78s una sola volta per avvio app**, poi
  riaprire la finestra e creare MD è **istantaneo**; una nuova chat ~1-2s (scoped).
  L'indice si carica **solo alla creazione MD** (non all'apertura finestra) → la
  navigazione resta reattiva. **Cache su disco** (build completo in background al
  primo uso) → anche tra **riavvii** dell'app l'indice si carica in ~0.3s (resta solo
  la decifratura ~15s), se il DB non è cambiato. Vedi "Timing" sotto.

### Architettura
- `whatsapp/desktop_crypto.py` — catena di decifratura → `decrypt_databases()`
  ritorna `DecryptedStore(workdir, messages_db, contacts_db)` (file SQLite **in
  chiaro standard**) con `.cleanup()`. Windows-only. Errori → `WhatsAppDesktopError`.
  `source_fingerprint()` = impronta dei DB sorgente cifrati (per la cache decifratura).
- `whatsapp/desktop_indexeddb.py` — apre l'**IndexedDB** del WebView2 (lettore
  vendorizzato) su una **copia** dei file. `get_index()` ritorna un `WhatsAppIndex`
  **condiviso a livello di processo** (riusato finché i `.ldb` non cambiano; chiuso
  via `atexit`). `open_index()` è il costruttore: estrae nomi (`group_subjects`,
  `name_by_jid`, `lid_to_phone`) e prepara i **mittenti scoped** (`_ScopedSenders`:
  `senders_for_chat(chat_id)` filtra le chiavi `message` per `chatJid` PRIMA della
  deserializzazione V8 → ~1-2s/chat invece di ~150s per tutto; tiene il wrapper
  aperto). Fallback full-scan se gli interni ccl mancano. **Cache su disco**: hit →
  carica la mappa completa da `wa_cache/index.json` senza leggere il LevelDB; miss →
  scoped + build completo in background (`_spawn_cache_build`) che scrive la cache.
  Robusto: in errore None (degrado a solo testo).
- `whatsapp/_vendor/ccl_chromium_reader/` — **`ccl_chromium_reader` vendorizzato**
  (sottoinsieme IndexedDB) + `ccl_simplesnappy`. MIT. **Non è su PyPI** (solo
  GitHub) e una dep git-only non è impacchettabile nell'.exe → vendorizzata. Vedi il
  suo `README.md` per provenienza/patch (incl. `time.sleep(0)` in `_cache_records`
  per non bloccare la UI). Niente `Brotli` (non serve per IndexedDB).
- `whatsapp/desktop_reader.py` — `WhatsAppDesktopReader` (context manager:
  `list_chats`, `read_messages`, `ensure_index(progress)`) + `build_markdown`.
  `open()` ottiene lo **store decifrato condiviso** (`_get_shared_store`: ri-decifra
  solo se il sorgente è cambiato) + nomi da `contacts.db`. `ensure_index` usa
  `get_index` (condiviso). `read_messages` arricchisce ogni messaggio col mittente
  via `senders_for_chat`. **`close()` NON chiude store/indice** (condivisi a livello
  app). Risoluzione nomi: IndexedDB → `contacts.db`. Log di timing in INFO (`WA:` / `WA-idx:`).
- `gui/frames/whatsapp_import_window.py` — `WhatsAppImportWindow(master,
  on_chat_ready)`: apertura **veloce e reattiva** (decifra + lista chat); l'indice
  mittenti si carica **solo al "Crea MD"** (se la checkbox "Includi mittenti" è on),
  con barra di avanzamento non bloccante. Filtro periodo/testo. "Crea MD" → scrive in
  `app_capture_dir()` → callback aggiunge agli input. Ogni apertura crea una NUOVA
  finestra/reader, ma store+indice condivisi rendono le riaperture istantanee.
  Agganciata da `gui/app.py` via `gui/frames/input_frame.py`.
- `tools/wa_export.py` — CLI `list` / `export` (`--no-senders` = solo testo veloce).
  `tools/wa_indexeddb_spike.py` — esplora lo schema IndexedDB (usa il vendor).
  `tools/wa_indexeddb_probe.py` / `wa_desktop_probe.py` — diagnostici read-only.
  `tools/wa_desktop_decrypt_spike.py` — spike decifratura completo.
- Dipendenze: `cryptography` (AES; fallback Cryptodome/Crypto). In `setup_cxfreeze.py`
  sono inclusi `whatsapp`, `cryptography` e i sottopacchetti `whatsapp._vendor.*`.
- Piano/ricerca: `docs/plans/whatsapp-desktop-import.md`.

### Catena di decifratura (validata sul PC dell'utente)
`RandomSeed` (registro `HKLM\SYSTEM\CurrentControlSet\Services\TPM\ODUID`,
leggibile **senza admin**) → `ODUID = SHA256(UTF-16LE("cv1g1gv") || RandomSeed)`
→ DPAPI-NG: `NCryptProtectSecret(staticBytes, "LOCAL=user")[:32]` = sessionDBSecret
→ decifra `session.db` → **clientKey** (48B; oracolo: `SHA1(clientKey).hex().upper()`
== nome cartella `sessions/<...>`) → dbKey (PBKDF2-HMAC-SHA256(clientKey, salt=ODUID,
10000)=auxKey; IV analogo; `dbKey = AES-256-CBC-PKCS7(staticBytes, auxKey, IV)[:32]`)
→ decifra `nativeSettings.db` → chiavi tipo1/tipo2 → `genericStorage.db` (messaggi)
e `contacts.db`. **Cifratura per-pagina**: AES-256-OFB, page=4096B,
`IV = struct.pack("<I", pageNumber) || page[-12:]`; dopo il decrypt ripristina i
byte `[16:24]` dall'originale. WAL: header 32B as-is, frame = 24B (pageNumber =
big-endian primi 4B) + 4096B. `staticBytes = 23a7f19c11e5bd784235c96f85d24913`.

### Mittenti, nomi gruppo e contatti (v2) — come funziona (validato sui dati reali)
- **`genericStorage.db`** (SQLite decifrato) è la **cache di ricerca full-text**:
  `message(rowid, id, chatId, timestamp, text)`. Ha il **testo** ma NON il mittente,
  NON `fromMe`, NON i media. `id` è un docid (`999999231`…).
- **L'IndexedDB del WebView2** (Chromium LevelDB + serializzazione V8, ≈323 MB:
  `...\IndexedDB\https_web.whatsapp.com_0.indexeddb.leveldb` + `.blob`) ha il resto.
  DB rilevante: **`model-storage`** (103 object store). Store usati:
  - **`message`** → `rowId`, `id` (prefisso `true_`/`false_` = **fromMe**),
    `author` (`{server,user,_serialized}` = **mittente nei gruppi**, un `@lid`), `t`.
    Il **corpo è cifrato** in `msgRowOpaqueData` (`{_data,iv,_keyId,_scheme}`,
    chiave in `wawc_db_enc`) → **non** lo leggiamo: il testo arriva da genericStorage.
  - **`group-metadata`** → `subject` = **nome del gruppo**.
  - **`contact`** → `id`(@lid) → `name`/`shortName`/`pushname` + `phoneNumber`(@c.us).
  - **`out-contact`** → `id`(@s.whatsapp.net) → `fullName`.
- **JOIN esatto e validato**: `genericStorage.message.id == IndexedDB.message.rowId`
  (264.947/264.947 = **100%**, timestamp coerente 100%). Niente join fragile per
  timestamp. Quindi: **testo+chat+ts da genericStorage** ⨝ **fromMe+author da
  IndexedDB** per `rowId`. Mittente: DM → io/contatto da `fromMe`; gruppi → `author`
  (@lid) risolto a nome via `contact` (e `lid→phoneNumber→nome`); fallback numero.
- **Lettore**: `ccl_chromium_reader` **vendorizzato** (vedi sopra). Si legge una
  **COPIA** dei file (DB live bloccato). Formato `chatId` coerente tra le due
  sorgenti (DM 381/381, gruppi 108/108) → la risoluzione funziona per entrambi.
- **Timing reale** (PC utente, ~265k messaggi), misurato in GUI: decifratura ~15s;
  apertura wrapper IndexedDB ~60s (legge ~2,2M record raw, `.ldb` 323 MB); nomi ~1.6s;
  **scoped per-chat ~1-2s**. **1ª volta per avvio app ~78s**; poi store+indice
  **condivisi in memoria** → riaperture finestra e nuove creazioni MD **istantanee**.
- **Cache su disco** (`%APPDATA%\OCRLangExtract\wa_cache\index.json`, ~7 MB, keyed
  sul fingerprint dei `.ldb`): al primo uso, dopo lo scoped, un thread daemon
  costruisce la mappa mittenti COMPLETA (riusa il wrapper già aperto: +~150s, in
  background, non blocca) e la salva. Ai **riavvii** successivi dell'app, se i `.ldb`
  non sono cambiati, l'indice si carica da disco in **~0.3s SENZA rileggere il
  LevelDB** → l'unico costo resta la decifratura (~15s). `_load_senders`/scoped/cache
  producono `Sender` **canonici e identici** (author solo per messaggi altrui).
- **Invalidazione**: store ri-decifrato se cambia `source_fingerprint` (sorgenti
  cifrati + `-wal`); indice/cache ricostruiti se cambiano i `.ldb` (flush/compaction
  — non a ogni scrittura, che va nel `.log`). I messaggi più recenti ancora nel
  `.log` possono mancare di mittente finché non compattati (degradano a solo testo).
- **Media**: differiti (best-effort); i riferimenti ci sono (`directPath`/`mediaKey`).

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
