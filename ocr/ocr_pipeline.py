"""OCR pipeline orchestrator: PDF -> page-by-page OCR -> combined text."""

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from config.defaults import PAGE_SEPARATOR
from config.settings import AppConfig
from ocr.gemini_ocr import GeminiOCR, GeminiOCRError
from ocr.page_analyzer import PageAnalyzer, PageType

# Supported image MIME types by extension
IMAGE_MIME_TYPES: dict[str, str] = {
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png":  "image/png",
    ".webp": "image/webp",
    ".tiff": "image/tiff",
    ".tif":  "image/tiff",
    ".bmp":  "image/bmp",
    ".gif":  "image/gif",
}
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
    skipped_ocr: bool = False  # True when native text extraction was used


@dataclass
class OCRResult:
    """Result of OCR for an entire PDF."""
    pdf_path: Path
    page_results: list[OCRPageResult] = field(default_factory=list)
    combined_text: str = ""
    total_pages: int = 0
    successful_pages: int = 0
    native_text_pages: int = 0  # Pages where OCR was skipped (native text detected)


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
        self.smart_text_detection = config.smart_text_detection
        self.page_analyzer = PageAnalyzer() if self.smart_text_detection else None

    def process_pdf(
        self,
        pdf_path: Path,
        on_page_complete: Callable[[int, int, bool], None] | None = None,
        on_page_skipped: Callable[[int, int, str], None] | None = None,
        on_page_native_text: Callable[[int, int, int, str], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> OCRResult:
        """Process all pages of a PDF sequentially.

        Args:
            pdf_path: Path to the PDF file.
            on_page_complete: Callback(page_num, total_pages, success) after each OCR page.
            on_page_skipped: Callback(page_num, total_pages, reason) when page text is empty.
            on_page_native_text: Callback(page_num, total_pages, char_count, reason) when
                native text is detected and OCR is skipped.
            cancel_event: Threading event to signal cancellation.

        Returns:
            OCRResult with all page texts and combined output.
        """
        total_pages = self.converter.get_page_count(pdf_path)
        logger.info(
            "Inizio OCR di '%s' (%d pagine, modello=%s, DPI=%d, rilevamento_testo=%s)",
            pdf_path.name, total_pages, self.model_id,
            self.converter.dpi,
            "attivo" if self.smart_text_detection else "disattivo",
        )

        result = OCRResult(pdf_path=pdf_path, total_pages=total_pages)
        page_texts = []

        for page_num, page in self.converter.iter_pages_raw(pdf_path):
            # Check for cancellation
            if cancel_event and cancel_event.is_set():
                logger.info("OCR annullato dall'utente alla pagina %d", page_num + 1)
                break

            if self.smart_text_detection and self.page_analyzer:
                analysis = self.page_analyzer.analyze_page(page)
                logger.info(
                    "Pagina %d/%d: %s",
                    page_num + 1, total_pages, analysis.reason,
                )

                if analysis.page_type == PageType.TEXT_NATIVE:
                    # Extract text directly — no Gemini API call needed
                    text = self.page_analyzer.extract_text(page)
                    page_result = OCRPageResult(
                        page_num=page_num,
                        text=text,
                        success=True,
                        skipped_ocr=True,
                    )
                    result.page_results.append(page_result)
                    result.successful_pages += 1
                    result.native_text_pages += 1
                    page_texts.append(text)

                    logger.info(
                        "Pagina %d/%d: testo nativo estratto (%d car.), OCR saltato",
                        page_num + 1, total_pages, len(text),
                    )
                    if on_page_native_text:
                        on_page_native_text(
                            page_num, total_pages,
                            analysis.text_char_count, analysis.reason,
                        )
                    continue  # Skip the OCR path entirely

                # SCANNED or MIXED — render to JPEG and send to Gemini
                image_bytes = self.converter.render_page(page)
            else:
                # Smart detection disabled: render every page normally
                image_bytes = self.converter.render_page(page)

            page_result = self._process_single_page(page_num, image_bytes)
            result.page_results.append(page_result)

            if page_result.success:
                result.successful_pages += 1
                page_texts.append(page_result.text)
                logger.info(
                    "Pagina %d/%d OK: %d caratteri, %d+%d token",
                    page_num + 1, total_pages, len(page_result.text),
                    page_result.input_tokens, page_result.output_tokens,
                )
                # Warn if page was processed but returned no text
                if not page_result.text.strip() and on_page_skipped:
                    logger.warning(
                        "⚠️  PAGINA %d SALTATA - Nessun testo estratto (possibile blocco RECITATION)",
                        page_num + 1,
                    )
                    on_page_skipped(page_num, total_pages, "Nessun testo estratto (RECITATION o pagina vuota)")
            else:
                logger.error(
                    "Pagina %d/%d ERRORE: %s",
                    page_num + 1, total_pages, page_result.error,
                )
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
            "OCR completato: %d/%d pagine riuscite (%d con testo nativo, OCR saltato)",
            result.successful_pages, total_pages, result.native_text_pages,
        )
        return result

    def ocr_single_image(
        self,
        image_path: Path,
        on_page_complete: Callable[[int, int, bool], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> OCRResult:
        """OCR a single image file (JPG, PNG, WEBP, TIFF, …) as one page.

        Args:
            image_path: Path to the image file.
            on_page_complete: Callback(page_num, total_pages, success).
            cancel_event: Threading event to signal cancellation.

        Returns:
            OCRResult with one page result.
        """
        mime_type = IMAGE_MIME_TYPES.get(image_path.suffix.lower(), "image/jpeg")
        logger.info(
            "OCR immagine '%s' (mime=%s, modello=%s)",
            image_path.name, mime_type, self.model_id,
        )
        result = OCRResult(pdf_path=image_path, total_pages=1)

        if cancel_event and cancel_event.is_set():
            return result

        image_bytes = image_path.read_bytes()
        page_result = self._process_single_page(0, image_bytes, mime_type=mime_type)
        result.page_results.append(page_result)

        if page_result.success:
            result.successful_pages = 1
            result.combined_text = page_result.text
            logger.info(
                "Immagine OCR completata: %d caratteri, %d+%d token",
                len(page_result.text),
                page_result.input_tokens, page_result.output_tokens,
            )
        else:
            logger.error("OCR immagine fallito: %s", page_result.error)
            result.combined_text = f"[OCR non riuscito: {page_result.error}]"

        if on_page_complete:
            on_page_complete(0, 1, page_result.success)

        return result

    def _process_single_page(
        self, page_num: int, image_bytes: bytes,
        mime_type: str = "image/jpeg",
    ) -> OCRPageResult:
        """Process a single page with retry logic."""

        def do_ocr():
            return self.ocr.ocr_page(image_bytes, page_num, mime_type=mime_type)

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
