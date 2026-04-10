"""Full pipeline orchestrator: PDF/TXT/EML -> OCR (PDF only) -> Extract -> Output."""

import email
import email.policy
import logging
import math
import tempfile
import threading
from pathlib import Path
from typing import Callable

from config.settings import AppConfig
from extraction.extractor import LegalExtractor
from extraction.schemas import get_schema_preset
from ocr.ocr_pipeline import OCRPipeline
from output.json_formatter import JSONFormatter
from output.markdown_formatter import MarkdownFormatter
from output.writer import OutputWriter
from pipeline.events import (
    BatchCompleteEvent,
    ErrorEvent,
    ExtractionCompleteEvent,
    ExtractionProgressEvent,
    ExtractionStartEvent,
    FileRenamedEvent,
    LogEvent,
    OCRProgressEvent,
    OutputWrittenEvent,
    PageNativeTextEvent,
    PageSkippedEvent,
    PipelineCompleteEvent,
    PipelineEvent,
)
from utils.cost_tracker import CostTracker
from utils.file_renamer import (
    build_new_filepath, derive_filename_from_llm, rename_file,
)

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".tiff", ".tif", ".bmp", ".gif")
AUDIO_EXTENSIONS = (".mp3", ".wav", ".flac", ".m4a", ".ogg")


