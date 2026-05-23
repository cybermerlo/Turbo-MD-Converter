"""Format router: convert a file path to plain text (OCR or direct read)."""

import tempfile
import threading
from collections.abc import Callable
from pathlib import Path

from config.settings import AppConfig
from ocr.ocr_pipeline import OCRPipeline, OCRResult
from pipeline.archive_sources import extract_archive_text, is_archive_path
from pipeline.constants import ARCHIVE_EXTENSIONS, IMAGE_EXTENSIONS
from pipeline.email_sources import (
    extract_eml_parts,
    extract_msg_parts,
    join_email_and_attachments,
)
from pipeline.models import EmailAttachmentDocument
from pipeline.text_extractors import (
    extract_docx_text,
    extract_html_text,
    extract_rtf_text,
)


class AttachmentProcessor:
    """Routes a file to the correct text-extraction handler."""

    def __init__(
        self,
        config: AppConfig,
        ocr_pipeline: OCRPipeline,
        emit_log: Callable[[str, str], None],
        on_page_complete: Callable,
        on_page_skipped: Callable,
        on_page_native_text: Callable,
    ):
        self.config = config
        self.ocr_pipeline = ocr_pipeline
        self.emit_log = emit_log
        self._on_page_complete = on_page_complete
        self._on_page_skipped = on_page_skipped
        self._on_page_native_text = on_page_native_text

    def to_text(
        self,
        att_path: Path,
        cancel_event: threading.Event | None = None,
    ) -> str:
        _cancel = cancel_event or threading.Event()
        suffix = att_path.suffix.lower()
        try:
            if suffix == ".pdf":
                result = self.ocr_pipeline.process_pdf(
                    pdf_path=att_path,
                    on_page_complete=self._on_page_complete,
                    on_page_skipped=self._on_page_skipped,
                    on_page_native_text=self._on_page_native_text,
                    cancel_event=_cancel,
                )
                return result.combined_text
            if suffix in IMAGE_EXTENSIONS:
                result = self.ocr_pipeline.ocr_single_image(
                    image_path=att_path,
                    on_page_complete=self._on_page_complete,
                    cancel_event=_cancel,
                )
                return result.combined_text
            if suffix == ".docx":
                return extract_docx_text(att_path)
            if suffix in (".html", ".htm"):
                return extract_html_text(att_path)
            if suffix == ".rtf":
                return extract_rtf_text(att_path)
            if suffix in (".txt", ".md"):
                return att_path.read_text(encoding="utf-8", errors="replace")
            if suffix == ".p7m":
                return self._extract_p7m_text(att_path, cancel_event)
            if is_archive_path(att_path):
                return extract_archive_text(
                    att_path,
                    process_member=lambda path: self.to_text(path, cancel_event),
                    emit_log=self.emit_log,
                    cancel_event=cancel_event,
                )
            self.emit_log(
                f"Allegato '{att_path.name}' ({suffix}) non supportato - saltato",
                "WARNING",
            )
            return ""
        except Exception as e:
            self.emit_log(
                f"Errore elaborazione allegato '{att_path.name}': {e}",
                "ERROR",
            )
            return ""

    def read_text_file(
        self,
        file_path: Path,
        cancel_event: threading.Event | None = None,
    ) -> tuple[OCRResult, list[EmailAttachmentDocument]]:
        """Read/unpack content from text, container and archive files (no OCR)."""
        suffix = file_path.suffix.lower()
        name_lower = file_path.name.lower()
        pending_attachments: list[EmailAttachmentDocument] = []
        process = lambda path: self.to_text(path, cancel_event)

        if suffix == ".eml":
            if self.config.email_attachments_separate:
                text, pending_attachments = extract_eml_parts(
                    file_path, process, self.emit_log, cancel_event,
                )
            else:
                body, attachments = extract_eml_parts(
                    file_path, process, self.emit_log, cancel_event,
                )
                text = join_email_and_attachments(body, attachments)
            self.emit_log("File EML letto direttamente", "INFO")
        elif suffix == ".msg":
            if self.config.email_attachments_separate:
                text, pending_attachments = extract_msg_parts(
                    file_path, process, self.emit_log, cancel_event,
                )
            else:
                body, attachments = extract_msg_parts(
                    file_path, process, self.emit_log, cancel_event,
                )
                text = join_email_and_attachments(body, attachments)
            self.emit_log("File MSG letto direttamente", "INFO")
        elif suffix == ".docx":
            text = extract_docx_text(file_path)
            self.emit_log("File DOCX letto direttamente", "INFO")
        elif suffix in (".html", ".htm"):
            text = extract_html_text(file_path)
            self.emit_log("File HTML letto direttamente", "INFO")
        elif suffix == ".rtf":
            text = extract_rtf_text(file_path)
            self.emit_log("File RTF letto direttamente", "INFO")
        elif suffix == ".md":
            text = file_path.read_text(encoding="utf-8", errors="replace")
            self.emit_log("File MD letto direttamente", "INFO")
        elif suffix == ".p7m":
            self.emit_log(f"Estrazione firma P7M: {file_path.name}", "INFO")
            text = self._extract_p7m_text(file_path, cancel_event)
        elif suffix in ARCHIVE_EXTENSIONS or name_lower.endswith(
            (".tar.gz", ".tar.bz2", ".tar.xz")
        ):
            fmt = suffix.lstrip(".").upper() if suffix in ARCHIVE_EXTENSIONS else "TAR"
            self.emit_log(f"Apertura archivio {fmt}: {file_path.name}", "INFO")
            text = extract_archive_text(
                file_path, process, self.emit_log, cancel_event,
            )
        else:
            text = file_path.read_text(encoding="utf-8", errors="replace")
            self.emit_log("File TXT letto direttamente", "INFO")

        return OCRResult(
            pdf_path=file_path,
            combined_text=text,
            total_pages=1,
            successful_pages=1,
        ), pending_attachments

    def _extract_p7m_text(
        self,
        file_path: Path,
        cancel_event: threading.Event | None = None,
    ) -> str:
        try:
            from asn1crypto import cms as asn1_cms
        except ImportError:
            raise RuntimeError(
                "Libreria asn1crypto non trovata. Eseguire: pip install asn1crypto"
            ) from None

        data = file_path.read_bytes()
        try:
            content_info = asn1_cms.ContentInfo.load(data)
            if content_info["content_type"].native != "signed_data":
                raise ValueError(
                    f"Tipo P7M non riconosciuto: {content_info['content_type'].native}"
                )
            encap = content_info["content"]["encap_content_info"]
            inner_bytes = encap["content"].native
            if not inner_bytes:
                raise ValueError("P7M senza contenuto (eContent vuoto)")
        except Exception as e:
            raise RuntimeError(
                f"Parsing P7M '{file_path.name}' fallito: {e}"
            ) from e

        inner_name = file_path.stem
        inner_suffix = Path(inner_name).suffix.lower()

        if not inner_suffix or inner_suffix == file_path.suffix.lower():
            if inner_bytes[:4] == b"%PDF":
                inner_suffix = ".pdf"
            elif inner_bytes[:2] == b"PK":
                inner_suffix = ".zip"
            elif inner_bytes[:5] == b"<?xml":
                inner_suffix = ".xml"
            else:
                inner_suffix = ".bin"
            inner_name = file_path.stem + inner_suffix

        self.emit_log(
            f"P7M estratto: {inner_name}  ({len(inner_bytes):,} byte)",
            "INFO",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            inner_path = Path(tmpdir) / inner_name
            inner_path.write_bytes(inner_bytes)
            return self.to_text(inner_path, cancel_event)
