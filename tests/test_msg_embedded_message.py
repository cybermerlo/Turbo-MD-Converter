"""Regressione: un .msg con un allegato di tipo MESSAGGIO INCORPORATO.

extract_msg espone gli allegati-messaggio con `.data` = oggetto Message (non
bytes). Prima della correzione il pipeline provava a scriverlo con write_bytes,
sollevando "memoryview: a bytes-like object is required, not 'Message'". La
correzione lo espande ricorsivamente. I test usano messaggi fittizi duck-typed,
così non serve installare extract_msg.
"""

import threading
import unittest
from pathlib import Path

from pipeline.email_sources import _extract_msg_message


class _FakeAttachment:
    def __init__(self, data, long_name=None, short_name=None):
        self.data = data
        self.longFilename = long_name
        self.shortFilename = short_name


class _FakeMsg:
    """Duck-type minimale di un messaggio extract_msg (top-level o incorporato)."""
    def __init__(self, *, subject="", sender="", to="", cc="", date="",
                 body="", attachments=None):
        self.subject = subject
        self.sender = sender
        self.to = to
        self.cc = cc
        self.date = date
        self.body = body
        self.attachments = attachments or []


def _read_as_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


class MsgEmbeddedMessageTests(unittest.TestCase):
    def setUp(self):
        self.logs = []
        self.emit_log = lambda message, level: self.logs.append((level, message))

    def test_embedded_message_is_expanded_not_crashing(self):
        # Messaggio incorporato: ha corpo proprio e un suo allegato di testo.
        embedded = _FakeMsg(
            subject="Comunicazione originale",
            sender="banca@example.com",
            body="Testo della mail incorporata.",
            attachments=[
                _FakeAttachment(
                    "Contenuto del PDF allegato alla mail incorporata.".encode(),
                    long_name="Contratto.txt",
                ),
            ],
        )
        # Messaggio top-level: un allegato bytes normale + il messaggio incorporato
        # (il cui .data e' un oggetto Message, non bytes: prima faceva crashare).
        top = _FakeMsg(
            subject="PEC con allegati",
            sender="pec@example.com",
            body="Corpo del messaggio principale.",
            attachments=[
                _FakeAttachment(
                    "Testo di un allegato normale.".encode(),
                    long_name="Nota.txt",
                ),
                _FakeAttachment(embedded, long_name="allegato_1"),
            ],
        )

        body, atts = _extract_msg_message(
            top, Path("PEC.msg"), _read_as_text, self.emit_log, threading.Event(),
        )

        # Il corpo principale contiene header + testo.
        self.assertIn("Corpo del messaggio principale.", body)
        self.assertIn("Subject: PEC con allegati", body)

        # Due documenti-allegato: la nota normale e il messaggio incorporato.
        filenames = [a.filename for a in atts]
        self.assertIn("Nota.txt", filenames)
        # Il nome senza estensione riceve il suffisso .msg.
        self.assertIn("allegato_1.msg", filenames)

        joined = "\n".join(a.text for a in atts)
        self.assertIn("Testo di un allegato normale.", joined)
        # Il corpo e l'allegato annidato del messaggio incorporato sono espansi.
        self.assertIn("Testo della mail incorporata.", joined)
        self.assertIn("Contenuto del PDF allegato alla mail incorporata.", joined)

        # Indici unici (necessario per i nomi file in modalita' separata).
        indices = [a.index for a in atts]
        self.assertEqual(len(indices), len(set(indices)))

    def test_unknown_attachment_type_is_skipped_without_crash(self):
        top = _FakeMsg(
            body="Corpo.",
            attachments=[_FakeAttachment(object(), long_name="strano.bin")],
        )
        body, atts = _extract_msg_message(
            top, Path("m.msg"), _read_as_text, self.emit_log, threading.Event(),
        )
        self.assertIn("Corpo.", body)
        self.assertEqual(atts, [])
        self.assertTrue(any(level == "WARNING" for level, _ in self.logs))


if __name__ == "__main__":
    unittest.main()
