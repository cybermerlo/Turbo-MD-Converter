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


def _find_date_from_text(text: str) -> str | None:
    """Find the first recognizable date by scanning raw OCR text line by line."""
    for line in text[:3000].split('\n'):
        parsed = _parse_italian_date(line.strip())
        if parsed:
            return parsed
    return None


def derive_filename_from_text(
    ocr_text: str, original_filename: str
) -> tuple[str, str]:
    """Derive a filename from raw OCR text (used when schema is 'none').

    Finds the first date in the OCR text and uses the original filename stem
    as the description. Always returns a usable tuple.
    """
    date_str = _find_date_from_text(ocr_text) or "00000000"
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
