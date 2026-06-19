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

    def iter_pages_raw(self, pdf_path: Path) -> Iterator[tuple[int, "fitz.Page"]]:
        """Yields (page_number, fitz.Page) for every page without rendering.

        The document is opened once and closed when the iterator is exhausted.
        Use render_page() on each page to get JPEG bytes on demand.
        """
        doc = fitz.open(str(pdf_path))
        try:
            total = doc.page_count
            logger.info("PDF '%s': %d pagine da analizzare", pdf_path.name, total)
            for i in range(total):
                yield (i, doc.load_page(i))
        finally:
            doc.close()

    def render_page(self, page: "fitz.Page") -> bytes:
        """Render an already-loaded fitz.Page to JPEG bytes."""
        pixmap = page.get_pixmap(dpi=self.dpi, alpha=False)
        return pixmap.tobytes(output="jpeg", jpg_quality=self.jpeg_quality)
