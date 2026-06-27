"""Test del router file→testo (pipeline/attachment_processor.py)."""

import tempfile
import unittest
from pathlib import Path

from config.settings import AppConfig
from ocr.audio_transcriber import AudioNotDecodableError
from pipeline.attachment_processor import AttachmentProcessor


def _make_processor(logs, transcriber=None):
    return AttachmentProcessor(
        config=AppConfig(),
        ocr_pipeline=None,
        emit_log=lambda msg, level="INFO": logs.append((msg, level)),
        on_page_complete=None,
        on_page_skipped=None,
        on_page_native_text=None,
        audio_transcriber=transcriber,
    )


class UndecodableMediaDowngradeTests(unittest.TestCase):
    def test_attachment_processor_downgrades_to_warning(self):
        """Il media non decodificabile produce WARNING (non ERROR) e testo vuoto."""

        class StubTranscriber:
            model_id = "scribe_v2"

            def transcribe(self, _path):
                raise AudioNotDecodableError("Nessuna traccia audio decodificabile")

        logs: list[tuple[str, str]] = []
        ap = _make_processor(logs, transcriber=StubTranscriber())

        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "VID-20260519.mp4"
            video.write_bytes(b"\x00\x00\x00\x18ftypmp42")
            text = ap.to_text(video)

        self.assertEqual("", text)
        levels = {level for _, level in logs}
        self.assertIn("WARNING", levels)
        self.assertNotIn("ERROR", levels)


class DirectReadRoutingTests(unittest.TestCase):
    """read_text_file instrada i nuovi formati .xml/.doc verso l'estrattore giusto."""

    def test_xml_input_read_directly(self):
        logs: list[tuple[str, str]] = []
        ap = _make_processor(logs)
        with tempfile.TemporaryDirectory() as tmp:
            xml = Path(tmp) / "dati.xml"
            xml.write_text(
                "<root><a>Alfa</a><b>Beta</b></root>", encoding="utf-8"
            )
            result, pending = ap.read_text_file(xml)
        self.assertIn("Alfa", result.combined_text)
        self.assertIn("Beta", result.combined_text)
        self.assertEqual([], pending)
        self.assertTrue(any("XML" in m for m, _ in logs))

    def test_unsupported_attachment_skipped_as_warning(self):
        logs: list[tuple[str, str]] = []
        ap = _make_processor(logs)
        with tempfile.TemporaryDirectory() as tmp:
            weird = Path(tmp) / "strano.xyz"
            weird.write_bytes(b"\x01\x02\x03")
            self.assertEqual("", ap.to_text(weird))
        self.assertTrue(any(level == "WARNING" for _, level in logs))


if __name__ == "__main__":
    unittest.main()
