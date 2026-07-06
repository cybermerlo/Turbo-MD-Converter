"""OCR pipeline orchestrator: PDF -> page-by-page OCR -> combined text."""

import contextlib
import logging
import threading
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Callable

from PIL import Image

from config.defaults import PAGE_SEPARATOR
from config.settings import AppConfig
from ocr.gemini_ocr import GeminiOCR, GeminiOCRError, GeminiOCRRetryableError
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

# Finish reason che indicano una trascrizione TRONCATA (non un normale STOP). Il caso
# tipico su documenti legali e' RECITATION: Gemini interrompe l'output quando riconosce
# testo "recitato" (leggi, decreti, polizze standard pubblicate in G.U.), tagliando la
# pagina a meta'. Su questi casi facciamo il fallback a strisce.
_TRUNCATED_REASONS = frozenset({
    "RECITATION", "MAX_TOKENS", "SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "OTHER",
})
_BAND_MAX_DEPTH = 3       # profondita' max della suddivisione (fino a ~8 strisce dove serve)
_BAND_OVERLAP = 0.06      # sovrapposizione tra strisce (frazione dell'altezza) per non tagliare righe


def _is_truncated(finish_reason) -> bool:
    return bool(finish_reason) and str(finish_reason).upper() in _TRUNCATED_REASONS


def _to_jpeg(img, quality: int = 85) -> bytes:
    from io import BytesIO
    buf = BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def _norm_line(s: str) -> str:
    return " ".join(s.split()).lower()


_JOIN_WINDOW = 12   # righe entro cui cercare i duplicati/frammenti alla giuntura
_JOIN_MINLEN = 6    # righe piu' corte di cosi' non vengono mai scartate (troppo rischioso)


