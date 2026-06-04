import tempfile
import threading
import unittest
from pathlib import Path

from config.settings import AppConfig
from pipeline.processor import DocumentProcessor


class OutputJsonTests(unittest.TestCase):
    def test_txt_writes_json_when_enabled(self):
        events = []
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            txt_path = root / "documento.txt"
            txt_path.write_text("Contenuto di prova.", encoding="utf-8")

            config = AppConfig(
                gemini_api_key="test-key",
                run_extraction=False,
                run_ocr=False,
                output_formats=["json"],
            )
            processor = DocumentProcessor(config, events.append)

            success, _cost_info, _batch_doc = processor.process_single(
                txt_path,
                threading.Event(),
            )

            self.assertTrue(success)
            self.assertTrue((root / "documento.json").exists())
            self.assertFalse((root / "documento.md").exists())

    def test_txt_writes_md_and_json_when_both_enabled(self):
        events = []
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            txt_path = root / "documento.txt"
            txt_path.write_text("Contenuto di prova.", encoding="utf-8")

            config = AppConfig(
                gemini_api_key="test-key",
                run_extraction=False,
                run_ocr=False,
                output_formats=["markdown", "json"],
            )
            processor = DocumentProcessor(config, events.append)

            success, _cost_info, _batch_doc = processor.process_single(
                txt_path,
                threading.Event(),
            )

            self.assertTrue(success)
            self.assertTrue((root / "documento.md").exists())
            self.assertTrue((root / "documento.json").exists())


if __name__ == "__main__":
    unittest.main()
