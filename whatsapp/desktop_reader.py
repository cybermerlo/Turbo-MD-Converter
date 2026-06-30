"""Lettura ad alto livello delle chat di WhatsApp Desktop.

Combina due sorgenti locali (nessuna connessione, nessun rischio ban):

  - **testo + chat + timestamp** dal SQLite `genericStorage` decifrato
    (`desktop_crypto.decrypt_databases()`), tabella `message(id, chatId,
    timestamp, text)` — è la cache di ricerca full-text;
  - **mittente per messaggio + nomi gruppo + nomi contatti** dall'IndexedDB del
    WebView2 (`desktop_indexeddb.load_index()`), unito al testo per `rowId`
    (== `genericStorage.message.id`, join esatto e validato).

L'indice IndexedDB è pesante da costruire (~1-2 min la prima volta): viene
caricato **una sola volta**, in modo pigro e thread-safe (`ensure_index`). Senza
indice il reader degrada al comportamento v1: solo testo, niente mittente, gruppi
senza titolo.
"""

from __future__ import annotations

import atexit
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

_log = logging.getLogger(__name__)

from whatsapp.desktop_crypto import (
    WhatsAppDesktopError,
    decrypt_databases,
    source_fingerprint,
)
from whatsapp.desktop_indexeddb import WhatsAppIndex, get_index

ME_LABEL = "Tu"


# ─── store decifrato condiviso a livello di processo ──────────────────────────
# La decifratura costa ~15s. La teniamo VIVA per la sessione dell'app e la
# riusiamo tra finestre di import, ri-decifrando solo se il DB sorgente è
# cambiato (nuovi messaggi). Simmetrico a desktop_indexeddb.get_index.
_shared_store = None
_shared_store_fp: Optional[str] = None
_shared_store_key: Optional[tuple] = None
_shared_store_lock = threading.Lock()


def _get_shared_store(localstate, oduid_hex):
    """DecryptedStore condiviso: riusa se il sorgente non è cambiato, altrimenti
    ri-decifra. **Da NON chiudere** dal chiamante (vita gestita qui, chiusura
    all'uscita dell'app)."""
    global _shared_store, _shared_store_fp, _shared_store_key
    fp = source_fingerprint(localstate)
    key = (str(localstate) if localstate else None, oduid_hex)
    with _shared_store_lock:
        if (_shared_store is not None and fp is not None
                and _shared_store_fp == fp and _shared_store_key == key):
            _log.info("WA: store decifrato riusato (nessuna ri-decifratura)")
            return _shared_store
        if _shared_store is not None:
            try:
                _shared_store.cleanup()
            except Exception:  # noqa: BLE001
                pass
            _shared_store = None
        store = decrypt_databases(localstate, oduid_hex)
        _shared_store = store
        _shared_store_fp = fp
        _shared_store_key = key
        return store


@atexit.register
def _close_shared_store() -> None:
    global _shared_store, _shared_store_fp
    if _shared_store is not None:
        try:
            _shared_store.cleanup()
        except Exception:  # noqa: BLE001
            pass
        _shared_store = None
        _shared_store_fp = None


@dataclass
class Chat:
    chat_id: str
    name: str
    kind: str           # "group" | "dm"
    message_count: int
    last_ts: int

    @property
    def is_group(self) -> bool:
        return self.kind == "group"


@dataclass
class Message:
    ts: int
    text: str
    from_me: bool = False
    sender: str = ""                 # nome visualizzato del mittente ("" se ignoto)
    sender_jid: Optional[str] = None


def _connect(db: Path):
    import sqlite3
    con = sqlite3.connect(str(db))
    try:  # unisce eventuale -wal così i messaggi recenti sono inclusi
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception:
        pass
    return con


def _kind(chat_id: str) -> str:
    return "group" if chat_id.endswith("@g.us") else "dm"


def _bare(jid: str) -> str:
    return jid.split("@", 1)[0] if jid else jid


def _to_int(mid) -> Optional[int]:
    try:
        return int(mid)
    except (TypeError, ValueError):
        return None


