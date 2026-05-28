import unittest
from unittest.mock import MagicMock, patch

from config.defaults import DEFAULT_FINAL_CHECK_PROMPT
from pipeline.final_check import (
    FinalCheckResult,
    build_md_documents_block,
    run_final_error_check,
)


class _FakeUsage:
    prompt_token_count = 120
    candidates_token_count = 45


class _FakeResponse:
    def __init__(self, text: str):
        self.text = text
        self.usage_metadata = _FakeUsage()


class FinalErrorCheckTests(unittest.TestCase):
    def test_build_md_documents_block(self):
        block = build_md_documents_block([
            ("doc1.md", "Contenuto uno"),
            ("doc2.md", "Contenuto due"),
        ])
        self.assertIn("--- FILE: doc1.md ---", block)
        self.assertIn("Contenuto uno", block)
        self.assertIn("--- FILE: doc2.md ---", block)

    @patch("pipeline.final_check.genai.Client")
    def test_passed_response(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.models.generate_content.return_value = _FakeResponse(
            '{"passed": true, "issues": []}'
        )

        result = run_final_error_check(
            md_documents=[("test.md", "Testo valido")],
            api_key="test-key",
            model_id="gemini-3.1-flash-lite",
            prompt_template=DEFAULT_FINAL_CHECK_PROMPT,
        )

        self.assertIsInstance(result, FinalCheckResult)
        self.assertTrue(result.passed)
        self.assertEqual([], result.issues)
        self.assertFalse(result.check_failed_technically)
        self.assertEqual(120, result.input_tokens)
        self.assertEqual(45, result.output_tokens)

    @patch("pipeline.final_check.genai.Client")
    def test_failed_response_with_json_fence(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.models.generate_content.return_value = _FakeResponse(
            '```json\n'
            '{"passed": false, "issues": ['
            '{"file": "doc.md", "type": "truncation", "description": "Testo troncato"}'
            ']}\n```'
        )

        result = run_final_error_check(
            md_documents=[("doc.md", "Testo incompleto...")],
            api_key="test-key",
            model_id="gemini-3.1-flash-lite",
            prompt_template=DEFAULT_FINAL_CHECK_PROMPT,
        )

        self.assertFalse(result.passed)
        self.assertEqual(1, len(result.issues))
        self.assertEqual("doc.md", result.issues[0]["file"])
        self.assertEqual("truncation", result.issues[0]["type"])
        self.assertIn("troncato", result.error_message)

    @patch("pipeline.final_check.genai.Client")
    def test_technical_failure_on_invalid_json(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.models.generate_content.return_value = _FakeResponse(
            "Risposta non JSON"
        )

        result = run_final_error_check(
            md_documents=[("doc.md", "Testo")],
            api_key="test-key",
            model_id="gemini-3.1-flash-lite",
            prompt_template=DEFAULT_FINAL_CHECK_PROMPT,
        )

        self.assertFalse(result.passed)
        self.assertTrue(result.check_failed_technically)
        self.assertIn("non interpretabile", result.error_message)


if __name__ == "__main__":
    unittest.main()
