import email
import email.policy
import tempfile
import unittest
from email.message import EmailMessage
from pathlib import Path

from pipeline.email_sources import _find_pec_inner, extract_eml_parts


def _build_pec() -> bytes:
    """Costruisce una PEC: busta di trasporto che avvolge il messaggio VERO in
    `postacert.eml`, accanto a `daticert.xml` e `smime.p7s`."""
    inner = EmailMessage()
    inner["From"] = "avvocato-vero@pec.it"
    inner["To"] = "cliente@pec.it"
    inner["Subject"] = "ATTO DI CITAZIONE"
    inner["Date"] = "Mon, 1 Jan 2024 10:00:00 +0100"
    inner.set_content("Testo dell'atto vero.")
    inner.add_attachment(b"%PDF-1.4 finto", maintype="application",
                         subtype="pdf", filename="citazione.pdf")

    outer = EmailMessage()
    outer["From"] = "posta-certificata@pec.it"
    outer["Subject"] = "POSTA CERTIFICATA: Vero Oggetto"
    outer.set_content("Messaggio di posta certificata (solo busta di trasporto).")
    outer.add_attachment(inner, filename="postacert.eml")
    outer.add_attachment(b"<?xml version='1.0'?><postacert/>", maintype="application",
                         subtype="xml", filename="daticert.xml")
    outer.add_attachment(b"firma", maintype="application",
                         subtype="pkcs7-signature", filename="smime.p7s")
    return outer.as_bytes()


class PecUnwrapTests(unittest.TestCase):
    def test_pec_estrae_il_messaggio_originale(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pec = Path(tmpdir) / "pec.eml"
            pec.write_bytes(_build_pec())

            processed: list[str] = []

            def _process(path: Path) -> str:
                processed.append(path.name)
                return f"OCR di {path.name}"

            body, attachments = extract_eml_parts(
                pec, _process, lambda *a, **k: None)

            # header e corpo VERI (dal postacert.eml), non quelli della busta
            self.assertIn("avvocato-vero@pec.it", body)
            self.assertIn("ATTO DI CITAZIONE", body)
            self.assertIn("Testo dell'atto vero.", body)
            self.assertIn("busta di trasporto", body)  # nota PEC
            self.assertNotIn("solo busta di trasporto", body)  # corpo della busta scartato
            # allegato VERO estratto; metadati/firma della busta esclusi
            self.assertEqual(["citazione.pdf"], processed)
            self.assertEqual(["citazione.pdf"], [a.filename for a in attachments])

    def test_email_normale_non_e_pec(self):
        """Un'email che inoltra un altro messaggio (message/rfc822 NON chiamato
        postacert.eml) non deve essere trattata come PEC."""
        fwd_inner = EmailMessage()
        fwd_inner["Subject"] = "Inoltrato"
        fwd_inner.set_content("ciao")
        fwd = EmailMessage()
        fwd["Subject"] = "Fwd"
        fwd.set_content("Ti inoltro.")
        fwd.add_attachment(fwd_inner, filename="messaggio.eml")
        msg = email.message_from_bytes(fwd.as_bytes(), policy=email.policy.default)
        self.assertIsNone(_find_pec_inner(msg))


if __name__ == "__main__":
    unittest.main()
