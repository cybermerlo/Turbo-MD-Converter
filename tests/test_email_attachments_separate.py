import tempfile
import threading
import unittest
from email.message import EmailMessage
from pathlib import Path

from config.settings import AppConfig
from pipeline.processor import DocumentProcessor


class EmailAttachmentsSeparateTests(unittest.TestCase):
    def _write_sample_eml(self, root: Path) -> Path:
        eml_path = root / "messaggio.eml"
        msg = EmailMessage()
        msg["From"] = "sender@example.com"
        msg["To"] = "receiver@example.com"
        msg["Subject"] = "Test allegato"
        msg.set_content("Corpo della mail.")
        msg.add_attachment(
            "Contenuto dell'allegato.",
            subtype="plain",
            filename="documento.txt",
        )
        eml_path.write_bytes(msg.as_bytes())
        return eml_path

    def test_eml_writes_mail_and_attachment_markdown_separately(self):
        events = []
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            eml_path = self._write_sample_eml(root)

            config = AppConfig(
                gemini_api_key="test-key",
                run_extraction=False,
                email_attachments_separate=True,
            )
            processor = DocumentProcessor(config, events.append)

            success, _cost_info = processor.process_single(
                eml_path,
                threading.Event(),
            )

            self.assertTrue(success)
            main_md = root / "messaggio.md"
            attachment_md = root / "messaggio - Allegato 1 - documento.md"
            self.assertTrue(main_md.exists())
            self.assertTrue(attachment_md.exists())

            main_text = main_md.read_text(encoding="utf-8")
            attachment_text = attachment_md.read_text(encoding="utf-8")
            self.assertIn("Corpo della mail.", main_text)
            self.assertNotIn("Contenuto dell'allegato.", main_text)
            self.assertIn("Contenuto dell'allegato.", attachment_text)

    def test_eml_keeps_attachments_in_single_markdown_by_default(self):
        events = []
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            eml_path = self._write_sample_eml(root)

            config = AppConfig(
                gemini_api_key="test-key",
                run_extraction=False,
            )
            processor = DocumentProcessor(config, events.append)

            success, _cost_info = processor.process_single(
                eml_path,
                threading.Event(),
            )

            self.assertTrue(success)
            markdown_files = sorted(root.glob("*.md"))
            self.assertEqual([root / "messaggio.md"], markdown_files)
            main_text = markdown_files[0].read_text(encoding="utf-8")
            self.assertIn("Corpo della mail.", main_text)
            self.assertIn("Contenuto dell'allegato.", main_text)


if __name__ == "__main__":
    unittest.main()