class DocumentProcessor:
    """Runs the full pipeline: PDF -> OCR -> Extract -> Output."""

    def __init__(
        self,
        config: AppConfig,
        event_callback: Callable[[PipelineEvent], None],
    ):
        self.config = config
        self.emit = event_callback
        self.cost_tracker = CostTracker()

        self.ocr_pipeline = OCRPipeline(config, self.cost_tracker)

        from ocr.audio_transcriber import AudioTranscriber
        self.audio_transcriber = (
            AudioTranscriber(config.mistral_api_key)
            if config.mistral_api_key else None
        )

        schema = get_schema_preset(config.active_schema)
        # Apply custom prompt override if the user edited the schema
        if schema and config.custom_schema_prompts.get(config.active_schema):
            schema.prompt_description = config.custom_schema_prompts[config.active_schema]
        self.extractor = LegalExtractor(config, schema, self.cost_tracker) if schema else None
        if self.extractor:
            self.extractor.set_progress_callback(self._on_extraction_progress)

        self.md_formatter = MarkdownFormatter()
        self.json_formatter = JSONFormatter()

        # Build the fixed output directory for "cartella" mode.
        # "accanto" and "sottocartella" are resolved per-file in process_single().
        if config.output_mode == "cartella" and config.output_directory:
            self._fixed_output_dir: Path | None = Path(config.output_directory)
        else:
            self._fixed_output_dir = None

        self.writer = OutputWriter(self._fixed_output_dir)

    def process_single(
        self,
        pdf_path: Path,
        cancel_event: threading.Event,
    ) -> tuple[bool, dict]:
        """Process one document through the full pipeline.

        PDF files go through OCR; TXT, EML and MSG files are read directly.

        Returns:
            Tuple of (success: bool, cost_info: dict)
        """
        self.cost_tracker.reset()
        self.emit(LogEvent(message=f"Inizio elaborazione: {pdf_path.name}"))

        # Phase 1: Text acquisition (OCR for PDF/image, direct read for TXT/EML/MSG,
        #          or sidecar .txt if OCR is disabled for a PDF)
        suffix = pdf_path.suffix.lower()
        is_audio = suffix in AUDIO_EXTENSIONS
        is_image = suffix in IMAGE_EXTENSIONS
        is_pdf = suffix not in (".txt", ".eml", ".msg", ".md", ".docx", ".html", ".htm", ".rtf") and not is_image and not is_audio

        if is_audio:
            if not self.audio_transcriber:
                self.emit(ErrorEvent(
                    error_message=(
                        "Chiave API Mistral non configurata. "
                        "Inseriscila nelle Impostazioni → tab API."
                    ),
                    recoverable=False,
                ))
                cost_info = self.cost_tracker.get_totals()
                self.emit(PipelineCompleteEvent(
                    pdf_path=pdf_path, success=False,
                    cost_info=cost_info,
                ))
                return False, cost_info

            self.emit(LogEvent(message=f"Avvio trascrizione audio: {pdf_path.name}"))
            try:
                from ocr.audio_transcriber import AudioTranscriberError
                trans_result = self.audio_transcriber.transcribe(pdf_path)
            except Exception as e:
                self.emit(ErrorEvent(
                    error_message=f"Errore trascrizione audio: {e}",
                    recoverable=False,
                ))
                cost_info = self.cost_tracker.get_totals()
                self.emit(PipelineCompleteEvent(
                    pdf_path=pdf_path, success=False,
                    cost_info=cost_info,
                ))
                return False, cost_info

            self.cost_tracker.add_call(
                model_id=self.audio_transcriber.model_id,
                input_tokens=trans_result["input_tokens"],
                output_tokens=trans_result["output_tokens"],
                phase="transcription",
            )
            ocr_result = self._make_ocr_result_from_text(
                pdf_path, trans_result["text"]
            )
            self.emit(LogEvent(
                message=(
                    f"Trascrizione audio completata: "
                    f"{len(trans_result['text']):,} caratteri, "
                    f"{trans_result['input_tokens'] + trans_result['output_tokens']:,} token"
                )
            ))

        elif is_image:
            try:
                ocr_result = self.ocr_pipeline.ocr_single_image(
                    image_path=pdf_path,
                    on_page_complete=self._on_ocr_page,
                    cancel_event=cancel_event,
                )
            except Exception as e:
                self.emit(ErrorEvent(
                    error_message=f"Errore OCR immagine: {e}",
                    recoverable=False,
                ))
                cost_info = self.cost_tracker.get_totals()
                self.emit(PipelineCompleteEvent(
                    pdf_path=pdf_path, success=False,
                    cost_info=cost_info,
                ))
                return False, cost_info

        elif not is_pdf:
            # TXT / EML / MSG: always read directly, OCR flag is irrelevant
            try:
                ocr_result = self._read_text_file(pdf_path, cancel_event)
            except Exception as e:
                self.emit(ErrorEvent(
                    error_message=f"Errore lettura file: {e}",
                    recoverable=False,
                ))
                cost_info = self.cost_tracker.get_totals()
                self.emit(PipelineCompleteEvent(
                    pdf_path=pdf_path, success=False,
                    cost_info=cost_info,
                ))
                return False, cost_info

        elif not self.config.run_ocr:
            # OCR disabled on a PDF: look for a sidecar .txt file
            sidecar = pdf_path.with_suffix(".txt")
            if sidecar.exists():
                self.emit(LogEvent(
                    message=f"OCR disabilitato: uso testo da '{sidecar.name}'"
                ))
                try:
                    ocr_result = self._read_text_file(sidecar)
                except Exception as e:
                    self.emit(ErrorEvent(
                        error_message=f"Errore lettura sidecar: {e}",
                        recoverable=False,
                    ))
                    cost_info = self.cost_tracker.get_totals()
                    self.emit(PipelineCompleteEvent(
                        pdf_path=pdf_path, success=False,
                        cost_info=cost_info,
                    ))
                    return False, cost_info
            else:
                self.emit(ErrorEvent(
                    error_message=(
                        f"OCR disabilitato ma nessun file sidecar trovato: "
                        f"'{sidecar.name}' non esiste"
                    ),
                    recoverable=False,
                ))
                cost_info = self.cost_tracker.get_totals()
                self.emit(PipelineCompleteEvent(
                    pdf_path=pdf_path, success=False,
                    cost_info=cost_info,
                ))
                return False, cost_info

        else:
            # Normal PDF OCR
            try:
                ocr_result = self.ocr_pipeline.process_pdf(
                    pdf_path=pdf_path,
                    on_page_complete=self._on_ocr_page,
                    on_page_skipped=self._on_page_skipped,
                    on_page_native_text=self._on_page_native_text,
                    cancel_event=cancel_event,
                )
            except Exception as e:
                self.emit(ErrorEvent(
                    error_message=f"Errore OCR: {e}",
                    recoverable=False,
                ))
                cost_info = self.cost_tracker.get_totals()
                self.emit(PipelineCompleteEvent(
                    pdf_path=pdf_path, success=False,
                    cost_info=cost_info,
                ))
                return False, cost_info

        if cancel_event.is_set():
            self.emit(LogEvent(message="Elaborazione annullata", level="WARNING"))
            return False, self.cost_tracker.get_totals()

        # Log text acquisition summary
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

        if not ocr_result.combined_text.strip():
            self.emit(ErrorEvent(
                error_message="Nessun testo estratto dall'OCR",
                recoverable=False,
            ))
            cost_info = self.cost_tracker.get_totals()
            self.emit(PipelineCompleteEvent(
                pdf_path=pdf_path, success=False,
                cost_info=cost_info,
            ))
            return False, cost_info

        # Phase 2: Extraction (skip if schema is "none" OR extraction is disabled)
        if not self.config.run_extraction or self.extractor is None:
            reason = "LangExtract disabilitato" if not self.config.run_extraction else "schema: none"
            self.emit(LogEvent(
                message=f"Estrazione strutturata saltata ({reason})"
            ))
            extractions = []
        else:
            text_len = len(ocr_result.combined_text)
            est_chunks = math.ceil(text_len / self.config.max_char_buffer) if self.config.max_char_buffer > 0 else 1
            self.emit(ExtractionStartEvent(
                total_text_length=text_len,
                schema_name=self.config.active_schema,
            ))
            self.emit(LogEvent(
                message=(
                    f"Inizio estrazione strutturata: {text_len:,} caratteri, "
                    f"~{est_chunks} chunk (buffer={self.config.max_char_buffer}), "
                    f"modello={self.config.extraction_model_id}, "
                    f"schema={self.config.active_schema}, "
                    f"pass={self.config.extraction_passes}, "
                    f"workers={self.config.max_workers}"
                )
            ))

            try:
                extraction_result = self.extractor.extract(ocr_result.combined_text)
                result_dict = LegalExtractor.result_to_dict(extraction_result)
                extractions = result_dict["extractions"]
            except Exception as e:
                self.emit(ErrorEvent(
                    error_message=f"Errore estrazione: {e}",
                    recoverable=False,
                ))
                self.emit(PipelineCompleteEvent(
                    pdf_path=pdf_path, success=False,
                    cost_info=self.cost_tracker.get_totals(),
                ))
                return False, self.cost_tracker.get_totals()

            self.emit(ExtractionCompleteEvent(extraction_count=len(extractions)))
            self.emit(LogEvent(message=f"Estratte {len(extractions)} entita'"))

        if cancel_event.is_set():
            return False, self.cost_tracker.get_totals()

        # Phase 3: Format and write output
        cost_info = self.cost_tracker.get_totals()
        output_files = []

        markdown = None
        json_data = None

        # Derive filename via LLM once, reused for both MD header and actual rename.
        _rename_result: tuple[str, str] | None = None
        if self.config.rename_files:
            from config.defaults import DEFAULT_RENAME_PROMPT
            rename_prompt = self.config.rename_prompt or DEFAULT_RENAME_PROMPT
            _rename_result = derive_filename_from_llm(
                ocr_text=ocr_result.combined_text,
                api_key=self.config.gemini_api_key,
                model_id=self.config.ocr_model_id,
                rename_prompt=rename_prompt,
                original_filename=pdf_path.name,
            )

        if "markdown" in self.config.output_formats:
            # When renaming is enabled, use the future renamed filename in the MD
            # header so the title matches the file that ends up on disk.
            header_filename = pdf_path.name
            if _rename_result:
                _date_str, _description = _rename_result
                header_filename = f"{_date_str} - {_description}{pdf_path.suffix}"

            markdown = self.md_formatter.format(
                extractions=extractions,
                source_filename=header_filename,
                total_pages=ocr_result.total_pages,
                ocr_text=ocr_result.combined_text if self.config.include_ocr_text_in_output else None,
                cost_info=None,
            )

        # Resolve per-file output directory based on output_mode.
        if self.config.output_mode == "sottocartella":
            per_file_dir = pdf_path.parent / self.config.output_subfolder_name
            per_file_dir.mkdir(parents=True, exist_ok=True)
            writer = OutputWriter(per_file_dir)
        else:
            # "accanto": OutputWriter(None) writes next to source file
            # "cartella": self.writer already points to the fixed dir
            writer = self.writer

        try:
            output_files = writer.write(
                pdf_path=pdf_path,
                markdown=markdown,
                json_data=json_data,
            )
        except Exception as e:
            self.emit(ErrorEvent(
                error_message=f"Errore scrittura output: {e}",
                recoverable=False,
            ))
            self.emit(PipelineCompleteEvent(
                pdf_path=pdf_path, success=False,
                cost_info=cost_info,
            ))
            return False, cost_info

        self.emit(OutputWrittenEvent(file_paths=output_files))

        # Phase 4: Rename files based on extracted content (if enabled)
        renamed_pdf_path = pdf_path
        renamed_output_files = list(output_files)
        if self.config.rename_files and _rename_result:
            renamed_pdf_path, renamed_output_files = self._rename_files(
                pdf_path, output_files, _rename_result,
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
        return True, cost_info

    def process_batch(
        self,
        pdf_paths: list[Path],
        cancel_event: threading.Event,
    ) -> None:
        """Process multiple PDFs sequentially."""
        successful = 0
        failed = 0
        total_cost_tracker = CostTracker()
        self._native_pages_batch = 0

        for i, pdf_path in enumerate(pdf_paths):
            if cancel_event.is_set():
                break

            self.emit(LogEvent(
                message=f"Documento {i + 1}/{len(pdf_paths)}: {pdf_path.name}"
            ))

            success, cost_info = self.process_single(pdf_path, cancel_event)
            
            # Accumula i costi nel total_cost_tracker (salva prima che vengano resettati)
            for call in self.cost_tracker._calls:
                total_cost_tracker.add_call(
                    model_id=call.model_id,
                    input_tokens=call.input_tokens,
                    output_tokens=call.output_tokens,
                    phase=call.phase,
                )
            
            if success:
                successful += 1
            else:
                failed += 1

        # Mostra il resoconto totale alla fine
        total_cost_info = total_cost_tracker.get_totals()
        total = total_cost_info.get("total", {})
        ocr_cost = total_cost_info.get("ocr", {})
        ext_cost = total_cost_info.get("extraction", {})

        self.emit(LogEvent(
            message=f"Conversione completata: {successful} riusciti, {failed} falliti"
        ))
        self.emit(LogEvent(
            message=f"Resoconto totale conversione:"
        ))
        self.emit(LogEvent(
            message=f"  - Token utilizzati: {total.get('input_tokens', 0):,} input + "
                    f"{total.get('output_tokens', 0):,} output"
        ))
        self.emit(LogEvent(
            message=f"  - Costo OCR: ${ocr_cost.get('cost_usd', 0):.4f}"
        ))
        if ext_cost.get("cost_usd", 0) > 0:
            self.emit(LogEvent(
                message=f"  - Costo estrazione: ~${ext_cost.get('cost_usd', 0):.4f} (stimato)"
            ))
        trans_cost = total_cost_info.get("transcription", {})
        if trans_cost.get("cost_usd", 0) > 0:
            self.emit(LogEvent(
                message=f"  - Costo trascrizione audio: ~${trans_cost.get('cost_usd', 0):.4f} (stimato)"
            ))
        self.emit(LogEvent(
            message=f"  - Costo totale: ${total.get('cost_usd', 0):.4f}"
        ))
        if self._native_pages_batch > 0:
            self.emit(LogEvent(
                message=f"  - Pagine con testo nativo (OCR saltato): {self._native_pages_batch}"
            ))

        self.emit(BatchCompleteEvent(
            total_pdfs=len(pdf_paths),
            successful=successful,
            failed=failed,
        ))

    def _rename_files(
        self,
        pdf_path: Path,
        output_files: list[Path],
        rename_result: tuple[str, str],
    ) -> tuple[Path, list[Path]]:
        """Rename PDF source and/or MD output using the pre-computed filename parts.

        Returns:
            Tuple of (possibly_renamed_pdf_path, possibly_renamed_output_files).
        """
        date_str, description = rename_result
        self.emit(LogEvent(
            message=f"Rinomina file: data={date_str}, descrizione='{description}'"
        ))

        renamed_pdf = pdf_path
        renamed_outputs = list(output_files)

        # Rename output MD file
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
                    except OSError as e:
                        self.emit(LogEvent(
                            message=f"Errore rinomina MD: {e}", level="ERROR",
                        ))

        # Rename source PDF
        if self.config.rename_mode in ("pdf", "both"):
            new_pdf_path = build_new_filepath(pdf_path, date_str, description)
            try:
                actual_pdf_path = rename_file(pdf_path, new_pdf_path)
                self.emit(FileRenamedEvent(
                    original_path=pdf_path, new_path=actual_pdf_path, file_type="pdf",
                ))
                renamed_pdf = actual_pdf_path
            except OSError as e:
                self.emit(LogEvent(
                    message=f"Errore rinomina PDF: {e}", level="ERROR",
                ))

        return renamed_pdf, renamed_outputs

    def _on_ocr_page(self, page_num: int, total_pages: int, success: bool) -> None:
        """Callback from OCR pipeline after each page."""
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
        """Callback from OCR pipeline when a page returns empty text."""
        self.emit(PageSkippedEvent(
            page_num=page_num,
            total_pages=total_pages,
            reason=reason,
        ))

    def _on_page_native_text(
        self, page_num: int, total_pages: int, char_count: int, reason: str
    ) -> None:
        """Callback from OCR pipeline when a page has native text (OCR skipped)."""
        # Increment batch counter (attribute may not exist if called outside process_batch)
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
                f"({char_count:,} car.) - OCR saltato"
            )
        ))

    def _on_extraction_progress(self, **kwargs) -> None:
        """Callback from LegalExtractor as batches of chunks complete."""
        self.emit(ExtractionProgressEvent(**kwargs))

    @staticmethod
    def _make_ocr_result_from_text(file_path: Path, text: str):
        """Wrap a plain text string into an OCRResult (1 page, no OCR)."""
        from ocr.ocr_pipeline import OCRResult
        return OCRResult(
            pdf_path=file_path,
            combined_text=text,
            total_pages=1,
            successful_pages=1,
        )

    def _read_text_file(self, file_path: Path, cancel_event: threading.Event | None = None):
        """Read text content directly from TXT, EML or MSG files (no OCR needed)."""
        from ocr.ocr_pipeline import OCRResult

        suffix = file_path.suffix.lower()
        if suffix == ".eml":
            text = self._extract_eml_text(file_path, cancel_event)
            self.emit(LogEvent(message="File EML letto direttamente (OCR non necessario)"))
        elif suffix == ".msg":
            text = self._extract_msg_text(file_path, cancel_event)
            self.emit(LogEvent(message="File MSG letto direttamente (OCR non necessario)"))
        elif suffix == ".docx":
            text = self._extract_docx_text(file_path)
            self.emit(LogEvent(message=f"File DOCX letto direttamente (OCR non necessario)"))
        elif suffix in (".html", ".htm"):
            text = self._extract_html_text(file_path)
            self.emit(LogEvent(message=f"File HTML letto direttamente (OCR non necessario)"))
        elif suffix == ".rtf":
            text = self._extract_rtf_text(file_path)
            self.emit(LogEvent(message=f"File RTF letto direttamente (OCR non necessario)"))
        elif suffix == ".md":
            text = file_path.read_text(encoding="utf-8", errors="replace")
            self.emit(LogEvent(message=f"File MD letto direttamente (OCR non necessario)"))
        else:
            text = file_path.read_text(encoding="utf-8", errors="replace")
            self.emit(LogEvent(message=f"File TXT letto direttamente (OCR non necessario)"))

        return OCRResult(
            pdf_path=file_path,
            combined_text=text,
            total_pages=1,
            successful_pages=1,
        )

    def _extract_eml_text(
        self, file_path: Path, cancel_event: threading.Event | None = None
    ) -> str:
        """Extract text from an EML file, including headers, body and OCR of attachments."""
        msg = email.message_from_bytes(
            file_path.read_bytes(),
            policy=email.policy.default,
        )

        parts = []

        # Headers
        for header in ("date", "from", "to", "cc", "subject"):
            value = msg.get(header, "").strip()
            if value:
                parts.append(f"{header.capitalize()}: {value}")
        if parts:
            parts.append("")

        # Body (only non-attachment text/plain parts)
        for part in msg.walk():
            if (
                part.get_content_type() == "text/plain"
                and part.get_content_disposition() != "attachment"
            ):
                try:
                    body = part.get_content()
                    if body and body.strip():
                        parts.append(body)
                except Exception:
                    pass

        # Collect attachments
        att_list: list[tuple[str, bytes]] = []
        for part in msg.walk():
            if part.get_content_disposition() == "attachment":
                raw_name = part.get_filename() or f"allegato_{len(att_list) + 1}"
                payload = part.get_payload(decode=True)
                if payload:
                    att_list.append((raw_name, payload))

        if att_list:
            names = ", ".join(n for n, _ in att_list)
            self.emit(LogEvent(
                message=f"Trovati {len(att_list)} allegati in {file_path.name}: {names}"
            ))
            with tempfile.TemporaryDirectory() as tmpdir:
                for i, (name, data) in enumerate(att_list, 1):
                    if cancel_event and cancel_event.is_set():
                        break
                    att_path = Path(tmpdir) / name
                    att_path.write_bytes(data)
                    self.emit(LogEvent(
                        message=f"Elaborazione allegato {i}/{len(att_list)}: {name}"
                    ))
                    att_text = self._process_attachment(att_path, cancel_event)
                    if att_text:
                        parts.append(f"\n\n--- ALLEGATO {i}: {name} ---\n\n")
                        parts.append(att_text)

        return "\n".join(parts)

    def _extract_msg_text(
        self, file_path: Path, cancel_event: threading.Event | None = None
    ) -> str:
        """Extract text from an Outlook MSG file, including headers, body and OCR of attachments."""
        import extract_msg

        parts = []
        att_list: list[tuple[str, bytes]] = []

        with extract_msg.openMsg(file_path) as msg:
            header_map = [
                ("Date", msg.date),
                ("From", msg.sender),
                ("To", msg.to),
                ("Cc", msg.cc),
                ("Subject", msg.subject),
            ]
            for label, value in header_map:
                if value and str(value).strip():
                    parts.append(f"{label}: {value}")
            if parts:
                parts.append("")

            body = msg.body
            if body and body.strip():
                parts.append(body)

            for attachment in msg.attachments:
                name = (
                    getattr(attachment, "longFilename", None)
                    or getattr(attachment, "shortFilename", None)
                    or f"allegato_{len(att_list) + 1}"
                )
                data = getattr(attachment, "data", None)
                if data:
                    att_list.append((name, data))

        if att_list:
            names = ", ".join(n for n, _ in att_list)
            self.emit(LogEvent(
                message=f"Trovati {len(att_list)} allegati in {file_path.name}: {names}"
            ))
            with tempfile.TemporaryDirectory() as tmpdir:
                for i, (name, data) in enumerate(att_list, 1):
                    if cancel_event and cancel_event.is_set():
                        break
                    att_path = Path(tmpdir) / name
                    att_path.write_bytes(data)
                    self.emit(LogEvent(
                        message=f"Elaborazione allegato {i}/{len(att_list)}: {name}"
                    ))
                    att_text = self._process_attachment(att_path, cancel_event)
                    if att_text:
                        parts.append(f"\n\n--- ALLEGATO {i}: {name} ---\n\n")
                        parts.append(att_text)

        return "\n".join(parts)

    def _process_attachment(
        self, att_path: Path, cancel_event: threading.Event | None = None
    ) -> str:
        """Process a single attachment and return its text content.

        PDFs and images go through OCR; other supported formats are read directly.
        Unsupported types are skipped with a warning.
        """
        _cancel = cancel_event or threading.Event()
        suffix = att_path.suffix.lower()
        try:
            if suffix == ".pdf":
                result = self.ocr_pipeline.process_pdf(
                    pdf_path=att_path,
                    on_page_complete=self._on_ocr_page,
                    on_page_skipped=self._on_page_skipped,
                    on_page_native_text=self._on_page_native_text,
                    cancel_event=_cancel,
                )
                return result.combined_text
            elif suffix in IMAGE_EXTENSIONS:
                result = self.ocr_pipeline.ocr_single_image(
                    image_path=att_path,
                    on_page_complete=self._on_ocr_page,
                    cancel_event=_cancel,
                )
                return result.combined_text
            elif suffix == ".docx":
                return self._extract_docx_text(att_path)
            elif suffix in (".html", ".htm"):
                return self._extract_html_text(att_path)
            elif suffix == ".rtf":
                return self._extract_rtf_text(att_path)
            elif suffix in (".txt", ".md"):
                return att_path.read_text(encoding="utf-8", errors="replace")
            else:
                self.emit(LogEvent(
                    message=f"Allegato '{att_path.name}' ({suffix}) non supportato - saltato",
                    level="WARNING",
                ))
                return ""
        except Exception as e:
            self.emit(LogEvent(
                message=f"Errore elaborazione allegato '{att_path.name}': {e}",
                level="ERROR",
            ))
            return ""

    @staticmethod
    def _extract_docx_text(file_path: Path) -> str:
        """Extract plain-text from DOCX files using python-docx."""
        import docx
        doc = docx.Document(file_path)
        parts = []
        for p in doc.paragraphs:
            if p.text:
                parts.append(p.text)
        return "\n".join(parts)

    @staticmethod
    def _extract_html_text(file_path: Path) -> str:
        """Extract plain-text and metadata from HTML files using beautifulsoup4."""
        import re
        from bs4 import BeautifulSoup
        
        html_content = file_path.read_text(encoding="utf-8", errors="replace")
        parts = []
        
        # 1. Try to find the "saved from url" comment (often added by browsers like Chrome/Edge)
        saved_url_match = re.search(r'<!--\s*saved from url=\(\d+\)(.*?)\s*-->', html_content)
        if saved_url_match:
            parts.append(f"Source URL: {saved_url_match.group(1).strip()}")
            
        soup = BeautifulSoup(html_content, "html.parser")
        
        # 2. Extract Title
        if soup.title and soup.title.string:
            parts.append(f"Title: {soup.title.string.strip()}")
            
        # 3. Extract common meta tags
        for meta_name in ["description", "author", "keywords"]:
            meta_tag = soup.find("meta", attrs={"name": lambda x: x and x.lower() == meta_name})
            if meta_tag and meta_tag.get("content"):
                parts.append(f"{meta_name.capitalize()}: {meta_tag.get('content').strip()}")
                
        # 4. Extract Canonical URL (if source URL wasn't found)
        canonical = soup.find("link", rel="canonical")
        if canonical and canonical.get("href") and not saved_url_match:
            parts.append(f"Canonical URL: {canonical.get('href').strip()}")
            
        if parts:
            parts.append("\n--- TESTO DEL SITO ---")
            
        # 5. Extract actual body text
        parts.append(soup.get_text(separator="\n", strip=True))
        
        return "\n".join(parts)

    @staticmethod
    def _extract_rtf_text(file_path: Path) -> str:
        """Extract plain-text from RTF files using striprtf."""
        from striprtf.striprtf import rtf_to_text
        rtf_content = file_path.read_text(encoding="utf-8", errors="replace")
        return rtf_to_text(rtf_content)
