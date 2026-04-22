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
    rename_examples: list[dict] | None = None,
    batch_documents: list[dict] | None = None,
    current_doc_id: int | None = None,
    user_context_text: str = "",
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
    batch_context = _build_batch_documents_context(
        original_filename=original_filename,
        batch_documents=batch_documents,
        current_doc_id=current_doc_id,
    )
    history_context = _build_rename_context_block(rename_examples)
    user_context = _build_user_context_block(user_context_text)
    context_blocks = [b for b in (user_context, batch_context, history_context) if b]
    context = "\n\n".join(context_blocks)
    prompt = (context + "\n\n" if context else "") + rename_prompt.format(ocr_sample=sample)

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model_id,
            contents=[types.Part.from_text(text=prompt)],
        )
        raw = _strip_json_fences(response.text.strip())

        data = json.loads(raw)
        date_str = str(data.get("data", "00000000")).strip()
        description = str(data.get("descrizione", "")).strip()

        # Validate date: must be exactly 8 digits and a plausible calendar value
        if not re.match(r"^\d{8}$", date_str) or not _is_plausible_date(date_str):
            logger.warning(
                "LLM ha restituito una data non valida ('%s') - uso 00000000", date_str
            )
            date_str = "00000000"

        description = _strip_leading_date_prefix(description)
        description = _sanitize_filename(description) or _fallback_description(original_filename)
        description = _ensure_unique_description(
            date_str=date_str,
            description=description,
            original_filename=original_filename,
            rename_examples=rename_examples,
        )
        logger.info("Nome file derivato via LLM: %s - %s", date_str, description)
        return date_str, description

    except Exception as exc:
        logger.warning("Derivazione nome file via LLM fallita: %s", exc)
        return "00000000", _fallback_description(original_filename)


def derive_batch_profiles_from_llm(
    batch_documents: list[dict],
    api_key: str,
    model_id: str,
    user_context_text: str = "",
) -> dict[int, dict]:
    """Derive distinguishing profiles for each document in the batch.

    Returns a mapping doc_id -> profile dict with:
    - primary_topic
    - distinguishing_focus
    - naming_hint
    - distinctive_terms (list[str])
    """
    if not batch_documents or len(batch_documents) < 2:
        return {}

    docs_payload: list[dict] = []
    for d in batch_documents[:30]:
        doc_id = int(d.get("doc_id", 0))
        docs_payload.append({
            "doc_id": doc_id,
            "name": str(d.get("original_name", "")).strip(),
            "keywords": str(d.get("keyword_hint", "")).strip(),
            "preview_start": str(d.get("ocr_preview_start", "")).strip()[:1200],
            "preview_middle": str(d.get("ocr_preview_middle", "")).strip()[:800],
        })

    user_block = _build_user_context_block(user_context_text)
    prompt = (
        ((user_block + "\n\n") if user_block else "")
        + "Analizza i documenti seguenti come insieme e trova la differenza SEMANTICA "
        "tra ogni documento.\n"
        "Per ciascun documento devi produrre:\n"
        "- primary_topic: tema generale breve\n"
        "- distinguishing_focus: il focus specifico che lo distingue dagli altri\n"
        "- naming_hint: etichetta sintetica (max 55 caratteri) adatta a nome file\n"
        "- distinctive_terms: 3-6 termini chiave distintivi\n\n"
        "Regole:\n"
        "- naming_hint deve essere specifico e non generico.\n"
        "- Evita etichette quasi uguali tra documenti diversi.\n"
        "- Restituisci SOLO JSON valido con schema:\n"
        '{"documents":[{"doc_id":1,"primary_topic":"...","distinguishing_focus":"...",'
        '"naming_hint":"...","distinctive_terms":["..."]}]}\n\n'
        f"Documenti:\n{json.dumps(docs_payload, ensure_ascii=False)}"
    )

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model_id,
            contents=[types.Part.from_text(text=prompt)],
        )
        raw = _strip_json_fences(response.text.strip())
        data = json.loads(raw)
        docs = data.get("documents")
        if not isinstance(docs, list):
            return {}

        profiles: dict[int, dict] = {}
        for item in docs:
            if not isinstance(item, dict):
                continue
            try:
                doc_id = int(item.get("doc_id"))
            except (TypeError, ValueError):
                continue

            primary_topic = _sanitize_filename(str(item.get("primary_topic", "")).strip())
            focus = _sanitize_filename(str(item.get("distinguishing_focus", "")).strip())
            naming_hint = _sanitize_filename(str(item.get("naming_hint", "")).strip())
            naming_hint = _truncate_description(naming_hint, 55)

            terms = item.get("distinctive_terms", [])
            if not isinstance(terms, list):
                terms = []
            clean_terms = [
                _sanitize_filename(str(t).strip())
                for t in terms
                if str(t).strip()
            ][:6]

            profiles[doc_id] = {
                "primary_topic": primary_topic,
                "distinguishing_focus": focus,
                "naming_hint": naming_hint,
                "distinctive_terms": clean_terms,
            }

        logger.info("Profili batch derivati: %s documenti", len(profiles))
        return profiles
    except Exception as exc:
        logger.warning("Analisi profili batch fallita: %s", exc)
        return {}


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