def _join_bands(parts: list[str]) -> str:
    """Concatena il testo delle strisce eliminando i frammenti alle giunture. Le
    strisce si sovrappongono (per non tagliare le righe) e una striscia bloccata da
    RECITATION finisce a meta' riga: si producono cosi' righe DUPLICATE (dalla
    sovrapposizione ri-letta) e MOZZICONI (dai tagli a meta'). Regola conservativa:
    si scarta una riga solo se e' un DUPLICATO esatto di una vicina gia' tenuta, o se
    e' CONTENUTA in una riga piu' completa lì vicino (quindi e' un frammento di quella).
    Le righe corte non si toccano, per non perdere mai contenuto vero."""
    lines: list[str] = []
    for part in parts:
        lines.extend(part.split("\n"))
    norm = [_norm_line(x) for x in lines]
    n = len(lines)
    keep = [True] * n
    for i in range(n):
        ni = norm[i]
        if not ni or len(ni) < _JOIN_MINLEN:
            continue
        lo, hi = max(0, i - _JOIN_WINDOW), min(n, i + _JOIN_WINDOW + 1)
        for j in range(lo, hi):
            if j == i or not keep[j]:
                continue
            nj = norm[j]
            if nj == ni:
                if j < i:            # duplicato esatto: tieni la prima occorrenza
                    keep[i] = False
                    break
            elif len(nj) > len(ni) and ni in nj:  # frammento di una riga piu' completa vicina
                keep[i] = False
                break
    out = [lines[i] for i in range(n) if keep[i]]
    # collassa le righe vuote consecutive rimaste dopo lo scarto
    res: list[str] = []
    for line in out:
        if not line.strip() and res and not res[-1].strip():
            continue
        res.append(line)
    return "\n".join(res).strip()


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
    # True quando combined_text contiene già un corpo Markdown pronto (con le proprie
    # intestazioni di sezione, es. video: "## Trascrizione audio" + "## Descrizione
    # visiva"): il formatter lo emette così com'è, senza il wrapper generico.
    prerendered_body: bool = False


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

        # ``closing`` garantisce che il documento PyMuPDF venga chiuso anche se
        # il loop esce in anticipo (cancellazione/eccezione): senza questo, alla
        # ``break`` il ``finally`` del generatore scatterebbe solo alla GC,
        # lasciando il file PDF bloccato su Windows.
        with contextlib.closing(self.converter.iter_pages_raw(pdf_path)) as pages:
            for page_num, page in pages:
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

    def _ocr_call(self, image_bytes: bytes, page_num: int,
                  mime_type: str = "image/jpeg") -> dict:
        """Una chiamata OCR con retry sui SOLI errori transitori (i 4xx permanenti
        falliscono subito). Ritorna il dict di `GeminiOCR.ocr_page`
        (text, input_tokens, output_tokens, finish_reason)."""
        max_retries = 3

        def on_retry(attempt: int, exc: Exception):
            logger.warning("Retry %d/%d per pagina %d: %s",
                           attempt, max_retries, page_num + 1, exc)

        return retry_with_backoff(
            func=lambda: self.ocr.ocr_page(image_bytes, page_num, mime_type=mime_type),
            max_retries=max_retries,
            base_delay=2.0,
            retryable_exceptions=(GeminiOCRRetryableError,),
            on_retry=on_retry,
        )

    def _process_single_page(
        self, page_num: int, image_bytes: bytes,
        mime_type: str = "image/jpeg",
    ) -> OCRPageResult:
        """OCR di una pagina. Se la trascrizione della pagina INTERA viene troncata
        (tipicamente RECITATION su testi standard/pubblicati), ritenta a strisce
        orizzontali per recuperare il testo tagliato."""
        try:
            res = self._ocr_call(image_bytes, page_num, mime_type)
            text = res["text"]
            in_tok = res["input_tokens"]
            out_tok = res["output_tokens"]

            if _is_truncated(res.get("finish_reason")):
                logger.warning(
                    "Pagina %d troncata dall'OCR (%s): ri-provo a strisce per "
                    "recuperare il testo mancante.", page_num + 1, res.get("finish_reason"),
                )
                banded = self._ocr_banded(image_bytes, page_num, mime_type)
                in_tok += banded["input_tokens"]
                out_tok += banded["output_tokens"]
                if len(banded["text"]) > len(text):
                    logger.info("Pagina %d: recupero a strisce %d -> %d caratteri.",
                                page_num + 1, len(text), len(banded["text"]))
                    text = banded["text"]

            if self.cost_tracker:
                self.cost_tracker.add_call(
                    model_id=self.model_id, input_tokens=in_tok,
                    output_tokens=out_tok, phase="ocr",
                )
            return OCRPageResult(
                page_num=page_num, text=text, success=True,
                input_tokens=in_tok, output_tokens=out_tok,
            )

        except GeminiOCRError as e:
            return OCRPageResult(page_num=page_num, text="", success=False, error=str(e))

    def _ocr_banded(self, image_bytes: bytes, page_num: int,
                    mime_type: str = "image/jpeg") -> dict:
        """Ri-OCR di una pagina troncata dividendola in strisce orizzontali sovrapposte
        (ricorsivo: una striscia ancora troncata viene divisa di nuovo, fino a
        `_BAND_MAX_DEPTH`). Le trascrizioni piu' corte aggirano il blocco RECITATION.
        Ritorna {text, input_tokens, output_tokens}; text vuoto se non si puo' dividere."""
        try:
            base = Image.open(BytesIO(image_bytes))
            base.load()
        except Exception as e:  # noqa: BLE001 — immagine illeggibile: niente fallback
            logger.warning("Fallback a strisce non possibile (pagina %d): %s",
                           page_num + 1, e)
            return {"text": "", "input_tokens": 0, "output_tokens": 0}

        texts: list[str] = []
        tok = {"in": 0, "out": 0}

        def ocr_region(img: "Image.Image", depth: int) -> None:
            try:
                r = self._ocr_call(_to_jpeg(img), page_num, "image/jpeg")
            except GeminiOCRError:
                return
            tok["in"] += r["input_tokens"]
            tok["out"] += r["output_tokens"]
            if not _is_truncated(r.get("finish_reason")) or depth >= _BAND_MAX_DEPTH:
                if r["text"].strip():
                    texts.append(r["text"].strip())
                return
            # striscia ancora troncata: dividila in due (con sovrapposizione)
            h, w = img.height, img.width
            ov = int(h * _BAND_OVERLAP)
            mid = h // 2
            ocr_region(img.crop((0, 0, w, min(h, mid + ov))), depth + 1)
            ocr_region(img.crop((0, max(0, mid - ov), w, h)), depth + 1)

        # la pagina intera e' gia' nota come troncata: parti subito dividendo in due
        h, w = base.height, base.width
        ov = int(h * _BAND_OVERLAP)
        mid = h // 2
        ocr_region(base.crop((0, 0, w, min(h, mid + ov))), 1)
        ocr_region(base.crop((0, max(0, mid - ov), w, h)), 1)
        return {"text": _join_bands(texts), "input_tokens": tok["in"], "output_tokens": tok["out"]}
