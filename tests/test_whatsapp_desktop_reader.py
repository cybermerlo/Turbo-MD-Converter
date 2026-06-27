"""Test della logica dati del lettore WhatsApp Desktop (senza la parte crypto
Windows-only): risoluzione nomi, lista chat, filtri messaggi, Markdown."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from whatsapp.desktop_crypto import DecryptedStore
from whatsapp.desktop_reader import WhatsAppDesktopReader, build_markdown


def _make_dbs(tmp: Path):
    msg = tmp / "genericStorage.clear.db"
    con = sqlite3.connect(str(msg))
    con.execute("CREATE TABLE message (rowid INTEGER PRIMARY KEY, id TEXT, "
                "chatId TEXT, timestamp TEXT, text TEXT)")
    rows = [
        ("1", "393282669681@s.whatsapp.net", "1000000000", "ciao"),
        ("2", "393282669681@s.whatsapp.net", "1000086400", "come va piscina"),
        ("3", "393282669681@s.whatsapp.net", "1000172800", "tutto ok"),
        ("4", "120363039986498251@g.us", "1000200000", "messaggio di gruppo"),
        ("5", "45625504731340@lid", "1000300000", "ehi"),
    ]
    con.executemany(
        "INSERT INTO message (id, chatId, timestamp, text) VALUES (?,?,?,?)", rows)
    con.commit()
    con.close()

    contacts = tmp / "contacts.clear.db"
    con = sqlite3.connect(str(contacts))
    con.execute("CREATE TABLE UserStatuses (StatusID INTEGER PRIMARY KEY, Jid TEXT, "
                "DbLid TEXT, ContactName TEXT, FirstName TEXT, PushName TEXT)")
    con.executemany(
        "INSERT INTO UserStatuses (Jid, DbLid, ContactName, FirstName, PushName) "
        "VALUES (?,?,?,?,?)",
        [
            ("393282669681@s.whatsapp.net", None, "Massimiliano Fior", None, None),
            ("999@s.whatsapp.net", "45625504731340@lid", None, "Anna", None),
        ],
    )
    con.commit()
    con.close()
    return msg, contacts


def _reader(tmp: Path) -> WhatsAppDesktopReader:
    msg, contacts = _make_dbs(tmp)
    r = WhatsAppDesktopReader()
    r._store = DecryptedStore(workdir=tmp, messages_db=msg, contacts_db=contacts)
    r._names = r._load_names()
    return r


class NameResolutionTests(unittest.TestCase):
    def test_dm_contact_name(self):
        with tempfile.TemporaryDirectory() as d:
            r = _reader(Path(d))
            self.assertEqual(r.chat_name("393282669681@s.whatsapp.net"),
                             "Massimiliano Fior")

    def test_lid_resolved_via_dblid(self):
        with tempfile.TemporaryDirectory() as d:
            r = _reader(Path(d))
            self.assertEqual(r.chat_name("45625504731340@lid"), "Anna")

    def test_group_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            r = _reader(Path(d))
            self.assertTrue(r.chat_name("120363039986498251@g.us").startswith("Gruppo"))

    def test_unknown_phone_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            r = _reader(Path(d))
            self.assertEqual(r.chat_name("39111@s.whatsapp.net"), "+39111")


class ChatAndMessageTests(unittest.TestCase):
    def test_list_chats_sorted_and_counted(self):
        with tempfile.TemporaryDirectory() as d:
            chats = _reader(Path(d)).list_chats()
            self.assertEqual(len(chats), 3)
            # ordinate per ultimo timestamp desc → il @lid (1000300000) è primo
            self.assertEqual(chats[0].chat_id, "45625504731340@lid")
            dm = next(c for c in chats if c.chat_id.endswith("s.whatsapp.net"))
            self.assertEqual(dm.message_count, 3)
            self.assertFalse(dm.is_group)
            self.assertTrue(next(c for c in chats if c.is_group).is_group)

    def test_read_messages_date_and_text_filters(self):
        with tempfile.TemporaryDirectory() as d:
            r = _reader(Path(d))
            cid = "393282669681@s.whatsapp.net"
            self.assertEqual(len(r.read_messages(cid)), 3)
            # solo dal secondo giorno in poi
            self.assertEqual(len(r.read_messages(cid, since=1000086400)), 2)
            # filtro testo
            hits = r.read_messages(cid, query="piscina")
            self.assertEqual([m.text for m in hits], ["come va piscina"])
            # ordine cronologico
            allm = r.read_messages(cid)
            self.assertEqual([m.ts for m in allm], sorted(m.ts for m in allm))


class MarkdownTests(unittest.TestCase):
    def test_build_markdown(self):
        with tempfile.TemporaryDirectory() as d:
            r = _reader(Path(d))
            chats = r.list_chats()
            dm = next(c for c in chats if c.name == "Massimiliano Fior")
            md = build_markdown(dm, r.read_messages(dm.chat_id))
            self.assertIn("# WhatsApp — Massimiliano Fior", md)
            self.assertIn("3 messaggi", md)
            self.assertIn("come va piscina", md)
            self.assertIn("## ", md)  # intestazione di giorno

    def test_build_markdown_empty(self):
        with tempfile.TemporaryDirectory() as d:
            r = _reader(Path(d))
            from whatsapp.desktop_reader import Chat
            md = build_markdown(Chat("x@g.us", "Vuota", "group", 0, 0), [])
            self.assertIn("Nessun messaggio", md)


if __name__ == "__main__":
    unittest.main()
