"""Test dell'archiviazione segreti nel keyring (utils/secret_store.py) e della
sua integrazione con load_config/save_config."""

import json
import os
import tempfile
import unittest
from pathlib import Path

from config.settings import AppConfig, load_config, save_config
from utils import secret_store


class _FakeKeyring:
    """Backend keyring in-memory per i test (niente Credential Manager reale)."""

    class _DeleteError(Exception):
        pass

    def __init__(self):
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service, name):
        return self.store.get((service, name))

    def set_password(self, service, name, value):
        self.store[(service, name)] = value

    def delete_password(self, service, name):
        if (service, name) not in self.store:
            raise self._FakeKeyring._DeleteError("not found")
        del self.store[(service, name)]


class SecretStoreTestBase(unittest.TestCase):
    def setUp(self):
        # Inietta il fake e assicurati che il keyring NON sia disabilitato.
        os.environ.pop("TURBOMD_DISABLE_KEYRING", None)
        self._saved_mod = secret_store._keyring_module
        self._saved_attempted = secret_store._import_attempted
        self.fake = _FakeKeyring()
        secret_store._keyring_module = self.fake
        secret_store._import_attempted = True

    def tearDown(self):
        secret_store._keyring_module = self._saved_mod
        secret_store._import_attempted = self._saved_attempted
        os.environ.pop("TURBOMD_DISABLE_KEYRING", None)


class SecretStoreUnitTests(SecretStoreTestBase):
    def test_set_get_round_trip(self):
        self.assertTrue(secret_store.set_secret("gemini_api_key", "segreto"))
        self.assertEqual(secret_store.get_secret("gemini_api_key"), "segreto")

    def test_empty_value_deletes(self):
        secret_store.set_secret("gemini_api_key", "x")
        self.assertTrue(secret_store.set_secret("gemini_api_key", ""))
        self.assertIsNone(secret_store.get_secret("gemini_api_key"))

    def test_disabled_via_env(self):
        os.environ["TURBOMD_DISABLE_KEYRING"] = "1"
        self.assertFalse(secret_store.is_available())
        self.assertFalse(secret_store.set_secret("gemini_api_key", "x"))
        self.assertIsNone(secret_store.get_secret("gemini_api_key"))


class ConfigKeyringIntegrationTests(SecretStoreTestBase):
    def test_save_moves_secret_to_keyring_and_blanks_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            save_config(AppConfig(gemini_api_key="abc123"), config_path=path)

            on_disk = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(on_disk["gemini_api_key"], "")  # non in chiaro
            self.assertEqual(
                self.fake.store[(secret_store.SERVICE_NAME, "gemini_api_key")],
                "abc123",
            )

            loaded = load_config(config_path=path, project_dir=Path(tmp))
            self.assertEqual(loaded.gemini_api_key, "abc123")

    def test_legacy_plaintext_key_is_migrated_on_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            # Simula un config "vecchio" con la chiave in chiaro nel JSON.
            path.write_text(
                json.dumps({"gemini_api_key": "legacy-key"}), encoding="utf-8"
            )

            cfg = load_config(config_path=path, project_dir=Path(tmp))
            self.assertEqual(cfg.gemini_api_key, "legacy-key")

            # Al primo salvataggio il segreto migra nel keyring e sparisce dal JSON.
            save_config(cfg, config_path=path)
            on_disk = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(on_disk["gemini_api_key"], "")
            self.assertEqual(secret_store.get_secret("gemini_api_key"), "legacy-key")

    def test_whatsapp_key_also_stored_in_keyring(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            save_config(
                AppConfig(whatsapp_backup_key="0" * 64), config_path=path
            )
            on_disk = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(on_disk["whatsapp_backup_key"], "")
            self.assertEqual(secret_store.get_secret("whatsapp_backup_key"), "0" * 64)


if __name__ == "__main__":
    unittest.main()