def _build_rename_context_block(rename_examples: list[dict] | None) -> str:
    """Build an optional prompt prefix with batch rename examples.

    The history can grow unbounded in memory, but we only inject the latest
    few examples into the prompt to keep it compact and stable.
    """
    if not rename_examples:
        return ""

    # Keep prompt size bounded; history growth is handled by the caller.
    max_examples = 8
    examples = rename_examples[-max_examples:]

    used_names: list[str] = []
    seen: set[str] = set()
    for ex in examples:
        final_name = str(ex.get("final_name", "")).strip()
        if not final_name:
            continue
        base = Path(final_name).stem.strip()
        norm = base.lower()
        if base and norm not in seen:
            used_names.append(base)
            seen.add(norm)

    lines: list[str] = []
    lines.append("Contesto di coerenza per questo batch:")
    lines.append("- Mantieni stile e terminologia coerenti con i file gia' rinominati.")
    lines.append("- NON riusare la stessa descrizione in modo identico.")
    lines.append("")
    lines.append("Nomi gia' assegnati (NON riusare tal quali):")
    for name in used_names:
        lines.append(f"- {name}")

    return "\n".join(lines)


def _build_batch_documents_context(
    original_filename: str,
    batch_documents: list[dict] | None,
    current_doc_id: int | None = None,
) -> str:
    """Build prompt context with an overview of all documents in the batch."""
    if not batch_documents:
        return ""

    max_docs = 25
    docs = batch_documents[:max_docs]
    lines: list[str] = []
    lines.append("Contesto batch (OCR disponibile per tutti i documenti):")
    lines.append(
        "Usa questa vista d'insieme per distinguere documenti simili e generare "
        "un nome specifico del documento corrente."
    )
    if current_doc_id is not None:
        lines.append(f"Documento corrente: #{current_doc_id} - {original_filename}")
    else:
        lines.append(f"Documento corrente: {original_filename}")
    lines.append("Regola: non usare descrizioni generiche uguali per documenti diversi.")
    lines.append("")
    lines.append("Panoramica documenti del batch:")

    for d in docs:
        doc_id = d.get("doc_id")
        name = str(d.get("original_name", "")).strip() or "(senza nome)"
        prefix = f"#{doc_id} " if doc_id is not None else ""
        lines.append(f"- {prefix}{name}")

        profile_hint = str(d.get("profile_naming_hint", "")).strip()
        focus_hint = str(d.get("profile_focus", "")).strip()
        terms = d.get("profile_terms", [])
        if isinstance(terms, list):
            terms = [str(t).strip() for t in terms if str(t).strip()]
        else:
            terms = []
        if profile_hint:
            lines.append(f"  hint_nome: {profile_hint}")
        if focus_hint:
            lines.append(f"  focus: {focus_hint}")
        if terms:
            lines.append(f"  termini: {', '.join(terms[:6])}")

        keyword_hint = str(d.get("keyword_hint", "")).strip()
        if keyword_hint:
            lines.append(f"  keyword: {keyword_hint}")

        preview_start = str(d.get("ocr_preview_start", "")).strip()
        preview_start = re.sub(r"\s+", " ", preview_start)[:220]
        if preview_start:
            lines.append(f"  inizio: {preview_start}")

        preview_middle = str(d.get("ocr_preview_middle", "")).strip()
        preview_middle = re.sub(r"\s+", " ", preview_middle)[:180]
        if preview_middle:
            lines.append(f"  centro: {preview_middle}")

    return "\n".join(lines)


