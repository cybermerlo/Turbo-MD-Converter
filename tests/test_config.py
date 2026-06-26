"""Test di persistenza e normalizzazione della configurazione (config/settings.py)."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from config.defaults import DEFAULT_OCR_MODEL, DEFAULT_OCR_PROMPT
from config.settings import AppConfig, load_config, save_config


def setUpModule():
    # Questi test verificano la persistenza/normalizzazione del JSON: disabilita
    # il keyring così i segreti restano nel JSON in modo deterministico (e i test
    # non scrivono nel Credential Manager reale della macchina).
    os.environ["TURBOMD_DISABLE_KEYRING"] = "1"


def tearDownModule():
    os.environ.pop("TURBOMD_DISABLE_KEYRING", None)


class SaveLoadRoundTripTests(unittest.TestCase):
    def test_round_trip_preserves_values(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"
            cfg = AppConfig(
                gemini_api_key="abc123",
                ocr_model_id=DEFAULT_OCR_MODEL,
                output_formats=["markdown", "json"],
                rename_files=True,
                video_max_duration_min=42,
            )
            save_config(cfg, config_path=path)
            # Niente .env nella tmpdir → le chiavi restano quelle del file.
            loaded = load_config(config_path=path, project_dir=Path(tmpdir))

            self.assertEqual(loaded.gemini_api_key, "abc123")
            self.assertEqual(loaded.output_formats, ["markdown", "json"])
            self.assertTrue(loaded.rename_files)
            self.assertEqual(loaded.video_max_duration_min, 42)

    def test_save_is_atomic_no_temp_left_behind(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"
            save_config(AppConfig(gemini_api_key="x"), config_path=path)
            self.assertTrue(path.exists())
            # Nessun file temporaneo ".config-*.tmp" deve restare.
            leftovers = list(Path(tmpdir).glob(".config-*.tmp"))
            self.assertEqual(leftovers, [])


class LoadFilteringTests(unittest.TestCase):
    def test_unknown_keys_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"
            path.write_text(
                json.dumps({"gemini_api_key": "k", "chiave_inesistente": 99}),
                encoding="utf-8",
            )
            cfg = load_config(config_path=path, project_dir=Path(tmpdir))
            self.assertEqual(cfg.gemini_api_key, "k")
            self.assertFalse(hasattr(cfg, "chiave_inesistente"))

    def test_corrupt_json_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"
            path.write_text("{ questo non e' json valido ", encoding="utf-8")
            cfg = load_config(config_path=path, project_dir=Path(tmpdir))
            self.assertEqual(cfg.ocr_model_id, DEFAULT_OCR_MODEL)
            self.assertEqual(cfg.ocr_prompt, DEFAULT_OCR_PROMPT)

    def test_empty_output_formats_defaults_to_markdown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"
            path.write_text(json.dumps({"output_formats": []}), encoding="utf-8")
            cfg = load_config(config_path=path, project_dir=Path(tmpdir))
            self.assertEqual(cfg.output_formats, ["markdown"])

    def test_output_formats_normalized_and_deduped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"
            path.write_text(
                json.dumps({"output_formats": ["JSON", "json", "xml", "markdown"]}),
                encoding="utf-8",
            )
            cfg = load_config(config_path=path, project_dir=Path(tmpdir))
            # "xml" scartato, "JSON"/"json" deduplicati, ordine preservato.
            self.assertEqual(cfg.output_formats, ["json", "markdown"])

    def test_unsupported_ocr_model_normalized_to_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"
            path.write_text(
                json.dumps({"ocr_model_id": "modello-fantasma"}), encoding="utf-8"
            )
            cfg = load_config(config_path=path, project_dir=Path(tmpdir))
            self.assertEqual(cfg.ocr_model_id, DEFAULT_OCR_MODEL)


class EnvOverrideTests(unittest.TestCase):
    def test_env_key_overrides_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"
            save_config(AppConfig(gemini_api_key="from-file"), config_path=path)
            with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "from-env"}):
                cfg = load_config(config_path=path, project_dir=Path(tmpdir))
            self.assertEqual(cfg.gemini_api_key, "from-env")


if __name__ == "__main__":
    unittest.main()
