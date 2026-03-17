"""Default prompts, constants, and schema preset definitions."""

DEFAULT_OCR_PROMPT = """Sei un assistente OCR specializzato in documenti legali italiani.
Analizza questa immagine di una pagina di un documento legale e trascrivi TUTTO il testo visibile in modo preciso e completo.

Regole:
- Mantieni la formattazione originale (paragrafi, elenchi, rientri)
- Trascrivi numeri, date, codici e riferimenti normativi esattamente come appaiono
- Preserva maiuscole/minuscole, accenti e punteggiatura
- Se una parola e' illeggibile, indica [illeggibile]
- Non aggiungere interpretazioni o commenti
- Restituisci SOLO il testo trascritto"""

DEFAULT_RENAME_PROMPT = """\
Sei un assistente per l'archiviazione documenti di uno studio legale.
Analizza il testo OCR qui sotto e rispondi SOLO con un oggetto JSON con due campi:

1. "data": La data in cui il documento è stato redatto, firmato, emesso o inviato.
   - Formato: YYYYMMDD  (es. "20260225")
   - Cerca la data del documento stesso: data di redazione, firma, emissione, \
apertura fascicolo, rilascio, chiusura verbale, ecc.
   - NON usare date di nascita, date di eventi descritti nel documento, scadenze \
future o qualsiasi altra data incidentale.
   - Se non riesci a determinare con certezza la data del documento, restituisci \
"00000000".

2. "descrizione": Una breve descrizione del documento adatta come nome file \
(massimo 60 caratteri).
   - Descrivi il contenuto del documento in modo che sia immediatamente \
riconoscibile leggendo solo il nome del file.
   - Usa maiuscole appropriate (non tutto maiuscolo, non tutto minuscolo).
   - Non usare caratteri non ammessi nei nomi file: < > : " / \\\\ | ? *

Rispondi SOLO con il JSON, nessun altro testo.

Testo OCR:
---
{ocr_sample}
---
"""

# Available OCR models
AVAILABLE_OCR_MODELS = [
    "gemini-3-flash-preview",
    "gemini-3.1-flash-lite-preview",
    "gemini-2.5-flash",
]

# Page separator used when combining OCR results
PAGE_SEPARATOR = "\n\n--- Pagina {page_num} ---\n\n"

# Gemini API pricing (per 1M tokens, USD)
PRICING = {
    "gemini-3-flash-preview": {
        "input_per_1m": 0.50,
        "output_per_1m": 3.00,
    },
    "gemini-3.1-flash-lite-preview": {
        "input_per_1m": 0.25,
        "output_per_1m": 1.50,
    },
    "gemini-2.5-flash": {
        "input_per_1m": 0.15,
        "output_per_1m": 0.60,
    },
}

# Available schema preset names
SCHEMA_PRESET_NAMES = ["full_legal", "parties_dates", "invoice", "estratto_conto", "custom"]
