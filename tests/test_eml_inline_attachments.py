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


if __name__ == "__main__":
    unittest.main()
