"""PDF to page image conversion using PyMuPDF."""

import logging
from pathlib import Path
from typing import Iterator

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)


class PDFConverter:
    """Converts PDF pages to JPEG byte arrays."""

    def __init__(self, dpi: int = 200, jpeg_quality: int = 85):
        self.dpi = dpi
        self.jpeg_quality = jpeg_quality

    def get_page_count(self, pdf_path: Path) -> int:
        """Returns total page count without loading all pages."""
        doc = fitz.open(str(pdf_path))
        count = doc.page_count
        doc.close()
        return count

    def convert_page(self, pdf_path: Path, page_num: int) -> bytes:
        """Converts a single page to JPEG bytes.

        Args:
            pdf_path: Path to the PDF file.
            page_num: Zero-based page index.

        Returns:
            JPEG image bytes.
        """
        doc = fitz.open(str(pdf_path))
        try:
            page = doc.load_page(page_num)
            pixmap = page.get_pixmap(dpi=self.dpi)
            img_bytes = pixmap.tobytes(output="jpeg", jpg_quality=self.jpeg_quality)
            return img_bytes
        finally:
            doc.close()

    def iter_pages(self, pdf_path: Path) -> Iterator[tuple[int, bytes]]:
        """Yields (page_number, jpeg_bytes) for every page.

        Opens the document once and iterates through all pages
        for efficiency.
        """
        doc = fitz.open(str(pdf_path))
        try:
            total = doc.page_count
            logger.info("PDF '%s': %d pagine da convertire", pdf_path.name, total)
            for i in range(total):
                page = doc.load_page(i)
                pixmap = page.get_pixmap(dpi=self.dpi)
                img_bytes = pixmap.tobytes(output="jpeg", jpg_quality=self.jpeg_quality)
                logger.debug("Pagina %d/%d convertita (%d bytes)", i + 1, total, len(img_bytes))
                yield (i, img_bytes)
        finally:
            doc.close()
