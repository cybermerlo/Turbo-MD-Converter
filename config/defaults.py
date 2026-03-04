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

# Available OCR models
AVAILABLE_OCR_MODELS = [
    "gemini-3-flash-preview",
    "gemini-3.1-flash-lite-preview",
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
SCHEMA_PRESET_NAMES = ["full_legal", "parties_dates", "invoice", "estratto_conto", "none", "custom"]
