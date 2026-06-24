"""Default prompts, constants, and schema preset definitions."""

DEFAULT_TRANSCRIPTION_PROMPT = """Trascrivi fedelmente e integralmente l'audio fornito.

Regole:
- Trascrivi ogni parola pronunciata, inclusi riempitivi ed esitazioni
- Mantieni la punteggiatura e la struttura dei periodi
- Se ci sono più interlocutori, separa gli interventi con un a capo
- Se una parola è incomprensibile, indica [incomprensibile]
- Non aggiungere riassunti, commenti o interpretazioni
- Restituisci SOLO il testo trascritto"""

DEFAULT_VIDEO_DESCRIPTION_PROMPT = """Basandoti ESCLUSIVAMENTE sui fotogrammi (le immagini) di questo video, descrivi in modo oggettivo e fedele ciò che si VEDE, in prosa scorrevole.

Regola fondamentale — IGNORA TOTALMENTE L'AUDIO:
- Descrivi un elemento SOLO se è effettivamente visibile nei fotogrammi.
- Se percepisci un suono la cui fonte NON è inquadrata (es. un cane che abbaia, una voce fuori campo, musica, un clacson, applausi), NON menzionarlo e NON dedurne la presenza visiva: per questo compito quel suono NON esiste. Esempio: se si sente un cane ma nessun cane appare a schermo, NON scrivere che c'è un cane.
- Nel dubbio se un elemento sia visibile oppure solo udibile, NON includerlo.

Altre regole:
- Descrivi persone, oggetti, luoghi, azioni, scene e testo realmente inquadrati.
- Procedi in ordine cronologico, descrivendo l'evolversi delle scene in paragrafi discorsivi.
- NON usare timestamp né elenchi puntati: scrivi un testo continuo.
- Se compare testo leggibile (cartelli, documenti, sottotitoli, watermark), riportalo tra "virgolette".
- Descrivi oggettivamente, senza interpretare intenzioni, emozioni o significati.
- Non aggiungere riassunti finali, commenti o opinioni.
- Restituisci SOLO la descrizione, in italiano."""

DEFAULT_OCR_PROMPT = """Sei un assistente OCR specializzato in documenti legali italiani.
Analizza questa immagine di una pagina di un documento legale e trascrivi TUTTO il testo visibile in modo preciso e completo.

Regole:
- Mantieni la formattazione originale (paragrafi, elenchi, rientri)
- Trascrivi numeri, date, codici e riferimenti normativi esattamente come appaiono
- Preserva maiuscole/minuscole, accenti e punteggiatura
- Se una parola e' illeggibile, indica [illeggibile]
- Non aggiungere interpretazioni o commenti
- Restituisci SOLO il testo trascritto"""

IMAGE_HANDLING_INSTRUCTION = """

---
ISTRUZIONE AGGIUNTIVA — GESTIONE ELEMENTI VISIVI (questa regola PREVALE su qualsiasi istruzione precedente che ti dica di restituire solo testo o di non aggiungere commenti):

Se nella pagina sono presenti elementi visivi non testuali (foto, immagini, illustrazioni, grafici, diagrammi, loghi, firme autografe, timbri, sigilli, codici a barre, QR code, schemi, mappe, ecc.), inseriscili nel flusso del testo — nella posizione esatta in cui appaiono nella pagina — usando ESATTAMENTE questo formato su una propria riga:

[IMMAGINE: breve descrizione oggettiva dell'elemento, 1-2 frasi]

Esempi:
- [IMMAGINE: foto di un gattino bianco e arancione che guarda verso la camera]
- [IMMAGINE: logo aziendale "ACME S.r.l." in alto a sinistra della pagina]
- [IMMAGINE: firma autografa illeggibile in calce]
- [IMMAGINE: timbro tondo con scritta "COMUNE DI MILANO - PROTOCOLLO"]
- [IMMAGINE: grafico a barre che mostra fatturato trimestrale crescente]

Descrivi in modo oggettivo, senza interpretare o commentare il significato dell'immagine. Non aggiungere il marker per elementi puramente decorativi (righe orizzontali, separatori, sfondi)."""

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

# Available audio transcription models
AVAILABLE_AUDIO_MODELS = [
    "voxtral-mini-2602",
    "voxtral-mini-latest",
    "voxtral-small-latest",
]

# Available OCR models (default first)
DEFAULT_OCR_MODEL = "gemini-3.1-flash-lite"

AVAILABLE_OCR_MODELS = [
    DEFAULT_OCR_MODEL,
    "gemini-3-flash-preview",
    "gemini-2.5-flash",
]


def normalize_ocr_model(model_id: str) -> str:
    """Return a supported OCR model id, falling back to the default."""
    if model_id in AVAILABLE_OCR_MODELS:
        return model_id
    return DEFAULT_OCR_MODEL

DEFAULT_FINAL_CHECK_PROMPT = """\
Sei un revisore di qualità per output OCR/testo estratto da documenti.
Analizza i file Markdown convertiti qui sotto e verifica se contengono errori \
o segnali di conversione fallita.

Cerca in particolare:
- Messaggi di errore API o quota (es. "API key invalid", "quota exceeded", \
"you exceeded your current quota", "RECITATION", "resource exhausted", \
"permission denied", "billing")
- Testo troncato o incompleto (frasi interrotte a metà, paragrafi che finiscono \
improvvisamente, separatori di pagina seguiti da contenuto assente)
- Placeholder OCR sospetti in massa (molte occorrenze di [illeggibile], blocchi \
vuoti, pagine senza testo)
- Encoding corrotto o caratteri illeggibili diffusi
- Risposte del modello al posto della trascrizione (es. "Mi dispiace", \
"non posso aiutarti", "I cannot", rifiuti o disclaimer)
- Incoerenze strutturali gravi (es. un solo documento con metà contenuto \
manifestamente mancante)

Per ogni problema trovato, indica il nome file interessato (come nell'intestazione \
--- FILE: ... ---), un tipo breve e una descrizione concisa.

Rispondi SOLO con un oggetto JSON valido:
{{
  "passed": true/false,
  "issues": [
    {{"file": "nomefile.md", "type": "tipo_breve", "description": "descrizione"}}
  ]
}}

Imposta "passed": true SOLO se non trovi problemi significativi.
Se non ci sono problemi, restituisci "issues": [].

File convertiti:
---
{md_documents}
---
"""

# Page separator used when combining OCR results
PAGE_SEPARATOR = "\n\n--- Pagina {page_num} ---\n\n"

# Gemini API pricing (per 1M tokens, USD)
PRICING = {
    "gemini-3-flash-preview": {
        "input_per_1m": 0.50,
        "output_per_1m": 3.00,
    },
    "gemini-3.1-flash-lite": {
        "input_per_1m": 0.25,
        "output_per_1m": 1.50,
    },
    "gemini-2.5-flash": {
        "input_per_1m": 0.30,
        "output_per_1m": 2.50,
    },
    "voxtral-mini-2602": {
        "input_per_1m": 0.10,
        "output_per_1m": 0.30,
    },
    "voxtral-mini-latest": {
        "input_per_1m": 0.10,
        "output_per_1m": 0.30,
    },
    "voxtral-small-latest": {
        "input_per_1m": 0.10,
        "output_per_1m": 0.30,
    },
}

# Available schema preset names
SCHEMA_PRESET_NAMES = [
    "full_legal",
    "parties_dates",
    "invoice",
    "estratto_conto",
    "studi_settore_sp",
    "custom",
]
