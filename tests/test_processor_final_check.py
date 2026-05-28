import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from config.settings import AppConfig
from pipeline.events import BatchCompleteEvent, FinalCheckCompleteEvent
from pipeline.final_check import FinalCheckResult
from pipeline.processor import DocumentProcessor


class ProcessorFinalCheckTests(unittest.TestCase):
    def test_process_batch_emits_final_check_event(self):
        events: list = []

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            txt_path = root / "documento.txt"
            txt_path.write_text("Contenuto di prova.", encoding="utf-8")

            config = AppConfig(
                gemini_api_key="test-key",
                run_extraction=False,
                run_ocr=False,
                final_error_check=True,
            )
            processor = DocumentProcessor(config, events.append)

            fake_result = FinalCheckResult(
                passed=False,
                issues=[{
                    "file": "documento.md",
                    "type": "test_issue",
                    "description": "Problema simulato",
                }],
                error_message="test_issue: Problema simulato",
            )

            with patch(
                "pipeline.processor.run_final_error_check",
                return_value=fake_result,
            ):
                processor.process_batch([txt_path], threading.Event())

            final_events = [
                e for e in events if isinstance(e, FinalCheckCompleteEvent)
            ]
            self.assertEqual(1, len(final_events))
            event = final_events[0]
            self.assertFalse(event.passed)
            self.assertEqual([txt_path], event.affected_pdf_paths)
            self.assertFalse(event.check_failed_technically)

            batch_events = [
                e for e in events if isinstance(e, BatchCompleteEvent)
            ]
            self.assertEqual(1, len(batch_events))
            self.assertTrue(batch_events[0].final_check_failed)
            self.assertEqual(1, batch_events[0].final_check_issue_count)

    def test_process_batch_skips_final_check_when_disabled(self):
        events: list = []

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            txt_path = root / "documento.txt"
            txt_path.write_text("Contenuto di prova.", encoding="utf-8")

            config = AppConfig(
                gemini_api_key="test-key",
                run_extraction=False,
                run_ocr=False,
                final_error_check=False,
            )
            processor = DocumentProcessor(config, events.append)

            with patch("pipeline.processor.run_final_error_check") as mock_check:
                processor.process_batch([txt_path], threading.Event())
                mock_check.assert_not_called()

            final_events = [
                e for e in events if isinstance(e, FinalCheckCompleteEvent)
            ]
            self.assertEqual([], final_events)


if __name__ == "__main__":
    unittest.main()
