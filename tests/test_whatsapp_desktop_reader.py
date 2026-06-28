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
    # Evita che read_messages tenti di leggere l'IndexedDB reale della macchina:
    # nei test l'indice è assente (comportamento v1, solo testo) salvo iniezione.
    r._index_loaded = True
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


def _with_index(r: WhatsAppDesktopReader) -> WhatsAppDesktopReader:
    """Inietta un indice IndexedDB finto per testare la risoluzione mittenti."""
    from whatsapp.desktop_indexeddb import Sender, WhatsAppIndex
    r._index = WhatsAppIndex(
        senders={
            1: Sender(False, None),                    # DM ricevuto → contatto
            2: Sender(True, None),                     # DM inviato → "Tu"
            4: Sender(False, "45625504731340@lid"),    # gruppo, autore @lid
        },
        group_subjects={"120363039986498251@g.us": "Gruppo Test"},
        name_by_jid={"393282669681@s.whatsapp.net": "Massimiliano Fior",
                     "45625504731340@lid": "Anna"},
        lid_to_phone={"45625504731340@lid": "393358294684@c.us"},
    )
    r._index_loaded = True
    return r


class IndexBackedTests(unittest.TestCase):
    def test_group_name_from_subject(self):
        with tempfile.TemporaryDirectory() as d:
            r = _with_index(_reader(Path(d)))
            self.assertEqual(r.chat_name("120363039986498251@g.us"), "Gruppo Test")

    def test_dm_senders_from_me_and_contact(self):
        with tempfile.TemporaryDirectory() as d:
            r = _with_index(_reader(Path(d)))
            msgs = r.read_messages("393282669681@s.whatsapp.net")
            by_text = {m.text: m for m in msgs}
            self.assertEqual(by_text["ciao"].sender, "Massimiliano Fior")
            self.assertFalse(by_text["ciao"].from_me)
            self.assertEqual(by_text["come va piscina"].sender, "Tu")
            self.assertTrue(by_text["come va piscina"].from_me)
            self.assertEqual(by_text["tutto ok"].sender, "")  # id 3: non in indice

    def test_group_author_resolved_to_name(self):
        with tempfile.TemporaryDirectory() as d:
            r = _with_index(_reader(Path(d)))
            msgs = r.read_messages("120363039986498251@g.us")
            self.assertEqual(msgs[0].sender, "Anna")
            self.assertEqual(msgs[0].sender_jid, "45625504731340@lid")

    def test_markdown_includes_sender(self):
        with tempfile.TemporaryDirectory() as d:
            r = _with_index(_reader(Path(d)))
            chat = next(c for c in r.list_chats()
                        if c.chat_id == "393282669681@s.whatsapp.net")
            md = build_markdown(chat, r.read_messages(chat.chat_id))
            self.assertIn("**Massimiliano Fior**:", md)
            self.assertIn("**Tu**:", md)


class WhatsAppIndexTests(unittest.TestCase):
    def _idx(self):
        from whatsapp.desktop_indexeddb import WhatsAppIndex
        return WhatsAppIndex(
            group_subjects={"120363039986498251@g.us": "Gruppo Test"},
            name_by_jid={"45625504731340@lid": "Anna"},
            lid_to_phone={"77@lid": "393358294684@c.us"},
        )

    def test_name_for_direct_and_via_phone(self):
        idx = self._idx()
        idx.name_by_jid["393358294684@c.us"] = "Mario"
        self.assertEqual(idx.name_for("45625504731340@lid"), "Anna")
        # 77@lid non ha nome diretto ma è mappato a un numero con nome
        self.assertEqual(idx.name_for("77@lid"), "Mario")
        self.assertIsNone(idx.name_for("999@lid"))

    def test_phone_for(self):
        idx = self._idx()
        self.assertEqual(idx.phone_for("393282669681@s.whatsapp.net"), "393282669681")
        self.assertEqual(idx.phone_for("77@lid"), "393358294684")
        self.assertIsNone(idx.phone_for("999@lid"))

    def test_group_title(self):
        self.assertEqual(self._idx().group_title("120363039986498251@g.us"),
                         "Gruppo Test")
        self.assertIsNone(self._idx().group_title("nope@g.us"))


class SendersForChatTests(unittest.TestCase):
    def test_injected_index_returns_full_map(self):
        # Senza wrapper (indice iniettato), senders_for_chat ritorna la mappa piena.
        from whatsapp.desktop_indexeddb import Sender, WhatsAppIndex
        idx = WhatsAppIndex(senders={1: Sender(True, None)})
        self.assertEqual(idx.senders_for_chat("qualsiasi@g.us"), {1: Sender(True, None)})
        idx.close()  # no-op senza wrapper


class DiskCacheTests(unittest.TestCase):
    def _idx(self):
        from whatsapp.desktop_indexeddb import Sender, WhatsAppIndex
        return WhatsAppIndex(
            group_subjects={"120363039986498251@g.us": "Gruppo Test"},
            name_by_jid={"45625504731340@lid": "Anna"},
            lid_to_phone={"45625504731340@lid": "393358294684@c.us"},
            senders={1: Sender(True, None), 2: Sender(False, None),
                     3: Sender(False, "45625504731340@lid")},
        )

    def test_round_trip(self):
        from whatsapp.desktop_indexeddb import _load_cache, _save_cache
        with tempfile.TemporaryDirectory() as d:
            cf = Path(d) / "index.json"
            _save_cache(cf, "FP1", self._idx())
            r = _load_cache(cf, "FP1")
            self.assertIsNotNone(r)
            self.assertEqual(r.group_subjects, {"120363039986498251@g.us": "Gruppo Test"})
            self.assertTrue(r.senders[1].from_me)
            self.assertFalse(r.senders[2].from_me)
            self.assertIsNone(r.senders[2].author_jid)
            self.assertEqual(r.senders[3].author_jid, "45625504731340@lid")
            # la mappa piena è usata da senders_for_chat (nessun wrapper)
            self.assertEqual(r.senders_for_chat("qualunque"), r.senders)

    def test_fingerprint_mismatch_and_missing(self):
        from whatsapp.desktop_indexeddb import _load_cache, _save_cache
        with tempfile.TemporaryDirectory() as d:
            cf = Path(d) / "index.json"
            _save_cache(cf, "FP-OLD", self._idx())
            self.assertIsNone(_load_cache(cf, "FP-NEW"))
            self.assertIsNone(_load_cache(Path(d) / "nope.json", "FP-OLD"))


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
