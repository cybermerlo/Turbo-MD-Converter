"""Lettura ad alto livello delle chat di WhatsApp Desktop (v1: solo testo).

Usa `desktop_crypto.decrypt_databases()` per ottenere i DB in chiaro, poi espone
le chat, i messaggi (con filtri data/testo) e i nomi risolti dai contatti.

Limiti noti v1: `genericStorage` è la cache di ricerca full-text → contiene
testo + chat + timestamp ma NON il mittente per-messaggio né i media (vivono
nell'IndexedDB del WebView2). Le chat 1:1 sono nominabili dai contatti; i gruppi
non hanno un titolo recuperabile da questi DB.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from whatsapp.desktop_crypto import (
    WhatsAppDesktopError,
    decrypt_databases,
)


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


class WhatsAppDesktopReader:
    """Apertura/lettura del DB di WhatsApp Desktop. Usare come context manager."""

    def __init__(self, localstate: Path | None = None, oduid_hex: str | None = None):
        self._localstate = localstate
        self._oduid_hex = oduid_hex
        self._store = None
        self._names: dict[str, str] = {}

    def __enter__(self) -> "WhatsAppDesktopReader":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def open(self) -> None:
        self._store = decrypt_databases(self._localstate, self._oduid_hex)
        self._names = self._load_names()

    def close(self) -> None:
        if self._store:
            self._store.cleanup()
            self._store = None

    # ─── Nomi contatti ────────────────────────────────────────────────────
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

    def chat_name(self, chat_id: str) -> str:
        if _kind(chat_id) == "group":
            return f"Gruppo {_bare(chat_id).split('-')[0]}"
        name = self._names.get(chat_id) or self._names.get(_bare(chat_id))
        if name:
            return name
        num = _bare(chat_id)
        if chat_id.endswith("@s.whatsapp.net") and num.isdigit():
            return f"+{num}"
        return f"Contatto {num}"

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
        sql = ("SELECT CAST(timestamp AS INTEGER) ts, text FROM message "
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
        con = _connect(self._store.messages_db)
        rows = con.execute(sql, params).fetchall()
        con.close()
        return [Message(int(ts or 0), text or "") for ts, text in rows]


# ─── Costruzione del Markdown (v1: solo testo, raggruppato per giorno) ────────
def _fmt_day(ts: int) -> str:
    return datetime.fromtimestamp(ts).strftime("%A %d %B %Y").capitalize()


def _fmt_time(ts: int) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M")


def _fmt_date(ts: int) -> str:
    return datetime.fromtimestamp(ts).strftime("%d/%m/%Y")


def build_markdown(chat: Chat, messages: list[Message]) -> str:
    lines = [f"# WhatsApp — {chat.name}", ""]
    if messages:
        lines.append(
            f"_Esportato da WhatsApp Desktop · {len(messages)} messaggi · "
            f"dal {_fmt_date(messages[0].ts)} al {_fmt_date(messages[-1].ts)}_"
        )
    else:
        lines.append("_Nessun messaggio nell'intervallo selezionato._")
    cur_day = None
    for m in messages:
        day = _fmt_day(m.ts)
        if day != cur_day:
            lines += ["", f"## {day}", ""]
            cur_day = day
        text = (m.text or "").replace("\r\n", "\n").strip()
        lines.append(f"**{_fmt_time(m.ts)}** — {text}")
    return "\n".join(lines) + "\n"