def _build_user_context_block(user_context_text: str) -> str:
    """Build optional user-provided context to steer filename generation."""
    text = (user_context_text or "").strip()
    if not text:
        return ""
    return (
        "ISTRUZIONI UTENTE (PRIORITA' MASSIMA):\n"
        "- Le istruzioni qui sotto hanno priorita' assoluta su qualunque altra regola o indicazione.\n"
        "- Se c'e' conflitto tra istruzioni, segui SEMPRE queste istruzioni utente.\n"
        "- Applica queste istruzioni sia alla scelta della descrizione sia allo stile del nome.\n\n"
        f"{text}"
    )


def _ensure_unique_description(
    date_str: str,
    description: str,
    original_filename: str,
    rename_examples: list[dict] | None,
) -> str:
    """Prevent exact date+description duplicates within the same batch."""
    clean_description = _sanitize_filename(description) or _fallback_description(original_filename)
    if not rename_examples:
        return clean_description

    used_keys = _collect_used_date_description_keys(rename_examples)
    current_key = _build_date_description_key(date_str, clean_description)
    if current_key not in used_keys:
        return clean_description

    # If LLM copies a previous filename exactly, force a deterministic variant
    # tied to the current source filename.
    source_hint = _fallback_description(original_filename)
    candidate = _sanitize_filename(f"{clean_description} - {source_hint}")
    candidate = _truncate_description(candidate, 60)
    if _build_date_description_key(date_str, candidate) not in used_keys:
        logger.info("Nome duplicato nel batch: applico variante con hint sorgente")
        return candidate

    for idx in range(2, 100):
        candidate = _sanitize_filename(f"{clean_description} - {source_hint} {idx}")
        candidate = _truncate_description(candidate, 60)
        if _build_date_description_key(date_str, candidate) not in used_keys:
            logger.info("Nome duplicato nel batch: applico variante incrementale")
            return candidate

    return _fallback_description(original_filename)


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


def _collect_used_date_description_keys(rename_examples: list[dict]) -> set[str]:
    keys: set[str] = set()
    for ex in rename_examples:
        date_str = str(ex.get("date_str", "")).strip() or "00000000"
        description = str(ex.get("description", "")).strip()
        if not description:
            final_name = str(ex.get("final_name", "")).strip()
            if final_name:
                description = _description_from_final_name(final_name)
        description = _sanitize_filename(description)
        if not description:
            continue
        keys.add(_build_date_description_key(date_str, description))
    return keys


def _build_date_description_key(date_str: str, description: str) -> str:
    clean_date = (date_str or "00000000").strip()
    clean_desc = _sanitize_filename(description).lower()
    return f"{clean_date}::{clean_desc}"


def _description_from_final_name(final_name: str) -> str:
    stem = Path(final_name).stem.strip()
    parts = stem.split(" - ", 1)
    return _sanitize_filename(parts[1] if len(parts) == 2 else stem)


def _truncate_description(description: str, max_len: int) -> str:
    if len(description) <= max_len:
        return description
    return description[:max_len].rstrip(" .-")


def _strip_json_fences(raw: str) -> str:
    cleaned = re.sub(r"^```[a-z]*\s*", "", raw, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def _strip_leading_date_prefix(description: str) -> str:
    """Remove one or more leading YYYYMMDD - prefixes from description."""
    text = (description or "").strip()
    if not text:
        return ""
    # Handles repeated prefixes like:
    # "20230217 - 20230217 - Titolo"
    return re.sub(r"^(?:\d{8}\s*-\s*)+", "", text).strip()
