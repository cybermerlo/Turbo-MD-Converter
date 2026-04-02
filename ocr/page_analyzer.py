"""PDF page analysis: detects whether a page has native text or is scanned."""

import logging
from dataclasses import dataclass
from enum import Enum

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

# Minimum characters to consider a page as having meaningful native text
_MIN_TEXT_CHARS = 50

# An image covering more than this fraction of the page area is "full-page" (scanned)
_FULL_PAGE_IMAGE_THRESHOLD = 0.80

# An image covering more than this fraction is "significant" (content image)
_SIGNIFICANT_IMAGE_THRESHOLD = 0.04


class PageType(Enum):
    TEXT_NATIVE = "text_native"   # Selectable text, no significant images -> skip OCR
    SCANNED = "scanned"           # Image-only page -> needs OCR
    MIXED = "mixed"               # Text + significant images -> needs OCR for images


@dataclass
class PageAnalysisResult:
    """Result of analysing a single PDF page."""
    page_type: PageType
    text_char_count: int
    image_count: int
    significant_image_count: int
    reason: str  # Human-readable explanation for logs


class PageAnalyzer:
    """Analyses fitz.Page objects to determine if OCR is needed."""

    def analyze_page(self, page: fitz.Page) -> PageAnalysisResult:
        """Classify a page as TEXT_NATIVE, SCANNED, or MIXED.

        Args:
            page: An open fitz.Page object.

        Returns:
            PageAnalysisResult with classification and diagnostic info.
        """
        text = page.get_text("text")
        char_count = len(text.replace(" ", "").replace("\n", "").replace("\t", ""))

        image_list = page.get_images(full=True)
        image_count = len(image_list)

        page_area = page.rect.width * page.rect.height
        significant_count = 0
        has_full_page_image = False

        for img_info in image_list:
            xref = img_info[0]
            try:
                rects = page.get_image_rects(xref)
            except Exception:
                continue
            for rect in rects:
                if rect.is_empty:
                    continue
                img_area = rect.width * rect.height
                if page_area > 0:
                    ratio = img_area / page_area
                    if ratio >= _FULL_PAGE_IMAGE_THRESHOLD:
                        has_full_page_image = True
                    elif ratio >= _SIGNIFICANT_IMAGE_THRESHOLD:
                        significant_count += 1

        # Classification logic
        has_text = char_count >= _MIN_TEXT_CHARS

        if not has_text and (has_full_page_image or image_count > 0):
            return PageAnalysisResult(
                page_type=PageType.SCANNED,
                text_char_count=char_count,
                image_count=image_count,
                significant_image_count=significant_count,
                reason=(
                    f"scansionata: {char_count} car., "
                    f"{image_count} immagini (pagina intera: {'si' if has_full_page_image else 'no'})"
                ),
            )

        if not has_text:
            # No text and no images (blank or unusual page) — treat as scanned to be safe
            return PageAnalysisResult(
                page_type=PageType.SCANNED,
                text_char_count=char_count,
                image_count=image_count,
                significant_image_count=significant_count,
                reason=f"pagina vuota o non riconosciuta: {char_count} car., {image_count} immagini",
            )

        if has_text and significant_count == 0 and not has_full_page_image:
            return PageAnalysisResult(
                page_type=PageType.TEXT_NATIVE,
                text_char_count=char_count,
                image_count=image_count,
                significant_image_count=significant_count,
                reason=f"testo nativo: {char_count} car., nessuna immagine significativa",
            )

        # has_text + significant images or full-page image alongside text
        return PageAnalysisResult(
            page_type=PageType.MIXED,
            text_char_count=char_count,
            image_count=image_count,
            significant_image_count=significant_count,
            reason=(
                f"misto: {char_count} car. + {significant_count} immagini significative"
                + (" + immagine pagina intera" if has_full_page_image else "")
            ),
        )

    def extract_text(self, page: fitz.Page) -> str:
        """Extract plain text from a native-text page.

        Args:
            page: An open fitz.Page object.

        Returns:
            Plain text string.
        """
        return page.get_text("text")
