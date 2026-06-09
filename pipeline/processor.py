"""Full pipeline orchestrator: document -> OCR/read -> extract -> output."""

import logging
import math
import threading
from pathlib import Path
from typing import Callable

from config.settings import AppConfig
from extraction.extractor import LegalExtractor
from extraction.schemas import get_schema_preset
from ocr.audio_transcriber import AudioTranscriber, AudioTranscriberError
from ocr.ocr_pipeline import OCRPipeline, OCRResult
from output.json_formatter import JsonFormatter
from output.markdown_formatter import MarkdownFormatter
from output.writer import OutputWriter
from pipeline.attachment_processor import AttachmentProcessor
from pipeline.final_check import run_final_error_check
from pipeline.constants import (
    AUDIO_EXTENSIONS,
    DIRECT_READ_FORMATS,
    IMAGE_EXTENSIONS,
)
from pipeline.events import (
    BatchCompleteEvent,
    ErrorEvent,
    ExtractionCompleteEvent,
    ExtractionProgressEvent,
    ExtractionStartEvent,
    FinalCheckCompleteEvent,
    LogEvent,
    OCRProgressEvent,
    OutputWrittenEvent,
    PageNativeTextEvent,
    PageSkippedEvent,
    PipelineCompleteEvent,
    PipelineEvent,
)
from pipeline.models import EmailAttachmentDocument
from pipeline.rename_coordinator import RenameCoordinator, attachment_output_stem
from utils.cost_tracker import CostTracker

logger = logging.getLogger(__name__)


