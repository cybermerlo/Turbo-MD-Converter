"""Fallback a strisce quando l'OCR di una pagina viene troncato (RECITATION & c.).

L'OCR reale e' sostituito da uno stub: la pagina INTERA (immagine alta) torna
troncata (finish_reason=RECITATION), le STRISCE piu' basse tornano complete (STOP).
Verifica che il pipeline recuperi il testo dividendo la pagina.
"""

import io
import unittest

from PIL import Image

from ocr.ocr_pipeline import OCRPipeline, _join_bands


def _jpeg(height: int, width: int = 600) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buf, format="JPEG")
    return buf.getvalue()


def _pipe(fake_ocr) -> OCRPipeline:
    # Bypassa __init__ (evita di costruire un client Gemini reale): servono solo
    # questi tre attributi a _process_single_page / _ocr_banded.
    p = OCRPipeline.__new__(OCRPipeline)
    p.ocr = fake_ocr
    p.cost_tracker = None
    p.model_id = "test"
    return p


class _TruncatingOCR:
    """Pagina intera (alta) -> RECITATION; strisce (basse) -> testo completo."""
    def __init__(self, tall_threshold: int = 1500):
        self.calls = 0
        self.tall = tall_threshold

    def ocr_page(self, image_bytes, page_num=0, mime_type="image/jpeg"):
        self.calls += 1
        h = Image.open(io.BytesIO(image_bytes)).height
        if h > self.tall:
            return {"text": "INIZIO (poi troncato)", "input_tokens": 10,
                    "output_tokens": 5, "finish_reason": "RECITATION"}
        return {"text": f"contenuto completo della banda #{self.calls} (h={h})",
                "input_tokens": 8, "output_tokens": 12, "finish_reason": "STOP"}


class RecitationFallbackTests(unittest.TestCase):
    def test_pagina_troncata_recuperata_a_strisce(self):
        fake = _TruncatingOCR()
        res = _pipe(fake)._process_single_page(0, _jpeg(2000))
        self.assertTrue(res.success)
        # il testo troncato e' stato sostituito dal recupero a strisce, piu' lungo
        self.assertIn("banda", res.text)
        self.assertGreater(len(res.text), len("INIZIO (poi troncato)"))
        # ha richiesto piu' di una chiamata (intera + strisce)
        self.assertGreater(fake.calls, 1)
        # i token delle strisce sono sommati
        self.assertGreater(res.output_tokens, 5)

    def test_pagina_completa_non_attiva_il_fallback(self):
        class _OkOCR:
            def __init__(self):
                self.calls = 0

            def ocr_page(self, image_bytes, page_num=0, mime_type="image/jpeg"):
                self.calls += 1
                return {"text": "pagina intera ok", "input_tokens": 1,
                        "output_tokens": 1, "finish_reason": "STOP"}

        ok = _OkOCR()
        res = _pipe(ok)._process_single_page(0, _jpeg(2000))
        self.assertEqual(res.text, "pagina intera ok")
        self.assertEqual(ok.calls, 1)  # nessuna suddivisione se non e' troncata


class JoinBandsTests(unittest.TestCase):
    def test_scarta_frammenti_e_duplicati_ma_tiene_il_contenuto(self):
        bands = [
            "Testo introduttivo abbastanza lungo.\nArt. 1 Ogg",  # "Art. 1 Ogg" = taglio a meta'
            "Art. 1 Oggetto dell'assicurazione completo.\nClausola comune ripetuta qui.",
            "Clausola comune ripetuta qui.\nConclusione del documento.",  # duplicato esatto
        ]
        out = _join_bands(bands)
        # il frammento (contenuto nella riga piu' completa vicina) sparisce
        self.assertIn("Art. 1 Oggetto dell'assicurazione completo.", out)
        self.assertNotIn("Art. 1 Ogg\n", out + "\n")
        # il duplicato esatto compare una sola volta
        self.assertEqual(out.count("Clausola comune ripetuta qui."), 1)
        # il contenuto vero (inizio e fine) e' preservato
        self.assertIn("Testo introduttivo abbastanza lungo.", out)
        self.assertIn("Conclusione del documento.", out)

    def test_non_scarta_righe_corte(self):
        # righe corte (< soglia) non vanno mai perse anche se contenute altrove
        out = _join_bands(["Art. 4\nEffetto e durata dell'assicurazione: Art. 4 e seguenti."])
        self.assertIn("Art. 4", out)


if __name__ == "__main__":
    unittest.main()
