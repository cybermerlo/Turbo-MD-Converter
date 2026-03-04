"""OCR pipeline orchestrator: PDF -> page-by-page OCR -> combined text."""

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from config.defaults import PAGE_SEPARATOR
from config.settings import AppConfig
from ocr.gemini_ocr import GeminiOCR, GeminiOCRError
from ocr.pdf_converter import PDFConverter
from utils.cost_tracker import CostTracker
from utils.retry import retry_with_backoff

logger = logging.getLogger(__name__)


@dataclass
class OCRPageResult:
    """Result of OCR for a single page."""
    page_num: int
    text: str
    success: bool
    error: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class OCRResult:
    """Result of OCR for an entire PDF."""
    pdf_path: Path
    page_results: list[OCRPageResult] = field(default_factory=list)
    combined_text: str = ""
    total_pages: int = 0
    successful_pages: int = 0


class OCRPipeline:
    """Orchestrates page-by-page OCR with progress callbacks."""

    def __init__(self, config: AppConfig, cost_tracker: CostTracker | None = None):
        self.converter = PDFConverter(
            dpi=config.page_dpi,
            jpeg_quality=config.jpeg_quality,
        )
        self.ocr = GeminiOCR(
            api_key=config.gemini_api_key,
            model_id=config.ocr_model_id,
            ocr_prompt=config.ocr_prompt,
        )
        self.cost_tracker = cost_tracker
        self.model_id = config.ocr_model_id

    def process_pdf(
        self,
        pdf_path: Path,
        on_page_complete: Callable[[int, int, bool], None] | None = None,
        on_page_skipped: Callable[[int, int, str], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> OCRResult:
        """Process all pages of a PDF sequentially.

        Args:
            pdf_path: Path to the PDF file.
            on_page_complete: Callback(page_num, total_pages, success) after each page.
            on_page_skipped: Callback(page_num, total_pages, reason) when page text is empty.
            cancel_event: Threading event to signal cancellation.

        Returns:
            OCRResult with all page texts and combined output.
        """
        total_pages = self.converter.get_page_count(pdf_path)
        logger.info("Inizio OCR di '%s' (%d pagine)", pdf_path.name, total_pages)

        result = OCRResult(pdf_path=pdf_path, total_pages=total_pages)
        page_texts = []

        for page_num, image_bytes in self.converter.iter_pages(pdf_path):
            # Check for cancellation
            if cancel_event and cancel_event.is_set():
                logger.info("OCR annullato dall'utente alla pagina %d", page_num + 1)
                break

            page_result = self._process_single_page(page_num, image_bytes)
            result.page_results.append(page_result)

            if page_result.success:
                result.successful_pages += 1
                page_texts.append(page_result.text)
                # Warn if page was processed but returned no text
                if not page_result.text.strip() and on_page_skipped:
                    logger.warning(
                        "⚠️  PAGINA %d SALTATA - Nessun testo estratto (possibile blocco RECITATION)",
                        page_num + 1,
                    )
                    on_page_skipped(page_num, total_pages, "Nessun testo estratto (RECITATION o pagina vuota)")
            else:
                page_texts.append(f"[Pagina {page_num + 1}: OCR non riuscito]")

            if on_page_complete:
                on_page_complete(page_num, total_pages, page_result.success)

        # Combine all page texts with separators
        parts = []
        for i, text in enumerate(page_texts):
            parts.append(PAGE_SEPARATOR.format(page_num=i + 1))
            parts.append(text)
        result.combined_text = "".join(parts).strip()

        logger.info(
            "OCR completato: %d/%d pagine riuscite",
            result.successful_pages, total_pages,
        )
        return result

    def _process_single_page(self, page_num: int, image_bytes: bytes) -> OCRPageResult:
        """Process a single page with retry logic."""

        def do_ocr():
            return self.ocr.ocr_page(image_bytes, page_num)

        def on_retry(attempt: int, exc: Exception):
            logger.warning(
                "Retry %d/3 per pagina %d: %s", attempt, page_num + 1, exc
            )

        try:
            ocr_result = retry_with_backoff(
                func=do_ocr,
                max_retries=3,
                base_delay=2.0,
                retryable_exceptions=(GeminiOCRError,),
                on_retry=on_retry,
            )

            # Track costs
            if self.cost_tracker:
                self.cost_tracker.add_call(
                    model_id=self.model_id,
                    input_tokens=ocr_result["input_tokens"],
                    output_tokens=ocr_result["output_tokens"],
                    phase="ocr",
                )

            return OCRPageResult(
                page_num=page_num,
                text=ocr_result["text"],
                success=True,
                input_tokens=ocr_result["input_tokens"],
                output_tokens=ocr_result["output_tokens"],
            )

        except GeminiOCRError as e:
            return OCRPageResult(
                page_num=page_num,
                text="",
                success=False,
                error=str(e),
            )
