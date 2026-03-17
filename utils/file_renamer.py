"""Derive a descriptive filename from OCR text via a lightweight LLM call."""

import json
import logging
import re
import shutil
from pathlib import Path

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def derive_filename_from_llm(
    ocr_text: str,
    api_key: str,
    model_id: str,
    rename_prompt: str,
    original_filename: str = "",
) -> tuple[str, str]:
    """Ask an LLM to derive the document date and a short description.

    Args:
        ocr_text: Combined OCR text from the document.
        api_key: Gemini API key.
        model_id: Gemini model to use.
        rename_prompt: The prompt template (must contain ``{ocr_sample}``).
        original_filename: Used as fallback description if LLM fails.

    Returns:
        (date_str, description) where date_str is "YYYYMMDD" or "00000000"
        if the date cannot be determined with confidence.
    """
    sample = ocr_text[:5000].strip()
    prompt = rename_prompt.format(ocr_sample=sample)

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model_id,
            contents=[types.Part.from_text(text=prompt)],
        )
        raw = response.text.strip()

        # Strip markdown code fences if the model wraps its answer
        raw = re.sub(r"^```[a-z]*\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)

        data = json.loads(raw)
        date_str = str(data.get("data", "00000000")).strip()
        description = str(data.get("descrizione", "")).strip()

        # Validate date: must be exactly 8 digits and a plausible calendar value
        if not re.match(r"^\d{8}$", date_str) or not _is_plausible_date(date_str):
            logger.warning(
                "LLM ha restituito una data non valida ('%s') - uso 00000000", date_str
            )
            date_str = "00000000"

        description = _sanitize_filename(description) or _fallback_description(original_filename)
        logger.info("Nome file derivato via LLM: %s - %s", date_str, description)
        return date_str, description

    except Exception as exc:
        logger.warning("Derivazione nome file via LLM fallita: %s", exc)
        return "00000000", _fallback_description(original_filename)


# ---------------------------------------------------------------------------
# Filesystem helpers
# ---------------------------------------------------------------------------

def build_new_filepath(original_path: Path, date_str: str, description: str) -> Path:
    """Build a new file path with the format 'YYYYMMDD - Description.ext'."""
    ext = original_path.suffix
    new_name = _sanitize_filename(f"{date_str} - {description}") + ext
    return original_path.parent / new_name


def rename_file(original_path: Path, new_path: Path) -> Path:
    """Rename a file, appending a counter on conflicts.

    Returns the actual path the file was renamed to.
    """
    if original_path == new_path:
        logger.info("File gia' con il nome corretto: %s", original_path.name)
        return original_path

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


# ---------------------------------------------------------------------------
# Internal utilities
# ---------------------------------------------------------------------------

def _is_plausible_date(date_str: str) -> bool:
    """Return True if YYYYMMDD looks like a real calendar date."""
    try:
        year = int(date_str[:4])
        month = int(date_str[4:6])
        day = int(date_str[6:])
        return 1900 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31
    except ValueError:
        return False


def _sanitize_filename(name: str) -> str:
    """Remove/replace characters that are invalid in filenames."""
    name = re.sub(r'[<>:"/\\|?*]', "", name)
    name = re.sub(r"\s+", " ", name)
    name = re.sub(r"-{2,}", "-", name)
    return name.strip(" .-")


def _fallback_description(original_filename: str) -> str:
    """Use the original filename stem as a last-resort description."""
    stem = Path(original_filename).stem if original_filename else ""
    return _sanitize_filename(stem) or "Documento"
