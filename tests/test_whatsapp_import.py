"""Test per l'importazione WhatsApp (parser DB, pacchetto .wachat, helper adb)."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from ocr.audio_transcriber import AUDIO_MIME_TYPES
from pipeline.constants import AUDIO_EXTENSIONS, DIRECT_READ_FORMATS
from pipeline.whatsapp_sources import extract_whatsapp_parts
from whatsapp.adb_bridge import parse_contacts, parse_devices
from whatsapp.backup_decryptor import BackupDecryptError, normalize_key
from whatsapp.msgstore_reader import MsgStoreReader, normalize_number
from whatsapp.package_builder import BuildStats, TranscriptEntry, build_wachat


def _build_modern_db(path: Path) -> None:
    con = sqlite3.connect(str(path))
    con.executescript(
        """
        CREATE TABLE jid (_id INTEGER PRIMARY KEY, raw_string TEXT);
        CREATE TABLE chat (_id INTEGER PRIMARY KEY, jid_row_id INTEGER, subject TEXT);
        CREATE TABLE message (
            _id INTEGER PRIMARY KEY, chat_row_id INTEGER, from_me INTEGER,
            sender_jid_row_id INTEGER, timestamp INTEGER, text_data TEXT
        );
        CREATE TABLE message_media (
            message_row_id INTEGER, file_path TEXT, mime_type TEXT
        );
        """
    )
    # jid 1 = contatto 1:1, jid 2 = me (mittente nei from_me non usato)
    con.execute("INSERT INTO jid (_id, raw_string) VALUES (1, '393331234567@s.whatsapp.net')")
    con.execute("INSERT INTO chat (_id, jid_row_id, subject) VALUES (10, 1, NULL)")
    # 3 messaggi: testo entrante, immagine uscente, nota vocale entrante
    con.execute("INSERT INTO message VALUES (1, 10, 0, 1, 1000, 'Ciao!')")
    con.execute("INSERT INTO message VALUES (2, 10, 1, NULL, 2000, NULL)")
    con.execute("INSERT INTO message VALUES (3, 10, 0, 1, 3000, NULL)")
    con.execute(
        "INSERT INTO message_media VALUES "
        "(2, 'Media/WhatsApp Images/IMG-1.jpg', 'image/jpeg')"
    )
    con.execute(
        "INSERT INTO message_media VALUES "
        "(3, 'Media/WhatsApp Voice Notes/PTT-1.opus', 'audio/ogg')"
    )
    con.commit()
    con.close()


def _build_legacy_db(path: Path) -> None:
    con = sqlite3.connect(str(path))
    con.executescript(
        """
        CREATE TABLE messages (
            _id INTEGER PRIMARY KEY, key_remote_jid TEXT, key_from_me INTEGER,
            data TEXT, timestamp INTEGER, media_wa_type INTEGER,
            media_mime_type TEXT, remote_resource TEXT
        );
        """
    )
    con.execute(
        "INSERT INTO messages VALUES "
        "(1, '393331234567@s.whatsapp.net', 0, 'Vecchio messaggio', 1000, 0, NULL, NULL)"
    )
    con.execute(
        "INSERT INTO messages VALUES "
        "(2, '393331234567@s.whatsapp.net', 1, 'Risposta', 2000, 0, NULL, NULL)"
    )
    con.commit()
    con.close()


class ConstantsTests(unittest.TestCase):
    def test_opus_registered(self):
        self.assertIn(".opus", AUDIO_EXTENSIONS)
        self.assertEqual("audio/ogg", AUDIO_MIME_TYPES[".opus"])

    def test_wachat_is_direct_read(self):
        self.assertIn(".wachat", DIRECT_READ_FORMATS)


class AdbParseTests(unittest.TestCase):
    def test_ready_device(self):
        out = "List of devices attached\nABC123\tdevice\n"
        devs = parse_devices(out)
        self.assertEqual(1, len(devs))
        self.assertEqual("ABC123", devs[0].serial)
        self.assertEqual("device", devs[0].state)

    def test_unauthorized_and_daemon_lines(self):
        out = ("* daemon not running; starting now *\n"
               "* daemon started successfully *\n"
               "List of devices attached\n"
               "XYZ\tunauthorized\n")
        devs = parse_devices(out)
        self.assertEqual(1, len(devs))
        self.assertEqual("unauthorized", devs[0].state)

    def test_no_devices(self):
        self.assertEqual([], parse_devices("List of devices attached\n\n"))


class DecryptKeyTests(unittest.TestCase):
    def test_valid_key_normalised(self):
        raw = "AA" * 32
        self.assertEqual(raw.lower(), normalize_key(raw))

    def test_key_with_spaces(self):
        spaced = " ".join(["abcd"] * 16)  # 64 hex con spazi
        self.assertEqual("abcd" * 16, normalize_key(spaced))

    def test_invalid_key_rejected(self):
        with self.assertRaises(BackupDecryptError):
            normalize_key("troppo-corta")


class MsgStoreModernTests(unittest.TestCase):
    def test_list_and_read_with_media(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "msgstore.db"
            _build_modern_db(db)
            reader = MsgStoreReader(db)
            self.assertEqual("modern", reader.schema)

            chats = reader.list_chats()
            self.assertEqual(1, len(chats))
            chat = chats[0]
            self.assertEqual("+393331234567", chat.name)
            self.assertEqual(3, chat.count)
            self.assertFalse(chat.is_group)

            msgs = reader.read_messages(chat)
            self.assertEqual(3, len(msgs))
            self.assertEqual("Ciao!", msgs[0].text)
            self.assertEqual("+393331234567", msgs[0].sender_label)
            self.assertEqual("Io", msgs[1].sender_label)
            self.assertEqual("Media/WhatsApp Images/IMG-1.jpg", msgs[1].media_relpath)
            self.assertEqual(
                "Media/WhatsApp Voice Notes/PTT-1.opus", msgs[2].media_relpath)

    def test_date_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "msgstore.db"
            _build_modern_db(db)
            reader = MsgStoreReader(db)
            chat = reader.list_chats()[0]
            # solo il secondo messaggio (timestamp 2000)
            msgs = reader.read_messages(chat, from_ms=1500, to_ms=2500)
            self.assertEqual(1, len(msgs))
            self.assertEqual(2000, msgs[0].ts)

    def test_count_range(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "msgstore.db"
            _build_modern_db(db)
            reader = MsgStoreReader(db)
            chat = reader.list_chats()[0]
            self.assertEqual((3, 2), reader.count_range(chat))            # tutto
            self.assertEqual((1, 1), reader.count_range(chat, 1500, 2500))  # solo img


class MsgStoreLegacyTests(unittest.TestCase):
    def test_legacy_text_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "msgstore.db"
            _build_legacy_db(db)
            reader = MsgStoreReader(db)
            self.assertEqual("legacy", reader.schema)
            chats = reader.list_chats()
            self.assertEqual(1, len(chats))
            msgs = reader.read_messages(chats[0])
            self.assertEqual(2, len(msgs))
            self.assertEqual("Vecchio messaggio", msgs[0].text)
            self.assertEqual("Io", msgs[1].sender_label)


class PackageRoundTripTests(unittest.TestCase):
    def test_build_and_extract(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            media_dir = tmp / "media"
            media_dir.mkdir()
            (media_dir / "img.jpg").write_bytes(b"fakeimg")
            # gone.jpg non creato → media non disponibile

            entries = [
                TranscriptEntry("2026-01-01 10:00", "Mario", "Ciao", None),
                TranscriptEntry("2026-01-01 10:01", "Io", "", "img.jpg"),
                TranscriptEntry("2026-01-01 10:02", "Mario", "", "gone.jpg"),
            ]
            out = tmp / "chat.wachat"
            build_wachat(
                out, "Mario Rossi", "intera conversazione", entries, media_dir,
                BuildStats(message_count=3, media_count=1),
            )
            self.assertTrue(out.exists())

            def fake_process(path: Path) -> str:
                return f"TEXTOF:{path.name}"

            combined = extract_whatsapp_parts(
                out, fake_process, lambda *_a, **_k: None,
            )
            self.assertIn("Ciao", combined)
            self.assertIn("TEXTOF:img.jpg", combined)
            self.assertIn("[media non disponibile sul telefono]", combined)
            self.assertNotIn("[[MEDIA:", combined)  # tutti i placeholder risolti


class PipelineRoutingTests(unittest.TestCase):
    """Verifica che un .wachat sia instradato e unito da AttachmentProcessor."""

    def test_wachat_routes_through_attachment_processor(self):
        from config.settings import AppConfig
        from pipeline.attachment_processor import AttachmentProcessor

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            media_dir = tmp / "media"
            media_dir.mkdir()
            (media_dir / "note.txt").write_text(
                "CONTENUTO ALLEGATO", encoding="utf-8")
            entries = [
                TranscriptEntry("2026-01-01 10:00", "Mario", "Messaggio uno", None),
                TranscriptEntry("2026-01-01 10:01", "Io", "", "note.txt"),
            ]
            out = tmp / "c.wachat"
            build_wachat(out, "Mario", "intera conversazione", entries,
                         media_dir, BuildStats())

            ap = AttachmentProcessor(
                config=AppConfig(), ocr_pipeline=None,
                emit_log=lambda *a, **k: None,
                on_page_complete=None, on_page_skipped=None,
                on_page_native_text=None, audio_transcriber=None,
            )
            ocr_result, pending = ap.read_text_file(out)
            self.assertEqual([], pending)
            self.assertIn("Messaggio uno", ocr_result.combined_text)
            self.assertIn("CONTENUTO ALLEGATO", ocr_result.combined_text)


class ContactResolutionTests(unittest.TestCase):
    def test_normalize_number_variants(self):
        self.assertEqual("3331234567", normalize_number("393331234567"))
        self.assertEqual("3331234567", normalize_number("+39 333 1234567"))
        self.assertEqual("3331234567", normalize_number("333 1234567"))
        self.assertEqual("3331234567",
                         normalize_number("393331234567@s.whatsapp.net"))

    def test_parse_contacts(self):
        out = parse_contacts(
            "Row: 0 display_name=Mario Rossi, data1=+39 333 1234567\n"
            "Row: 1 display_name=Anna, data1=3351234567\n"
            "Row: 2 display_name=null, data1=39000\n"
        )
        self.assertEqual("Mario Rossi", out["3331234567"])
        self.assertEqual("Anna", out["3351234567"])
        self.assertNotIn("39000", out)  # nome null → scartato

    def test_reader_resolves_contact_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "msgstore.db"
            _build_modern_db(db)
            contacts = {"3331234567": "Mario Rossi"}
            reader = MsgStoreReader(db, contacts=contacts)
            chat = reader.list_chats()[0]
            self.assertEqual("Mario Rossi", chat.name)
            msgs = reader.read_messages(chat)
            self.assertEqual("Mario Rossi", msgs[0].sender_label)  # entrante
            self.assertEqual("Io", msgs[1].sender_label)           # from_me


class AudioRetryPolicyTests(unittest.TestCase):
    """Gli errori client 4xx (es. video senza audio) non vanno ritentati."""

    def test_status_code_400_not_retried(self):
        from ocr.audio_transcriber import _is_non_retryable

        class Err(Exception):
            status_code = 400

        self.assertTrue(_is_non_retryable(Err("could not be decoded")))

    def test_message_based_400(self):
        from ocr.audio_transcriber import _is_non_retryable
        self.assertTrue(_is_non_retryable(
            Exception("API error occurred: Status 400. Body: could not be decoded")))

    def test_429_is_retryable(self):
        from ocr.audio_transcriber import _is_non_retryable

        class Err(Exception):
            status_code = 429

        self.assertFalse(_is_non_retryable(Err("rate limit")))

    def test_500_is_retryable(self):
        from ocr.audio_transcriber import _is_non_retryable

        class Err(Exception):
            status_code = 500

        self.assertFalse(_is_non_retryable(Err("server error")))


if __name__ == "__main__":
    unittest.main()
