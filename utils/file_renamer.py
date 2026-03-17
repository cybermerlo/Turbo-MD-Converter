"""Derive a descriptive filename from extraction results (zero additional LLM calls)."""

import logging
import re
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

# Italian month names -> month number
_ITALIAN_MONTHS = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4,
    "maggio": 5, "giugno": 6, "luglio": 7, "agosto": 8,
    "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
}

# Ordered list of (pattern_to_search, label_to_use) for known Italian document types.
# Patterns are matched case-insensitively against the first part of the OCR text.
# More specific / higher-priority patterns must come before their sub-phrases.
_DOCUMENT_TYPE_PATTERNS: list[tuple[str, str]] = [
    # Legal acts - most specific first
    (r"comparsa\s+di\s+costituzione\s+e\s+risposta", "Comparsa di Costituzione e Risposta"),
    (r"comparsa\s+di\s+costituzione", "Comparsa di Costituzione"),
    (r"comparsa\s+conclusionale", "Comparsa Conclusionale"),
    (r"atto\s+di\s+citazione", "Atto di Citazione"),
    (r"opposizione\s+a\s+decreto\s+ingiuntivo", "Opposizione a Decreto Ingiuntivo"),
    (r"ricorso\s+per\s+decreto\s+ingiuntivo", "Ricorso per Decreto Ingiuntivo"),
    (r"decreto\s+ingiuntivo", "Decreto Ingiuntivo"),
    (r"\bopposizione\b", "Opposizione"),
    (r"\bricorso\b", "Ricorso"),
    (r"memoria\s+difensiva", "Memoria Difensiva"),
    (r"\bmemoria\b", "Memoria"),
    (r"\bsentenza\b", "Sentenza"),
    (r"\bordinanza\b", "Ordinanza"),
    (r"\bprecetto\b", "Precetto"),
    (r"\bpignoramento\b", "Pignoramento"),
    # Diffida before contratto: a "diffida" doc often also mentions "contratto"
    (r"\bdiffida\b", "Diffida"),
    (r"\bprocura\b", "Procura"),
    (r"atto\s+notarile", "Atto Notarile"),
    # Police / criminal law
    (r"ricezione\s+querela", "Querela"),
    (r"\bquerela\b", "Querela"),
    (r"denuncia.{0,5}querela", "Denuncia-Querela"),
    (r"\bdenuncia\b", "Denuncia"),
    (r"verbale\s+di\s+pronto\s+soccorso", "Verbale di Pronto Soccorso"),
    (r"cartella\s+clinica\s+di\s+ps", "Verbale di Pronto Soccorso"),
    (r"certificazione\s+(?:medica\s+)?(?:di\s+)?infortunio", "Certificazione Infortunio INAIL"),
    (r"certificat[oo]\s+inail", "Certificazione INAIL"),
    (r"referto\s+(?:di\s+)?(?:autorit|pronto)", "Referto"),
    (r"\breferto\b", "Referto"),
    # Hearings / verbali
    (r"verbale\s+di\s+udienza", "Verbale di Udienza"),
    (r"verbale\s+d['']udienza", "Verbale di Udienza"),
    # Court/expert reports
    (r"elaborato\s+peritale", "Elaborato Peritale"),
    (r"\bperizia\b", "Perizia"),
    (r"relazione\s+tecnica", "Relazione Tecnica"),
    # Medical / insurance
    (r"certificato\s+medico", "Certificato Medico"),
    (r"cartella\s+clinica", "Cartella Clinica"),
    # Commercial documents
    (r"distinta\s+bonific", "Distinta Bonifico"),
    (r"\bbonifico\b", "Bonifico"),
    (r"documento\s+di\s+trasporto|bolla\s+di\s+consegna|\bddt\b", "DDT"),
    (r"\bpreventivo\b", "Preventivo"),
    (r"conferma\s+(d[''])?ordine|ordine\s+di\s+acquisto", "Ordine"),
    (r"\bfattura\b", "Fattura"),
    (r"estratto\s+conto", "Estratto Conto"),
    (r"\bdichiarazione\b", "Dichiarazione"),
    (r"\bvisura\b", "Visura"),
    (r"\bcontratto\b", "Contratto"),
    (r"\bpec\b", "PEC"),
]

