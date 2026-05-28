"""File rename orchestration: immediate and deferred batch rename."""

import re
import threading
from collections.abc import Callable
from pathlib import Path

from config.settings import AppConfig
from pipeline.events import FileRenamedEvent, LogEvent, PipelineEvent
from pipeline.models import EmailAttachmentDocument
from utils.file_renamer import (
    build_new_filepath,
    derive_batch_profiles_from_llm,
    derive_filename_from_llm,
    rename_file,
)


def safe_output_stem_component(value: str, fallback: str) -> str:
    text = Path(str(value)).stem or fallback
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text[:90] or fallback


def attachment_output_stem(
    email_stem: str,
    attachment_doc: EmailAttachmentDocument,
) -> str:
    base = safe_output_stem_component(email_stem, "email")
    attachment = safe_output_stem_component(
        attachment_doc.filename,
        f"allegato {attachment_doc.index}",
    )
    return f"{base} - Allegato {attachment_doc.index} - {attachment}"


class RenameCoordinator:
    """Handles LLM-driven file renaming for single docs and batches."""

    def __init__(
        self,
        config: AppConfig,
        emit: Callable[[PipelineEvent], None],
    ):
        self.config = config
        self.emit = emit

    def rename_files(
        self,
        pdf_path: Path,
        output_files: list[Path],
        rename_result: tuple[str, str],
        rename_history: list[dict] | None = None,
    ) -> tuple[Path, list[Path]]:
        date_str, description = rename_result
        self.emit(LogEvent(
            message=f"Rinomina file: data={date_str}, descrizione='{description}'"
        ))

        renamed_pdf = pdf_path
        renamed_outputs = list(output_files)
        history_final_name: str | None = None

        if self.config.rename_mode in ("md", "both"):
            for i, fp in enumerate(renamed_outputs):
                if fp.suffix.lower() == ".md":
                    new_path = build_new_filepath(fp, date_str, description)
                    try:
                        actual_path = rename_file(fp, new_path)
                        self.emit(FileRenamedEvent(
                            original_path=fp, new_path=actual_path, file_type="md",
                        ))
                        renamed_outputs[i] = actual_path
                        history_final_name = history_final_name or actual_path.name
                    except OSError as e:
                        self.emit(LogEvent(
                            message=f"Errore rinomina MD: {e}", level="ERROR",
                        ))

        if self.config.rename_mode in ("pdf", "both"):
            new_pdf_path = build_new_filepath(pdf_path, date_str, description)
            try:
                actual_pdf_path = rename_file(pdf_path, new_pdf_path)
                self.emit(FileRenamedEvent(
                    original_path=pdf_path, new_path=actual_pdf_path, file_type="pdf",
                ))
                renamed_pdf = actual_pdf_path
                history_final_name = actual_pdf_path.name
            except OSError as e:
                self.emit(LogEvent(
                    message=f"Errore rinomina PDF: {e}", level="ERROR",
                ))

        if rename_history is not None and history_final_name:
            rename_history.append({
                "file_type": "document",
                "original_name": pdf_path.name,
                "final_name": history_final_name,
                "date_str": date_str,
                "description": description,
            })

        return renamed_pdf, renamed_outputs

    def run_deferred_renames(
        self,
        deferred_renames: list[dict],
        rename_history: list[dict],
        cancel_event: threading.Event,
    ) -> None:
        from config.defaults import DEFAULT_RENAME_PROMPT

        rename_prompt = self.config.rename_prompt or DEFAULT_RENAME_PROMPT
        batch_documents = build_batch_documents_context(deferred_renames)
        batch_profiles = derive_batch_profiles_from_llm(
            batch_documents=batch_documents,
            api_key=self.config.gemini_api_key,
            model_id=self.config.ocr_model_id,
            user_context_text=(
                self.config.rename_user_context_text
                if self.config.rename_use_user_context
                else ""
            ),
        )
        apply_batch_profiles(batch_documents, batch_profiles)
        total = len(deferred_renames)
        self.emit(LogEvent(
            message=f"Avvio rinomina post-OCR su {total} documenti"
        ))

        for idx, item in enumerate(deferred_renames, 1):
            if cancel_event.is_set():
                self.emit(LogEvent(
                    message="Rinomina post-OCR annullata", level="WARNING"
                ))
                break

            pdf_path: Path = item["pdf_path"]
            output_files: list[Path] = item["output_files"]
            ocr_text: str = item["ocr_text"]
            self.emit(LogEvent(
                message=f"Rinomina post-OCR {idx}/{total}: {pdf_path.name}"
            ))
            rename_result = derive_filename_from_llm(
                ocr_text=ocr_text,
                api_key=self.config.gemini_api_key,
                model_id=self.config.ocr_model_id,
                rename_prompt=rename_prompt,
                original_filename=pdf_path.name,
                rename_examples=rename_history,
                batch_documents=batch_documents,
                current_doc_id=item.get("doc_id"),
                user_context_text=(
                    self.config.rename_user_context_text
                    if self.config.rename_use_user_context
                    else ""
                ),
            )
            renamed_pdf, renamed_outputs = self.rename_files(
                pdf_path=pdf_path,
                output_files=output_files,
                rename_result=rename_result,
                rename_history=rename_history,
            )
            item["pdf_path"] = renamed_pdf
            item["output_files"] = renamed_outputs

    def derive_immediate_rename(
        self,
        ocr_text: str,
        original_filename: str,
        rename_history: list[dict] | None,
    ) -> tuple[str, str]:
        from config.defaults import DEFAULT_RENAME_PROMPT

        rename_prompt = self.config.rename_prompt or DEFAULT_RENAME_PROMPT
        return derive_filename_from_llm(
            ocr_text=ocr_text,
            api_key=self.config.gemini_api_key,
            model_id=self.config.ocr_model_id,
            rename_prompt=rename_prompt,
            original_filename=original_filename,
            rename_examples=rename_history,
            user_context_text=(
                self.config.rename_user_context_text
                if self.config.rename_use_user_context
                else ""
            ),
        )


def build_batch_documents_context(deferred_renames: list[dict]) -> list[dict]:
    """Prepare compact OCR previews for all documents in batch."""
    from utils.file_renamer import extract_keyword_hint

    docs: list[dict] = []
    for item in deferred_renames:
        ocr_text = str(item.get("ocr_text", "")).strip()
        preview_start = ocr_text[:1200]
        mid = len(ocr_text) // 2
        preview_middle = ocr_text[mid:mid + 700]
        docs.append({
            "doc_id": item.get("doc_id"),
            "original_name": str(item.get("original_name", "")).strip(),
            "ocr_preview_start": preview_start,
            "ocr_preview_middle": preview_middle,
            "keyword_hint": extract_keyword_hint(ocr_text),
        })
    return docs


def apply_batch_profiles(batch_documents: list[dict], profiles: dict[int, dict]) -> None:
    """Merge LLM-derived document profiles into batch context in-place."""
    if not profiles:
        return
    for doc in batch_documents:
        doc_id = doc.get("doc_id")
        if doc_id is None:
            continue
        profile = profiles.get(int(doc_id))
        if not profile:
            continue
        doc["profile_primary_topic"] = profile.get("primary_topic", "")
        doc["profile_focus"] = profile.get("distinguishing_focus", "")
        doc["profile_naming_hint"] = profile.get("naming_hint", "")
        doc["profile_terms"] = profile.get("distinctive_terms", [])