class WhatsAppDesktopReader:
    """Apertura/lettura del DB di WhatsApp Desktop. Usare come context manager."""

    def __init__(self, localstate: Path | None = None, oduid_hex: str | None = None):
        self._localstate = localstate
        self._oduid_hex = oduid_hex
        self._store = None
        self._names: dict[str, str] = {}          # contacts.db (fallback v1)
        self._index: Optional[WhatsAppIndex] = None
        self._index_loaded = False
        self._index_lock = threading.Lock()

    def __enter__(self) -> "WhatsAppDesktopReader":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def open(self) -> None:
        """Ottiene i DB decifrati (condivisi: ri-decifra solo se cambiati) e
        carica i nomi da contacts.db. NON tocca l'IndexedDB (vedi `ensure_index`)."""
        t0 = time.perf_counter()
        self._store = _get_shared_store(self._localstate, self._oduid_hex)
        self._names = self._load_names()
        _log.info("WA: open (store decifrato + nomi=%d) in %.1fs",
                  len(self._names), time.perf_counter() - t0)

    def close(self) -> None:
        # NB: SIA lo store decifrato SIA l'indice IndexedDB sono CONDIVISI a
        # livello di app (vedi _get_shared_store / desktop_indexeddb.get_index):
        # NON li chiudiamo qui, così la prossima finestra di import li riusa senza
        # ricostruirli. Vengono chiusi all'uscita dell'app (atexit).
        self._index = None
        self._index_loaded = False
        self._store = None

    # ─── Indice IndexedDB (mittenti, nomi gruppo, contatti) ────────────────
    def ensure_index(self, progress: Optional[Callable[[int], None]] = None) -> bool:
        """Costruisce l'indice IndexedDB una sola volta (thread-safe). Ritorna
        True se disponibile. Il primo chiamante paga ~1-2 min; gli altri
        attendono lo stesso risultato. In errore degrada a None (solo testo)."""
        with self._index_lock:
            if not self._index_loaded:
                t0 = time.perf_counter()
                try:
                    self._index = get_index(progress=progress)   # condiviso, riusato
                except Exception:  # noqa: BLE001
                    self._index = None
                self._index_loaded = True
                _log.info("WA: ensure_index TOTALE %.1fs (disponibile=%s)",
                          time.perf_counter() - t0, self._index is not None)
        return self._index is not None

    @property
    def has_index(self) -> bool:
        return self._index is not None

    # ─── Nomi contatti (contacts.db, fallback v1) ──────────────────────────
    def _load_names(self) -> dict[str, str]:
        names: dict[str, str] = {}
        if not self._store or not self._store.contacts_db:
            return names
        try:
            con = _connect(self._store.contacts_db)
            cur = con.execute(
                "SELECT Jid, DbLid, ContactName, FirstName, PushName FROM UserStatuses"
            )
            for jid, dblid, contact, first, push in cur.fetchall():
                name = (contact or first or push or "").strip()
                if not name:
                    continue
                for key in (jid, dblid):
                    if key:
                        names.setdefault(key, name)
                        names.setdefault(_bare(key), name)
            con.close()
        except Exception:
            pass
        return names

    def _name_for_jid(self, jid: Optional[str]) -> Optional[str]:
        """Miglior nome noto per un JID: prima l'IndexedDB, poi contacts.db."""
        if not jid:
            return None
        if self._index:
            n = self._index.name_for(jid)
            if n:
                return n
        return self._names.get(jid) or self._names.get(_bare(jid))

    def chat_name(self, chat_id: str) -> str:
        if _kind(chat_id) == "group":
            if self._index:
                title = self._index.group_title(chat_id)
                if title:
                    return title
            return f"Gruppo {_bare(chat_id).split('-')[0]}"
        # DM
        name = self._name_for_jid(chat_id)
        if name:
            return name
        if self._index:
            phone = self._index.phone_for(chat_id)
            if phone:
                return f"+{phone}"
        num = _bare(chat_id)
        if chat_id.endswith("@s.whatsapp.net") and num.isdigit():
            return f"+{num}"
        return f"Contatto {num}"

    # ─── Risoluzione mittente ──────────────────────────────────────────────
    def _display_name(self, jid: Optional[str]) -> str:
        name = self._name_for_jid(jid)
        if name:
            return name
        if self._index:
            phone = self._index.phone_for(jid)
            if phone:
                return f"+{phone}"
        num = _bare(jid or "")
        if num.isdigit():
            return f"+{num}"
        return num or "Sconosciuto"

    def _resolve_sender(self, chat: Chat, chat_senders: dict, mid
                        ) -> tuple[bool, Optional[str], str]:
        """(from_me, sender_jid, display_name) per un messaggio. Senza indice o
        senza match ritorna (False, None, "")."""
        rid = _to_int(mid)
        s = chat_senders.get(rid) if rid is not None else None
        if s is None:
            return (False, None, "")
        if s.from_me:
            return (True, None, ME_LABEL)
        jid = s.author_jid if chat.is_group else chat.chat_id
        return (False, jid, self._display_name(jid))

    # ─── Chat e messaggi ──────────────────────────────────────────────────
    def list_chats(self) -> list[Chat]:
        if not self._store:
            raise WhatsAppDesktopError("Reader non aperto.")
        con = _connect(self._store.messages_db)
        rows = con.execute(
            "SELECT chatId, COUNT(*), MAX(CAST(timestamp AS INTEGER)) "
            "FROM message GROUP BY chatId"
        ).fetchall()
        con.close()
        chats = [
            Chat(cid, self.chat_name(cid), _kind(cid), int(cnt), int(last or 0))
            for cid, cnt, last in rows if cid
        ]
        chats.sort(key=lambda c: c.last_ts, reverse=True)
        return chats

    def read_messages(self, chat_id: str, since: int | None = None,
                      until: int | None = None, query: str | None = None,
                      limit: int | None = None) -> list[Message]:
        if not self._store:
            raise WhatsAppDesktopError("Reader non aperto.")
        # I mittenti vengono dall'indice IndexedDB SE già caricato (via
        # `ensure_index`, deciso dal chiamante). Qui NON lo costruiamo: senza
        # indice i messaggi restano solo testo (comportamento v1).
        sql = ("SELECT CAST(timestamp AS INTEGER) ts, text, id FROM message "
               "WHERE chatId=?")
        params: list = [chat_id]
        if since is not None:
            sql += " AND CAST(timestamp AS INTEGER) >= ?"
            params.append(int(since))
        if until is not None:
            sql += " AND CAST(timestamp AS INTEGER) <= ?"
            params.append(int(until))
        if query:
            sql += " AND text LIKE ?"
            params.append(f"%{query}%")
        sql += " ORDER BY ts ASC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        t0 = time.perf_counter()
        con = _connect(self._store.messages_db)
        rows = con.execute(sql, params).fetchall()
        con.close()
        t_sql = time.perf_counter() - t0

        chat = Chat(chat_id, self.chat_name(chat_id), _kind(chat_id), 0, 0)
        # Mittenti della chat (scoped): ~5s la 1ª volta per questa chat, poi cache.
        t0 = time.perf_counter()
        chat_senders = self._index.senders_for_chat(chat_id) if self._index else {}
        t_send = time.perf_counter() - t0
        out: list[Message] = []
        for ts, text, mid in rows:
            from_me, sjid, sname = self._resolve_sender(chat, chat_senders, mid)
            out.append(Message(int(ts or 0), text or "", from_me, sname, sjid))
        _log.info("WA: read_messages %s -> %d msg (sql %.2fs, mittenti %.2fs)",
                  chat_id, len(out), t_sql, t_send)
        return out


