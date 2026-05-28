import tempfile
import unittest
from email.message import EmailMessage
from pathlib import Path

from pipeline.email_sources import extract_eml_parts


class EmlBodyHtmlFallbackTests(unittest.TestCase):
    def test_extracts_body_from_html_when_plain_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            eml_path = Path(tmpdir) / "mail.eml"
            msg = EmailMessage()
            msg["From"] = "sender@example.com"
            msg["To"] = "receiver@example.com"
            msg["Subject"] = "Solo HTML"
            msg.set_content(
                "<html><body><p>Corpo inoltrato completo.</p></body></html>",
                subtype="html",
            )
            eml_path.write_bytes(msg.as_bytes())

            body_text, attachments = extract_eml_parts(
                eml_path,
                lambda _path: "",
                lambda *_args, **_kwargs: None,
            )

            self.assertIn("Corpo inoltrato completo.", body_text)
            self.assertEqual([], attachments)


if __name__ == "__main__":
    unittest.main()