# Lines matching these patterns are skipped when looking for a title fallback.
# Split into case-sensitive and case-insensitive parts to avoid Python 3.11
# restrictions on inline (?i) flags in alternations.
_SKIP_LINE_RE = re.compile(r"^\s*$|@|^\s*\d[\d\s./,\-]{3,}$")
_SKIP_LINE_RE_I = re.compile(
    r"tel[.:\s]|fax[.:\s]|p\.?\s*iva|c\.?\s*f\.?|pec\b"
    r"|(via|viale|piazza|corso|largo)\s+\w|cap\s*\d{5}"
    # OCR page separator markers like "--- Pagina 1 ---" or "--- Page 2 ---"
    r"|^-{2,}.*-{2,}$"
    # Institutional headers (e.g. "REGIONE DEL VENETO", "Azienda ULSS n. 7")
    r"|^regione\b|^comune\b|^provincia\b|^prefettura\b"
    r"|azienda\s+(?:ulss|usl|ospedaliera)"
    r"|presidio\s+ospedaliero"
    r"|legione\s+carabinieri|stazione\s+cc\b"
    r"|^ulss\d",
    re.IGNORECASE,
)

def _parse_italian_date(text: str) -> str | None:
    """Try to parse an Italian date string into YYYYMMDD format.

    Handles formats like:
        "15 marzo 2024"
        "30.09.2024"
        "30/09/2024"
        "2024-03-15"
    """
    text = text.strip()

    # Format: "15 marzo 2024" or "15 Marzo 2024"
    m = re.match(r"(\d{1,2})\s+([a-zA-ZàèéìòùÀÈÉÌÒÙ]+)\s+(\d{4})", text)
    if m:
        day, month_name, year = m.groups()
        month_num = _ITALIAN_MONTHS.get(month_name.lower())
        if month_num:
            return f"{year}{month_num:02d}{int(day):02d}"

    # Format: "30.09.2024" or "30/09/2024"
    m = re.match(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", text)
    if m:
        day, month, year = m.groups()
        return f"{year}{int(month):02d}{int(day):02d}"

    # Format: "2024-03-15"
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        year, month, day = m.groups()
        return f"{year}{month}{day}"

    # Format: "30.09.2024" inside a longer string - extract date part
    m = re.search(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", text)
    if m:
        day, month, year = m.groups()
        return f"{year}{int(month):02d}{int(day):02d}"

    # Format: Italian month name inside a longer string
    # e.g. "Sandrigo, 30 Agosto 2023" or "del 15 marzo 2024"
    m = re.search(r"(\d{1,2})\s+([a-zA-ZàèéìòùÀÈÉÌÒÙ]+)\s+(\d{4})", text)
    if m:
        day, month_name, year = m.groups()
        month_num = _ITALIAN_MONTHS.get(month_name.lower())
        if month_num:
            return f"{year}{month_num:02d}{int(day):02d}"

    return None


def _find_date_from_extractions(extractions: list[dict]) -> str | None:
    """Find the most relevant date from extraction results.

    Prioritizes document-level dates (deposit date, invoice date, etc.)
    over incidental dates (hearing dates, deadlines, etc.).
    """
    # Priority order for date extraction classes
    date_priority = [
        "data_fattura",          # Invoice date
        "data_deposito",         # Court filing date
        "data_sentenza",         # Sentence date
        "estratto_conto",        # Bank statement (date in attributes)
        "data_udienza",          # Hearing date
        "data_scadenza",         # Due date
        "data",                  # Generic date
    ]

    # First pass: look for high-priority date classes
    for target_class in date_priority:
        for ext in extractions:
            cls = ext.get("extraction_class", "").lower()
            if cls == target_class:
                # For estratto_conto, the date is in attributes
                if cls == "estratto_conto":
                    attrs = ext.get("attributes") or {}
                    date_str = attrs.get("data_chiusura") or attrs.get("periodo_fine") or ""
                    parsed = _parse_italian_date(date_str)
                    if parsed:
                        return parsed

                # Try the extraction text directly
                parsed = _parse_italian_date(ext.get("extraction_text", ""))
                if parsed:
                    return parsed

                # Try date in attributes
                attrs = ext.get("attributes") or {}
                for attr_val in attrs.values():
                    if isinstance(attr_val, str):
                        parsed = _parse_italian_date(attr_val)
                        if parsed:
                            return parsed

    # Fallback: any extraction with "data" in the class name
    for ext in extractions:
        cls = ext.get("extraction_class", "").lower()
        if "data" in cls:
            parsed = _parse_italian_date(ext.get("extraction_text", ""))
            if parsed:
                return parsed

    return None


# Patterns that capture a date immediately after a document-date label.
# Each pattern captures the date portion in group(1..3) or via a named group.
# Used to extract the date right next to the label, ignoring other dates on the same line.
_DOC_DATE_EXTRACTORS: list[re.Pattern] = [
    # "Data ed ora di apertura 25/02/2026", "Data di rilascio 25/02/2026"
    re.compile(
        r"data\s+(?:ed?\s+ora\s+)?di\s+"
        r"(?:apertura|chiusura|rilascio|emissione|redazione|stesura|deposito)"
        r"\s+(\d{1,2})[./](\d{1,2})[./](\d{4})",
        re.IGNORECASE,
    ),
    # "Data del verbale 25/02/2026", "Data fattura 25/02/2026"
    re.compile(
        r"data\s+(?:del\s+)?(?:verbale|documento|referto|certificato|atto|sentenza|fattura)"
        r"\s+(\d{1,2})[./](\d{1,2})[./](\d{4})",
        re.IGNORECASE,
    ),
    # "Data Referto 25/02/2026"
    re.compile(
        r"data\s+referto\s+(\d{1,2})[./](\d{1,2})[./](\d{4})",
        re.IGNORECASE,
    ),
    # "Il giorno 25/02/2026" / "del giorno 25/02/2026"
    re.compile(
        r"(?:il|del)\s+giorno\s+(\d{1,2})[./](\d{1,2})[./](\d{4})",
        re.IGNORECASE,
    ),
    # "in data 25/02/2026" / "addì 25/02/2026"
    re.compile(
        r"(?:in\s+data|addì|addi)\s+(\d{1,2})[./](\d{1,2})[./](\d{4})",
        re.IGNORECASE,
    ),
    # "firmato digitalmente ... in data 25/02/2026"
    re.compile(
        r"firmat[oa]\s+.{0,40}(?:in\s+data|il)\s+(\d{1,2})[./](\d{1,2})[./](\d{4})",
        re.IGNORECASE,
    ),
    # "le operazioni si sono concluse alle ore 14:20 del 25/02/2026"
    re.compile(
        r"le\s+operazioni\s+si\s+sono\s+concluse\s+.{0,30}(\d{1,2})[./](\d{1,2})[./](\d{4})",
        re.IGNORECASE,
    ),
    # Italian month: "data di rilascio 25 febbraio 2026"
    re.compile(
        r"data\s+(?:ed?\s+ora\s+)?di\s+"
        r"(?:apertura|chiusura|rilascio|emissione|redazione|stesura|deposito)"
        r"\s+(\d{1,2})\s+([a-zA-ZàèéìòùÀÈÉÌÒÙ]+)\s+(\d{4})",
        re.IGNORECASE,
    ),
    # "Il giorno 25 febbraio 2026"
    re.compile(
        r"(?:il|del)\s+giorno\s+(\d{1,2})\s+([a-zA-ZàèéìòùÀÈÉÌÒÙ]+)\s+(\d{4})",
        re.IGNORECASE,
    ),
]

# Regex patterns that indicate a date on that line is personal / incidental
# (birth dates, residence dates, etc.) and should be skipped.
_PERSONAL_DATE_LABEL_RE = re.compile(
    r"nat[oa]\s+(?:il|a\s)|data\s+di\s+nascita|GG/MM/YYYY"
    r"|codice\s+fiscale|c\.?\s*f\.?\s*:"
    r"|(?:nato|nata)\s+il",
    re.IGNORECASE,
)


def _find_date_from_text(text: str) -> str | None:
    """Find the document date from OCR text using contextual clues.

    Strategy (in priority order):
    1. Search for dates immediately adjacent to document-date labels
       (e.g. "Data di rilascio 25/02/2026"). This is precise even when
       multiple dates appear on the same line.
    2. Fall back to the first date on a line that does NOT contain
       personal-date markers (e.g. "Nato il", "Data di nascita").
    3. Last resort: any date at all.
    """
    sample = text[:6000]

    # Pass 1: extract dates right next to document-date labels
    for extractor in _DOC_DATE_EXTRACTORS:
        m = extractor.search(sample)
        if m:
            groups = m.groups()
            if len(groups) == 3:
                g1, g2, g3 = groups
                # Check if g2 is a month name (Italian) or numeric
                month_num = _ITALIAN_MONTHS.get(g2.lower()) if g2 else None
                if month_num is not None:
                    # day, month_name, year
                    return f"{g3}{month_num:02d}{int(g1):02d}"
                else:
                    # day, month_number, year
                    return f"{g3}{int(g2):02d}{int(g1):02d}"

    # Pass 2: first date on a line without personal-date markers
    lines = sample.split('\n')
    for line in lines:
        stripped = line.strip()
        if _PERSONAL_DATE_LABEL_RE.search(stripped):
            continue
        parsed = _parse_italian_date(stripped)
        if parsed:
            return parsed

    # Pass 3 (last resort): any date at all
    for line in lines:
        parsed = _parse_italian_date(line.strip())
        if parsed:
            return parsed

    return None


def _extract_oggetto_subject(text: str) -> str | None:
    """Extract the subject from an 'Oggetto:' line in the text.

    Returns the subject text (e.g. 'Dichiarazione porta blindata rif. Cecchin'),
    or None if no 'Oggetto:' line is found.
    """
    m = re.search(r"\boggetto\s*:\s*(.+)", text, re.IGNORECASE)
    if m:
        subject = m.group(1).strip()
        # Only use if it's meaningful (not just punctuation or very short)
        if len(subject) >= 5 and sum(1 for c in subject if c.isalpha()) >= 4:
            return _shorten_name(subject, max_len=80)
    return None


def _find_description_from_text(text: str) -> str | None:
    """Extract a content description from raw OCR text without an LLM call.

    Strategy:
    1. Look for an "Oggetto:" line and use its subject text (most specific).
    2. Look for a known Italian document-type keyword.
    3. Fall back to the first meaningful non-header line in the text.
    """
    sample = text[:4000]

    # 1. "Oggetto:" subject — the most informative description available
    subject = _extract_oggetto_subject(sample)
    if subject:
        return subject

    # 2. Keyword match for known document types (longest/most-specific first)
    for pattern, label in _DOCUMENT_TYPE_PATTERNS:
        if re.search(pattern, sample, re.IGNORECASE):
            return label

    # 3. First meaningful line that doesn't look like a header/address/contact
    for line in sample.split('\n'):
        line = line.strip()
        if len(line) < 6 or len(line) > 120:
            continue
        if _SKIP_LINE_RE.search(line) or _SKIP_LINE_RE_I.search(line):
            continue
        # Must contain at least a few real letters (not just numbers/symbols)
        if sum(1 for c in line if c.isalpha()) < 5:
            continue
        return _shorten_name(line, max_len=80)

    return None


def derive_filename_from_text(
    ocr_text: str, original_filename: str
) -> tuple[str, str]:
    """Derive a filename from raw OCR text (used when schema is 'none').

    Extracts the document date and a content-based description directly from
    the OCR text, with zero additional LLM calls.
    Falls back to the original filename stem only if no description can be found.
    """
    date_str = _find_date_from_text(ocr_text) or "00000000"
    description = _find_description_from_text(ocr_text)
    if not description:
        stem = Path(original_filename).stem
        description = _sanitize_filename(stem) or "Documento"
    return date_str, description


def _find_description_from_extractions(
    extractions: list[dict], schema_name: str
) -> str | None:
    """Build a short description from extraction results.

    Returns a concise description like:
        "Sentenza Tribunale di Milano"
        "Fattura 001-2024 Tech Solutions"
        "Estratto Conto 003-2024 Intesa Sanpaolo"
    """
    ext_by_class = {}
    for ext in extractions:
        cls = ext.get("extraction_class", "").lower()
        if cls not in ext_by_class:
            ext_by_class[cls] = ext

    if schema_name == "full_legal":
        return _describe_legal(ext_by_class)
    elif schema_name == "parties_dates":
        return _describe_parties(ext_by_class)
    elif schema_name == "invoice":
        return _describe_invoice(ext_by_class)
    elif schema_name == "estratto_conto":
        return _describe_bank_statement(ext_by_class)
    else:
        # Custom or unknown schema: try generic approach
        return _describe_generic(ext_by_class)


def _describe_legal(ext_by_class: dict) -> str | None:
    parts = []

    # Document type: check for dispositivo (sentence) or domanda (petition)
    if "dispositivo" in ext_by_class:
        parts.append("Sentenza")
    else:
        parts.append("Documento Legale")

    # Tribunal
    tribunal = ext_by_class.get("tribunale")
    if tribunal:
        text = tribunal["extraction_text"]
        # Shorten "TRIBUNALE DI MILANO" to "Tribunale di Milano"
        parts.append(text.title() if len(text) < 40 else text[:35].title())

    # Parties: attore vs convenuto
    attore = ext_by_class.get("parte_attore")
    convenuto = ext_by_class.get("parte_convenuto")
    if attore and convenuto:
        a = _shorten_name(attore["extraction_text"])
        c = _shorten_name(convenuto["extraction_text"])
        parts.append(f"{a} vs {c}")
    elif attore:
        parts.append(_shorten_name(attore["extraction_text"]))

    return " - ".join(parts) if parts else None


def _describe_parties(ext_by_class: dict) -> str | None:
    parts = ["Documento Legale"]
    attore = ext_by_class.get("parte_attore")
    convenuto = ext_by_class.get("parte_convenuto")
    if attore and convenuto:
        a = _shorten_name(attore["extraction_text"])
        c = _shorten_name(convenuto["extraction_text"])
        parts.append(f"{a} vs {c}")
    elif attore:
        parts.append(_shorten_name(attore["extraction_text"]))
    return " - ".join(parts) if len(parts) > 1 else parts[0]


def _describe_invoice(ext_by_class: dict) -> str | None:
    parts = ["Fattura"]
    num = ext_by_class.get("numero_fattura")
    if num:
        parts.append(num["extraction_text"].replace("/", "-"))
    fornitore = ext_by_class.get("fornitore")
    if fornitore:
        parts.append(_shorten_name(fornitore["extraction_text"]))
    return " ".join(parts) if parts else None


def _describe_bank_statement(ext_by_class: dict) -> str | None:
    parts = ["Estratto Conto"]
    ec = ext_by_class.get("estratto_conto")
    if ec:
        attrs = ec.get("attributes") or {}
        num = attrs.get("numero", "")
        if num:
            parts.append(num.replace("/", "-"))
    banca = ext_by_class.get("banca")
    if banca:
        parts.append(_shorten_name(banca["extraction_text"]))
    return " ".join(parts) if parts else None


def _describe_generic(ext_by_class: dict) -> str | None:
    """Fallback: take the first meaningful extraction as description."""
    # Skip date-like and numeric classes
    skip = {"data", "importo", "iva", "totale", "saldo", "movimento"}
    for cls, ext in ext_by_class.items():
        if not any(s in cls for s in skip):
            text = ext.get("extraction_text", "")
            if text and len(text) > 3:
                return _shorten_name(text, max_len=60)
    return None


def _shorten_name(text: str, max_len: int = 40) -> str:
    """Shorten a name/text to a reasonable length for filenames."""
    text = text.strip()
    if len(text) <= max_len:
        return text
    return text[:max_len].rsplit(" ", 1)[0]


def _sanitize_filename(name: str) -> str:
    """Remove/replace characters that are invalid in filenames."""
    # Replace problematic characters
    name = re.sub(r'[<>:"/\\|?*]', "", name)
    # Collapse multiple spaces/dashes
    name = re.sub(r"\s+", " ", name)
    name = re.sub(r"-{2,}", "-", name)
    return name.strip(" .-")


def derive_filename(
    extractions: list[dict], schema_name: str
) -> tuple[str, str] | None:
    """Derive a descriptive filename from extraction results.

    Args:
        extractions: List of extraction dicts from LegalExtractor.result_to_dict().
        schema_name: Active schema name (e.g. "full_legal", "invoice").

    Returns:
        Tuple of (date_str, description) like ("20240315", "Sentenza Tribunale di Milano"),
        or None if insufficient data to determine a filename.
    """
    if not extractions:
        return None

    date_str = _find_date_from_extractions(extractions)
    description = _find_description_from_extractions(extractions, schema_name)

    if not date_str and not description:
        return None

    # Use "00000000" as placeholder if no date found
    if not date_str:
        date_str = "00000000"

    if not description:
        description = "Documento"

    description = _sanitize_filename(description)
    return date_str, description


def build_new_filepath(
    original_path: Path, date_str: str, description: str
) -> Path:
    """Build a new file path with the format 'YYYYMMDD - Description.ext'.

    The file is placed in the same directory as the original.
    """
    ext = original_path.suffix
    new_name = _sanitize_filename(f"{date_str} - {description}") + ext
    return original_path.parent / new_name


def rename_file(original_path: Path, new_path: Path) -> Path:
    """Rename a file, handling conflicts by appending a counter.

    Returns the actual path the file was renamed to.
    """
    if original_path == new_path:
        logger.info("File gia' con il nome corretto: %s", original_path.name)
        return original_path

    # Handle naming conflicts
    final_path = new_path
    counter = 1
    while final_path.exists():
        stem = new_path.stem
        ext = new_path.suffix
        final_path = new_path.parent / f"{stem} ({counter}){ext}"
        counter += 1

    shutil.move(str(original_path), str(final_path))
    logger.info("File rinominato: %s -> %s", original_path.name, final_path.name)
    return final_path
