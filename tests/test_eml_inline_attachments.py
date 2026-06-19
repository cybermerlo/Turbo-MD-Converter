import tempfile
import unittest
from email.message import EmailMessage
from pathlib import Path

from pipeline.email_sources import extract_eml_parts


class EmlInlineAttachmentTests(unittest.TestCase):
    def test_extracts_inline_pdf_attachment_with_filename(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            eml_path = Path(tmpdir) / "mail.eml"

            msg = EmailMessage()
            msg["From"] = "sender@example.com"
            msg["To"] = "receiver@example.com"
            msg["Subject"] = "PDF inline"
            msg.set_content("Corpo della mail.")
            msg.add_attachment(
                b"%PDF-1.4\n%fake\n",
                maintype="application",
                subtype="pdf",
                filename="preventivo.pdf",
                disposition="inline",
            )
            eml_path.write_bytes(msg.as_bytes())

            processed_names: list[str] = []

            def _process_attachment(path: Path) -> str:
                processed_names.append(path.name)
                return f"OCR di {path.name}"

            body_text, attachments = extract_eml_parts(
                eml_path,
                _process_attachment,
                lambda *_args, **_kwargs: None,
            )

            self.assertIn("Corpo della mail.", body_text)
            self.assertEqual(["preventivo.pdf"], processed_names)
            self.assertEqual(1, len(attachments))
            self.assertEqual("preventivo.pdf", attachments[0].filename)
            self.assertIn("OCR di preventivo.pdf", attachments[0].text)

    def test_same_named_attachments_do_not_overwrite(self):
        """Due allegati con lo stesso filename devono essere processati
        entrambi senza sovrascriversi nella tempdir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            eml_path = Path(tmpdir) / "mail.eml"

            msg = EmailMessage()
            msg["Subject"] = "Due immagini omonime"
            msg.set_content("Corpo.")
            msg.add_attachment(
                b"\x89PNG\r\n\x1a\n-primo",
                maintype="image",
                subtype="png",
                filename="image001.png",
                disposition="inline",
            )
            msg.add_attachment(
                b"\x89PNG\r\n\x1a\n-secondo",
                maintype="image",
                subtype="png",
                filename="image001.png",
                disposition="inline",
            )
            eml_path.write_bytes(msg.as_bytes())

            seen_bytes: list[bytes] = []

            def _process_attachment(path: Path) -> str:
                data = path.read_bytes()
                seen_bytes.append(data)
                return f"OCR {len(data)}b"

            _body, attachments = extract_eml_parts(
                eml_path,
                _process_attachment,
                lambda *_args, **_kwargs: None,
            )

            # Entrambi gli allegati processati con i loro contenuti distinti.
            self.assertEqual(2, len(attachments))
            self.assertIn(b"\x89PNG\r\n\x1a\n-primo", seen_bytes)
            self.assertIn(b"\x89PNG\r\n\x1a\n-secondo", seen_bytes)


if __name__ == "__main__":
    unittest.main()
