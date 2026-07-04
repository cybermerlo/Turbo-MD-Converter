import email
import email.policy
import tempfile
import unittest
from email.message import EmailMessage
from pathlib import Path

from pipeline.email_sources import _is_pec_envelope, extract_eml_parts


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

    def test_pec_inoltrata_non_viene_sbustata(self):
        """Un avvocato che INOLTRA una PEC (nota propria + postacert.eml allegato) non
        deve perdere la nota: senza i marcatori della busta di trasporto (mittente
        posta-certificata@, oggetto 'POSTA CERTIFICATA:', header X-Ricevuta) NON si
        sbusta -> il messaggio viene processato normalmente."""
        inner = EmailMessage()
        inner["From"] = "avvocato@pec.it"
        inner["Subject"] = "ATTO"
        inner.set_content("atto vero")
        fwd = EmailMessage()
        fwd["From"] = "collega@studio.it"        # NON posta-certificata@
        fwd["Subject"] = "Ti giro questa PEC"    # NON 'POSTA CERTIFICATA:'
        fwd.set_content("Guarda il punto 3, urgente. -- Mario")
        fwd.add_attachment(inner, filename="postacert.eml")

        self.assertFalse(_is_pec_envelope(
            email.message_from_bytes(fwd.as_bytes(), policy=email.policy.default)))
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "fwd.eml"
            f.write_bytes(fwd.as_bytes())
            body, _atts = extract_eml_parts(f, lambda p: "", lambda *a, **k: None)
        self.assertIn("Guarda il punto 3", body)        # nota dell'inoltro conservata
        self.assertNotIn("busta di trasporto", body)    # NON sbustata


if __name__ == "__main__":
    unittest.main()
