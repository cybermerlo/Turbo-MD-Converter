"""Full pipeline orchestrator: PDF -> OCR -> Extract -> Output."""

import logging
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
    ExtractionStartEvent,
    LogEvent,
    OCRProgressEvent,
    OutputWrittenEvent,
    PipelineCompleteEvent,
    PipelineEvent,
)
from utils.cost_tracker import CostTracker

logger = logging.getLogger(__name__)


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

        schema = get_schema_preset(config.active_schema)
        self.extractor = LegalExtractor(config, schema, self.cost_tracker) if schema else None

        self.md_formatter = MarkdownFormatter()
        self.json_formatter = JSONFormatter()
        self.writer = OutputWriter(
            Path(config.output_directory) if config.output_directory else None
        )

    def process_single(
        self,
        pdf_path: Path,
        cancel_event: threading.Event,
    ) -> tuple[bool, dict]:
        """Process one PDF through the full pipeline.

        Returns:
            Tuple of (success: bool, cost_info: dict)
        """
        self.cost_tracker.reset()
        self.emit(LogEvent(message=f"Inizio elaborazione: {pdf_path.name}"))

        # Phase 1: OCR
        try:
            ocr_result = self.ocr_pipeline.process_pdf(
                pdf_path=pdf_path,
                on_page_complete=self._on_ocr_page,
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

        # Phase 2: Extraction (skip if schema is "none")
        if self.extractor is None:
            # No structured extraction - just use OCR text
            self.emit(LogEvent(
                message="Estrazione strutturata saltata (schema: none)"
            ))
            extractions = []
        else:
            self.emit(ExtractionStartEvent(
                total_text_length=len(ocr_result.combined_text),
                schema_name=self.config.active_schema,
            ))
            self.emit(LogEvent(
                message=f"Inizio estrazione strutturata ({len(ocr_result.combined_text)} caratteri)"
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
                return False

            self.emit(ExtractionCompleteEvent(extraction_count=len(extractions)))
            self.emit(LogEvent(message=f"Estratte {len(extractions)} entita'"))

        if cancel_event.is_set():
            return False

        # Phase 3: Format and write output
        cost_info = self.cost_tracker.get_totals()
        output_files = []

        markdown = None
        json_data = None

        if "markdown" in self.config.output_formats:
            markdown = self.md_formatter.format(
                extractions=extractions,
                source_filename=pdf_path.name,
                total_pages=ocr_result.total_pages,
                ocr_text=ocr_result.combined_text if self.config.include_ocr_text_in_output else None,
                cost_info=None,  # Non includere cost_info nell'output
            )

        if "json" in self.config.output_formats:
            extraction_model = self.config.extraction_model_id if self.extractor else ""
            json_data = self.json_formatter.format(
                extractions=extractions,
                source_filename=pdf_path.name,
                ocr_text=ocr_result.combined_text,
                total_pages=ocr_result.total_pages,
                ocr_model=self.config.ocr_model_id,
                extraction_model=extraction_model,
                cost_info=None,  # Non includere cost_info nell'output
            )

        try:
            output_files = self.writer.write(
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
            return False

        self.emit(OutputWrittenEvent(file_paths=output_files))
        self.emit(PipelineCompleteEvent(
            pdf_path=pdf_path,
            success=True,
            output_files=output_files,
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
            message=f"  - Costo totale stimato: ${total.get('cost_usd', 0):.4f}"
        ))

        self.emit(BatchCompleteEvent(
            total_pdfs=len(pdf_paths),
            successful=successful,
            failed=failed,
        ))

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
