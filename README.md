# Turbo MD Converter

App desktop **Windows** (Python + CustomTkinter) che converte documenti eterogenei
in **Markdown**: PDF, immagini, audio/video, email (`.eml`/`.msg`), documenti
Office (`.docx`/`.doc`/`.rtf`), fogli di calcolo (`.xlsx`/`.ods`/`.csv`),
presentazioni (`.pptx`/`.odp`), `.odt`, `.xml`, archivi (`.zip`/`.7z`/`.tar.*`) e
firmati `.p7m`.

Usa **Google Gemini** per l'OCR e la descrizione visiva dei video, **ElevenLabs
Scribe v2** per la trascrizione audio (con riconoscimento degli interlocutori) ed
(opzionale) **LangExtract** per l'estrazione strutturata. Regola: **ogni input →
un file `.md`**.

## Funzionalità principali

- **OCR** di PDF e immagini con rilevamento del testo nativo (salta l'OCR quando
  il testo è già selezionabile).
- **Audio/video** → trascrizione; i video producono un solo MD con
  `## Trascrizione audio` + `## Descrizione visiva`.
- **Email e archivi**: corpo + allegati uniti (o separati) in Markdown.
- **Documenti Office e XML**: `.docx`, `.doc` (Word 97-2003 legacy), `.rtf`,
  `.odt` e `.xml` letti direttamente, senza OCR.
- **Fogli di calcolo e presentazioni**: `.xlsx`/`.xlsm`, `.ods`, `.csv`/`.tsv`,
  `.pptx` e `.odp` convertiti in tabelle/sezioni Markdown, senza OCR.
- **Rinomina automatica** dei file via LLM e **check finale errori** (QA) opzionali.
- **Auto-aggiornamento** dall'ultima release GitHub.

## Installazione (utente)

Scarica l'installer più recente (`TurboMDConverter_Setup_*.exe`) dalle
[release di GitHub](../../releases) ed eseguilo.

## Esecuzione da sorgente

```bash
pip install -r requirements.txt
python main.py
```

## Configurazione

Le chiavi API si inseriscono in **Impostazioni**. I **segreti** (chiavi API)
vengono salvati nel **Credential Manager di Windows**
(DPAPI) quando disponibile; le altre impostazioni in
`%APPDATA%\OCRLangExtract\config.json`. Se il keyring non è disponibile (o è
disabilitato con `TURBOMD_DISABLE_KEYRING=1`), i segreti ricadono nel
`config.json` come in passato. In alternativa, in sviluppo, si possono mettere le
chiavi in un file `.env` (vedi [`.env.example`](.env.example)):

| Chiave | Uso |
| --- | --- |
| `GEMINI_API_KEY` | OCR e descrizione video (obbligatoria) |
| `ELEVENLABS_API_KEY` | Trascrizione audio/note vocali (Scribe v2) |
| `LANGEXTRACT_API_KEY` | Estrazione strutturata (default = Gemini) |

## Test

```bash
python -m unittest discover -s tests
```

## Altra documentazione

- [AGENTS.md](AGENTS.md) — architettura e modello dati della pipeline.
- [BUILD_README.md](BUILD_README.md) — build dell'installer Windows (cx_Freeze + Inno Setup).