class DocumentProcessor:
    """Runs the full pipeline: acquire text -> extract -> write -> rename."""

    def __init__(
        self,
        config: AppConfig,
        event_callback: Callable[[PipelineEvent], None],
    ):
        self.config = config
        self.emit = event_callback
        self.cost_tracker = CostTracker()
        self.ocr_pipeline = OCRPipeline(config, self.cost_tracker)

        self.audio_transcriber = (
            AudioTranscriber(config.mistral_api_key)
            if config.mistral_api_key else None
        )

        if config.run_extraction:
            schema = get_schema_preset(config.active_schema)
            if schema and config.custom_schema_prompts.get(config.active_schema):
                schema.prompt_description = config.custom_schema_prompts[config.active_schema]
            self.extractor = LegalExtractor(config, schema, self.cost_tracker) if schema else None
            if self.extractor:
                self.extractor.set_progress_callback(self._on_extraction_progress)
        else:
            self.extractor = None

        self.md_formatter = MarkdownFormatter()
        self.json_formatter = JsonFormatter()
        self.rename_coordinator = RenameCoordinator(config, self.emit)
        self.attachment_processor = AttachmentProcessor(
            config=config,
            ocr_pipeline=self.ocr_pipeline,
            emit_log=self._emit_log,
            on_page_complete=self._on_ocr_page,
            on_page_skipped=self._on_page_skipped,
            on_page_native_text=self._on_page_native_text,
        )

        if config.output_mode == "cartella" and config.output_directory:
            self._fixed_output_dir: Path | None = Path(config.output_directory)
        else:
            self._fixed_output_dir = None

        self.writer = OutputWriter(self._fixed_output_dir)
        self._pending_email_attachment_docs: list[EmailAttachmentDocument] = []

    def _emit_log(self, message: str, level: str = "INFO") -> None:
        self.emit(LogEvent(message=message, level=level))

    def _fail(
        self,
        pdf_path: Path,
        error_message: str,
        *,
        recoverable: bool = False,
    ) -> tuple[bool, dict]:
        self.emit(ErrorEvent(error_message=error_message, recoverable=recoverable))
        cost_info = self.cost_tracker.get_totals()
        self.emit(PipelineCompleteEvent(
            pdf_path=pdf_path, success=False, cost_info=cost_info,
        ))
        return False, cost_info, None

    def process_single(
        self,
        pdf_path: Path,
        cancel_event: threading.Event,
        rename_history: list[dict] | None = None,
        defer_rename: bool = False,
        deferred_renames: list[dict] | None = None,
    ) -> tuple[bool, dict, tuple[Path, list[Path]] | None]:
        self.cost_tracker.reset()
        self._pending_email_attachment_docs = []
        self.emit(LogEvent(message=f"Inizio elaborazione: {pdf_path.name}"))

        acquire_result = self._acquire_text(pdf_path, cancel_event)
        if acquire_result is None:
            return self._last_fail_result(pdf_path)
        ocr_result, is_pdf, is_image = acquire_result

        if cancel_event.is_set():
            self.emit(LogEvent(message="Elaborazione annullata", level="WARNING"))
            return False, self.cost_tracker.get_totals(), None

        self._log_acquisition_summary(ocr_result, is_pdf, is_image)

        if not ocr_result.combined_text.strip():
            return self._fail(pdf_path, "Nessun testo estratto dall'OCR")

        email_attachment_docs = list(self._pending_email_attachment_docs)
        try:
            extractions = self._extract_entities_for_text(
                ocr_result.combined_text,
                source_label=pdf_path.name,
            )
            for attachment_doc in email_attachment_docs:
                if cancel_event.is_set():
                    return False, self.cost_tracker.get_totals(), None
                attachment_doc.extractions = self._extract_entities_for_text(
                    attachment_doc.text,
                    source_label=f"allegato {attachment_doc.filename}",
                )
        except Exception as e:
            return self._fail(pdf_path, f"Errore estrazione: {e}")

        if cancel_event.is_set():
            return False, self.cost_tracker.get_totals(), None

        cost_info = self.cost_tracker.get_totals()
        try:
            output_files, primary_output_files, attachment_output_files = (
                self._write_outputs(
                    pdf_path, ocr_result, extractions, email_attachment_docs,
                )
            )
        except Exception as e:
            return self._fail(pdf_path, f"Errore scrittura output: {e}")

        self.emit(OutputWrittenEvent(file_paths=output_files))

        renamed_pdf_path = pdf_path
        renamed_output_files = list(output_files)
        if self.config.rename_files:
            rename_output_files = (
                primary_output_files if email_attachment_docs else output_files
            )
            if defer_rename:
                if deferred_renames is not None:
                    deferred_renames.append({
                        "doc_id": len(deferred_renames) + 1,
                        "pdf_path": pdf_path,
                        "output_files": list(rename_output_files),
                        "ocr_text": ocr_result.combined_text,
                        "original_name": pdf_path.name,
                    })
                    self.emit(LogEvent(
                        message=f"Rinomina pianificata dopo OCR batch: {pdf_path.name}"
                    ))
            else:
                rename_result = self.rename_coordinator.derive_immediate_rename(
                    ocr_result.combined_text,
                    pdf_path.name,
                    rename_history,
                )
                renamed_pdf_path, renamed_primary = self.rename_coordinator.rename_files(
                    pdf_path,
                    rename_output_files,
                    rename_result,
                    rename_history=rename_history,
                )
                renamed_output_files = (
                    renamed_primary + attachment_output_files
                    if email_attachment_docs
                    else renamed_primary
                )

        self.emit(PipelineCompleteEvent(
            pdf_path=renamed_pdf_path,
            success=True,
            output_files=renamed_output_files,
            cost_info=cost_info,
        ))
        self.emit(LogEvent(
            message=f"Completato: {pdf_path.name} -> {len(output_files)} file"
        ))
        return True, cost_info, (renamed_pdf_path, renamed_output_files)

    def _last_fail_result(self, pdf_path: Path) -> tuple[bool, dict, None]:
        cost_info = self.cost_tracker.get_totals()
        return False, cost_info, None

    def _acquire_text(
        self,
        pdf_path: Path,
        cancel_event: threading.Event,
    ) -> tuple[OCRResult, bool, bool] | None:
        suffix = pdf_path.suffix.lower()
        is_audio = suffix in AUDIO_EXTENSIONS
        is_image = suffix in IMAGE_EXTENSIONS
        name_lower = pdf_path.name.lower()
        is_tarball = name_lower.endswith((".tar.gz", ".tar.bz2", ".tar.xz"))
        is_pdf = (
            suffix not in DIRECT_READ_FORMATS
            and not is_image
            and not is_audio
            and not is_tarball
        )

        if is_audio:
            return self._acquire_audio(pdf_path, cancel_event)
        if is_image:
            return self._acquire_image(pdf_path, cancel_event, is_pdf=False, is_image=True)
        if not is_pdf:
            return self._acquire_direct_read(pdf_path, cancel_event, is_pdf=False, is_image=False)
        if not self.config.run_ocr:
            return self._acquire_sidecar(pdf_path, cancel_event)
        return self._acquire_pdf(pdf_path, cancel_event)

    def _acquire_audio(
        self,
        pdf_path: Path,
        cancel_event: threading.Event,
    ) -> tuple[OCRResult, bool, bool] | None:
        if not self.audio_transcriber:
            self._fail(
                pdf_path,
                "Chiave API Mistral non configurata. "
                "Inseriscila nelle Impostazioni → tab API.",
            )
            return None

        self.emit(LogEvent(
            message=(
                f"Avvio trascrizione audio: {pdf_path.name}  "
                f"[{self.audio_transcriber.model_id}]"
            )
        ))
        try:
            trans_result = self.audio_transcriber.transcribe(pdf_path)
        except AudioTranscriberError as e:
            self._fail(pdf_path, f"Errore trascrizione audio: {e}")
            return None
        except Exception as e:
            self._fail(pdf_path, f"Errore trascrizione audio: {e}")
            return None

        self.cost_tracker.add_call(
            model_id=self.audio_transcriber.model_id,
            input_tokens=trans_result["input_tokens"],
            output_tokens=trans_result["output_tokens"],
            phase="transcription",
        )
        ocr_result = self._make_ocr_result_from_text(pdf_path, trans_result["text"])
        self.emit(LogEvent(
            message=(
                f"Trascrizione audio completata: "
                f"{len(trans_result['text']):,} caratteri, "
                f"{trans_result['input_tokens'] + trans_result['output_tokens']:,} token"
            )
        ))
        return ocr_result, False, False

    def _acquire_image(
        self,
        pdf_path: Path,
        cancel_event: threading.Event,
        *,
        is_pdf: bool,
        is_image: bool,
    ) -> tuple[OCRResult, bool, bool] | None:
        self.emit(LogEvent(
            message=f"Avvio OCR immagine: {pdf_path.name}  [{self.config.ocr_model_id}]"
        ))
        try:
            ocr_result = self.ocr_pipeline.ocr_single_image(
                image_path=pdf_path,
                on_page_complete=self._on_ocr_page,
                cancel_event=cancel_event,
            )
        except Exception as e:
            self._fail(pdf_path, f"Errore OCR immagine: {e}")
            return None
        return ocr_result, is_pdf, is_image

    def _acquire_direct_read(
        self,
        pdf_path: Path,
        cancel_event: threading.Event,
        *,
        is_pdf: bool,
        is_image: bool,
    ) -> tuple[OCRResult, bool, bool] | None:
        try:
            ocr_result, pending = self.attachment_processor.read_text_file(
                pdf_path, cancel_event,
            )
            self._pending_email_attachment_docs = pending
        except Exception as e:
            self._fail(pdf_path, f"Errore lettura file: {e}")
            return None
        return ocr_result, is_pdf, is_image

    def _acquire_sidecar(
        self,
        pdf_path: Path,
        cancel_event: threading.Event,
    ) -> tuple[OCRResult, bool, bool] | None:
        sidecar = pdf_path.with_suffix(".txt")
        if not sidecar.exists():
            self._fail(
                pdf_path,
                f"OCR disabilitato ma nessun file sidecar trovato: "
                f"'{sidecar.name}' non esiste",
            )
            return None
        self.emit(LogEvent(
            message=f"OCR disabilitato: uso testo da '{sidecar.name}'"
        ))
        try:
            ocr_result, _ = self.attachment_processor.read_text_file(sidecar)
        except Exception as e:
            self._fail(pdf_path, f"Errore lettura sidecar: {e}")
            return None
        return ocr_result, True, False

    def _acquire_pdf(
        self,
        pdf_path: Path,
        cancel_event: threading.Event,
    ) -> tuple[OCRResult, bool, bool] | None:
        self.emit(LogEvent(
            message=f"Avvio OCR PDF: {pdf_path.name}  [{self.config.ocr_model_id}]"
        ))
        try:
            ocr_result = self.ocr_pipeline.process_pdf(
                pdf_path=pdf_path,
                on_page_complete=self._on_ocr_page,
                on_page_skipped=self._on_page_skipped,
                on_page_native_text=self._on_page_native_text,
                cancel_event=cancel_event,
            )
        except Exception as e:
            self._fail(pdf_path, f"Errore OCR: {e}")
            return None
        return ocr_result, True, False

    def _log_acquisition_summary(
        self,
        ocr_result: OCRResult,
        is_pdf: bool,
        is_image: bool,
    ) -> None:
        ocr_chars = len(ocr_result.combined_text)
        if (is_pdf or is_image) and self.config.run_ocr:
            native = ocr_result.native_text_pages
            ocr_pages = ocr_result.successful_pages - native
            summary = (
                f"OCR completato: {ocr_result.successful_pages}/{ocr_result.total_pages} "
                f"pagine, {ocr_chars:,} caratteri totali"
            )
            if native > 0:
                summary += f" | {native} pagine con testo nativo (OCR saltato)"
                if ocr_pages > 0:
                    summary += f", {ocr_pages} pagine OCR"
            self.emit(LogEvent(message=summary))

    def _write_outputs(
        self,
        pdf_path: Path,
        ocr_result: OCRResult,
        extractions: list[dict],
        email_attachment_docs: list[EmailAttachmentDocument],
    ) -> tuple[list[Path], list[Path], list[Path]]:
        should_write_md = "markdown" in self.config.output_formats
        should_write_json = "json" in self.config.output_formats

        markdown = (
            self.md_formatter.format(
                extractions=extractions,
                source_filename=pdf_path.name,
                total_pages=ocr_result.total_pages,
                ocr_text=(
                    ocr_result.combined_text
                    if self.config.include_ocr_text_in_output
                    else None
                ),
                cost_info=None,
            )
            if should_write_md
            else None
        )
        json_content = (
            self.json_formatter.format(
                extractions=extractions,
                source_filename=pdf_path.name,
                total_pages=ocr_result.total_pages,
                ocr_text=(
                    ocr_result.combined_text
                    if self.config.include_ocr_text_in_output
                    else None
                ),
                cost_info=None,
            )
            if should_write_json
            else None
        )

        if self.config.output_mode == "sottocartella":
            per_file_dir = pdf_path.parent / self.config.output_subfolder_name
            per_file_dir.mkdir(parents=True, exist_ok=True)
            writer = OutputWriter(per_file_dir)
        else:
            writer = self.writer

        primary_output_files = writer.write(
            pdf_path=pdf_path,
            markdown=markdown,
            json_content=json_content,
        )
        output_files = list(primary_output_files)
        attachment_output_files: list[Path] = []

        for attachment_doc in email_attachment_docs:
            attachment_markdown = self.md_formatter.format(
                extractions=attachment_doc.extractions,
                source_filename=attachment_doc.filename,
                total_pages=1,
                ocr_text=(
                    attachment_doc.text
                    if self.config.include_ocr_text_in_output
                    else None
                ),
                cost_info=None,
            ) if should_write_md else None
            attachment_json = self.json_formatter.format(
                extractions=attachment_doc.extractions,
                source_filename=attachment_doc.filename,
                total_pages=1,
                ocr_text=(
                    attachment_doc.text
                    if self.config.include_ocr_text_in_output
                    else None
                ),
                cost_info=None,
            ) if should_write_json else None
            attachment_output_files.extend(writer.write(
                pdf_path=pdf_path,
                markdown=attachment_markdown,
                json_content=attachment_json,
                output_stem=attachment_output_stem(pdf_path.stem, attachment_doc),
            ))
        output_files.extend(attachment_output_files)
        return output_files, primary_output_files, attachment_output_files

    def _extract_entities_for_text(
        self,
        text: str,
        source_label: str = "documento",
    ) -> list[dict]:
        if not self.config.run_extraction or self.extractor is None:
            reason = (
                "LangExtract disabilitato"
                if not self.config.run_extraction
                else "schema: none"
            )
            self.emit(LogEvent(
                message=f"Estrazione strutturata saltata per {source_label} ({reason})"
            ))
            return []

        text_len = len(text)
        est_chunks = (
            math.ceil(text_len / self.config.max_char_buffer)
            if self.config.max_char_buffer > 0
            else 1
        )
        self.emit(ExtractionStartEvent(
            total_text_length=text_len,
            schema_name=self.config.active_schema,
        ))
        self.emit(LogEvent(
            message=(
                f"Avvio estrazione strutturata per {source_label}  "
                f"[{self.config.extraction_model_id}]  "
                f"schema={self.config.active_schema}  "
                f"{text_len:,} car.  ~{est_chunks} chunk  "
                f"pass={self.config.extraction_passes}  workers={self.config.max_workers}"
            )
        ))

        extraction_result = self.extractor.extract(text)
        result_dict = LegalExtractor.result_to_dict(extraction_result)
        extractions = result_dict["extractions"]

        self.emit(ExtractionCompleteEvent(extraction_count=len(extractions)))
        self.emit(LogEvent(
            message=f"Estratte {len(extractions)} entita' da {source_label}"
        ))
        return extractions

    def process_batch(
        self,
        pdf_paths: list[Path],
        cancel_event: threading.Event,
    ) -> None:
        successful = 0
        failed = 0
        total_cost_tracker = CostTracker()
        self._native_pages_batch = 0
        rename_history: list[dict] = []
        deferred_renames: list[dict] = []
        batch_outputs: list[tuple[Path, list[Path]]] = []
        defer_rename_enabled = (
            self.config.rename_files and self.config.rename_use_batch_context
        )

        for i, pdf_path in enumerate(pdf_paths):
            if cancel_event.is_set():
                break

            self.emit(LogEvent(
                message=f"Documento {i + 1}/{len(pdf_paths)}: {pdf_path.name}"
            ))

            success, _cost_info, batch_doc = self.process_single(
                pdf_path,
                cancel_event,
                rename_history=rename_history,
                defer_rename=defer_rename_enabled,
                deferred_renames=deferred_renames,
            )

            total_cost_tracker.merge_from(self.cost_tracker)

            if success:
                successful += 1
                if batch_doc and not defer_rename_enabled:
                    batch_outputs.append(batch_doc)
            else:
                failed += 1

        if (
            self.config.rename_files
            and self.config.rename_use_batch_context
            and not cancel_event.is_set()
            and deferred_renames
        ):
            self.rename_coordinator.run_deferred_renames(
                deferred_renames=deferred_renames,
                rename_history=rename_history,
                cancel_event=cancel_event,
            )
            for item in deferred_renames:
                batch_outputs.append((item["pdf_path"], item["output_files"]))

        final_check_result = None
        if (
            self.config.final_error_check
            and not cancel_event.is_set()
            and batch_outputs
        ):
            final_check_result = self._run_final_check(
                batch_outputs, total_cost_tracker,
            )

        total_cost_info = total_cost_tracker.get_totals()
        total = total_cost_info.get("total", {})
        ocr_cost = total_cost_info.get("ocr", {})
        ext_cost = total_cost_info.get("extraction", {})

        self.emit(LogEvent(
            message=f"Conversione completata: {successful} riusciti, {failed} falliti"
        ))
        self.emit(LogEvent(message="Resoconto totale conversione:"))
        self.emit(LogEvent(
            message=(
                f"  - Token utilizzati: {total.get('input_tokens', 0):,} input + "
                f"{total.get('output_tokens', 0):,} output"
            )
        ))
        self.emit(LogEvent(
            message=f"  - Costo OCR: ${ocr_cost.get('cost_usd', 0):.4f}"
        ))
        if ext_cost.get("cost_usd", 0) > 0:
            self.emit(LogEvent(
                message=(
                    f"  - Costo estrazione: ~${ext_cost.get('cost_usd', 0):.4f} (stimato)"
                )
            ))
        trans_cost = total_cost_info.get("transcription", {})
        if trans_cost.get("cost_usd", 0) > 0:
            self.emit(LogEvent(
                message=(
                    f"  - Costo trascrizione audio: "
                    f"~${trans_cost.get('cost_usd', 0):.4f} (stimato)"
                )
            ))
        final_check_cost = total_cost_info.get("final_check", {})
        if final_check_cost.get("cost_usd", 0) > 0:
            self.emit(LogEvent(
                message=(
                    f"  - Costo check finale: "
                    f"${final_check_cost.get('cost_usd', 0):.4f}"
                )
            ))
        self.emit(LogEvent(
            message=f"  - Costo totale: ${total.get('cost_usd', 0):.4f}"
        ))
        if self._native_pages_batch > 0:
            self.emit(LogEvent(
                message=(
                    f"  - Pagine con testo nativo (OCR saltato): "
                    f"{self._native_pages_batch}"
                )
            ))

        self.emit(BatchCompleteEvent(
            total_pdfs=len(pdf_paths),
            successful=successful,
            failed=failed,
            final_check_failed=(
                final_check_result is not None
                and not final_check_result.passed
                and not final_check_result.check_failed_technically
            ),
            final_check_issue_count=(
                len(final_check_result.issues) if final_check_result else 0
            ),
        ))

    def _run_final_check(
        self,
        batch_outputs: list[tuple[Path, list[Path]]],
        total_cost_tracker: CostTracker,
    ):
        from config.defaults import DEFAULT_FINAL_CHECK_PROMPT, PRICING

        md_documents: list[tuple[str, str]] = []
        affected_pdf_paths: list[Path] = []

        for input_path, output_files in batch_outputs:
            affected_pdf_paths.append(input_path)
            for output_file in output_files:
                if output_file.suffix.lower() != ".md" or not output_file.exists():
                    continue
                try:
                    content = output_file.read_text(encoding="utf-8", errors="replace")
                except OSError as e:
                    self.emit(LogEvent(
                        message=(
                            f"Check finale: impossibile leggere "
                            f"'{output_file.name}': {e}"
                        ),
                        level="WARNING",
                    ))
                    continue
                md_documents.append((output_file.name, content))

        if not md_documents:
            self.emit(LogEvent(
                message="Check finale errori saltato: nessun Markdown disponibile",
                level="WARNING",
            ))
            return None

        self.emit(LogEvent(
            message=(
                f"Avvio check finale errori su {len(md_documents)} file Markdown  "
                f"[{self.config.ocr_model_id}]"
            )
        ))

        result = run_final_error_check(
            md_documents=md_documents,
            api_key=self.config.gemini_api_key,
            model_id=self.config.ocr_model_id,
            prompt_template=DEFAULT_FINAL_CHECK_PROMPT,
        )

        if result.input_tokens or result.output_tokens:
            total_cost_tracker.add_call(
                model_id=self.config.ocr_model_id,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                phase="final_check",
            )

        pricing = PRICING.get(self.config.ocr_model_id, {})
        cost_usd = (
            (result.input_tokens / 1_000_000) * pricing.get("input_per_1m", 0)
            + (result.output_tokens / 1_000_000) * pricing.get("output_per_1m", 0)
        )

        if result.check_failed_technically:
            self.emit(LogEvent(
                message=f"Check finale errori non eseguito: {result.error_message}",
                level="WARNING",
            ))
        elif result.passed:
            self.emit(LogEvent(message="Check Finale Errori Superato"))
        else:
            self.emit(LogEvent(
                message="Check Finale Errori FALLITO",
                level="WARNING",
            ))
            for issue in result.issues:
                self.emit(LogEvent(
                    message=(
                        f"  - [{issue.get('type', 'issue')}] "
                        f"{issue.get('file', '?')}: "
                        f"{issue.get('description', '')}"
                    ),
                    level="WARNING",
                ))
            if result.error_message and not result.issues:
                self.emit(LogEvent(
                    message=f"  - {result.error_message}",
                    level="WARNING",
                ))

        self.emit(FinalCheckCompleteEvent(
            passed=result.passed,
            issues=result.issues,
            error_message=result.error_message,
            affected_pdf_paths=affected_pdf_paths,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cost_usd=cost_usd,
            check_failed_technically=result.check_failed_technically,
        ))
        return result

    @staticmethod
    def _make_ocr_result_from_text(file_path: Path, text: str) -> OCRResult:
        return OCRResult(
            pdf_path=file_path,
            combined_text=text,
            total_pages=1,
            successful_pages=1,
        )

    def _on_ocr_page(self, page_num: int, total_pages: int, success: bool) -> None:
        cost = self.cost_tracker.get_last_call_cost()
        in_tok, out_tok = self.cost_tracker.get_last_call_tokens()

        self.emit(OCRProgressEvent(
            page_num=page_num,
            total_pages=total_pages,
            success=success,
            input_tokens=in_tok,
            output_tokens=out_tok,
            page_cost=cost,
        ))

        status = "OK" if success else "ERRORE"
        self.emit(LogEvent(
            message=(
                f"OCR pagina {page_num + 1}/{total_pages} [{status}] "
                f"- {in_tok + out_tok:,} token, ${cost:.4f}"
            )
        ))

    def _on_page_skipped(self, page_num: int, total_pages: int, reason: str) -> None:
        self.emit(PageSkippedEvent(
            page_num=page_num,
            total_pages=total_pages,
            reason=reason,
        ))
        self.emit(LogEvent(
            message=(
                f"Pagina {page_num + 1}/{total_pages} saltata "
                f"(nessun testo): {reason}"
            ),
            level="WARNING",
        ))

    def _on_page_native_text(
        self,
        page_num: int,
        total_pages: int,
        char_count: int,
        reason: str,
    ) -> None:
        self._native_pages_batch = getattr(self, "_native_pages_batch", 0) + 1
        self.emit(PageNativeTextEvent(
            page_num=page_num,
            total_pages=total_pages,
            char_count=char_count,
            reason=reason,
        ))
        self.emit(LogEvent(
            message=(
                f"Pagina {page_num + 1}/{total_pages}: testo nativo "
                f"({char_count:,} car.) — OCR saltato ({reason})"
            )
        ))

    def _on_extraction_progress(self, **kwargs) -> None:
        self.emit(ExtractionProgressEvent(**kwargs))