# ─── Costruzione del Markdown (raggruppato per giorno) ────────────────────────
def _fmt_day(ts: int) -> str:
    return datetime.fromtimestamp(ts).strftime("%A %d %B %Y").capitalize()


def _fmt_time(ts: int) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M")


def _fmt_date(ts: int) -> str:
    return datetime.fromtimestamp(ts).strftime("%d/%m/%Y")


def build_markdown(chat: Chat, messages: list[Message]) -> str:
    with_sender = any(m.sender for m in messages)
    lines = [f"# WhatsApp — {chat.name}", ""]
    if messages:
        meta = (f"_Esportato da WhatsApp Desktop · {len(messages)} messaggi · "
                f"dal {_fmt_date(messages[0].ts)} al {_fmt_date(messages[-1].ts)}_")
        if not with_sender:
            meta = meta[:-1] + " · solo testo (mittenti non disponibili)_"
        lines.append(meta)
    else:
        lines.append("_Nessun messaggio nell'intervallo selezionato._")
    cur_day = None
    for m in messages:
        day = _fmt_day(m.ts)
        if day != cur_day:
            lines += ["", f"## {day}", ""]
            cur_day = day
        text = (m.text or "").replace("\r\n", "\n").strip()
        if with_sender and m.sender:
            lines.append(f"**{_fmt_time(m.ts)}** — **{m.sender}**: {text}")
        else:
            lines.append(f"**{_fmt_time(m.ts)}** — {text}")
    return "\n".join(lines) + "\n"
