"""Lettura del database WhatsApp decifrato (msgstore.db).

Gestisce due varianti di schema:
- "modern" (WhatsApp ~2021+): tabelle `message`, `chat`, `jid`, `message_media`.
- "legacy" (più vecchio): tabella unica `messages`.

Senza root non è disponibile `wa.db` (rubrica), quindi i nomi dei contatti
1:1 vengono mostrati come numero di telefono; per i gruppi si usa il soggetto.
"""

from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ChatSummary:
    selector: object        # chat._id (modern) o jid string (legacy)
    jid: str
    name: str
    is_group: bool
    last_ts: int            # ms epoch
    count: int
    last_text: str = ""


@dataclass
class WaMessage:
    ts: int                 # ms epoch
    from_me: bool
    sender_label: str
    text: str
    media_relpath: str | None = None
    media_mime: str | None = None


class MsgStoreReaderError(Exception):
    """Schema non riconosciuto o database illeggibile."""


def _format_jid(jid: str | None) -> str:
    if not jid:
        return "Sconosciuto"
    user = jid.split("@", 1)[0]
    return f"+{user}" if user.isdigit() else (user or jid)


def _is_group_jid(jid: str | None) -> bool:
    return bool(jid) and jid.endswith("@g.us")


def normalize_number(value: str | None) -> str:
    """Riduce un numero o jid a sole cifre; usa le ultime 10 per il confronto.

    Gestisce la presenza/assenza del prefisso internazionale (es. il jid
    '393331234567' e la voce in rubrica '+39 333 1234567' o '333 1234567'
    collassano tutti su '3331234567').
    """
    digits = re.sub(r"\D", "", value or "")
    return digits[-10:] if len(digits) >= 10 else digits


class MsgStoreReader:
    def __init__(self, db_path: Path, contacts: dict[str, str] | None = None):
        self.db_path = Path(db_path)
        # Mappa numero-normalizzato → nome (dalla rubrica del telefono). Vuota
        # se non disponibile: in tal caso si mostra il numero.
        self.contacts = contacts or {}
        self.schema = self._detect_schema()

    # ── Connessione / schema ──────────────────────────────────────────────
    def _connect(self) -> sqlite3.Connection:
        # Connessione di sola lettura, robusta con i path Windows.
        uri = self.db_path.resolve().as_uri() + "?mode=ro"
        con = sqlite3.connect(uri, uri=True)
        con.row_factory = sqlite3.Row
        return con

    def _tables(self, con: sqlite3.Connection) -> set[str]:
        rows = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        return {r[0] for r in rows}

    def _columns(self, con: sqlite3.Connection, table: str) -> set[str]:
        try:
            rows = con.execute(f"PRAGMA table_info({table})").fetchall()
        except sqlite3.Error:
            return set()
        return {r[1] for r in rows}

    def _detect_schema(self) -> str:
        with closing(self._connect()) as con:
            tables = self._tables(con)
        if "message" in tables and "chat" in tables and "jid" in tables:
            return "modern"
        if "messages" in tables:
            return "legacy"
        raise MsgStoreReaderError(
            "Schema del database WhatsApp non riconosciuto."
        )

    # ── API pubblica ──────────────────────────────────────────────────────
    def list_chats(self) -> list[ChatSummary]:
        if self.schema == "modern":
            return self._list_chats_modern()
        return self._list_chats_legacy()

    def read_messages(
        self,
        chat: ChatSummary,
        from_ms: int | None = None,
        to_ms: int | None = None,
    ) -> list[WaMessage]:
        if self.schema == "modern":
            return self._read_messages_modern(chat, from_ms, to_ms)
        return self._read_messages_legacy(chat, from_ms, to_ms)

    def count_range(
        self,
        chat: ChatSummary,
        from_ms: int | None = None,
        to_ms: int | None = None,
    ) -> tuple[int, int]:
        """(numero messaggi, numero media) nel periodo — COUNT veloce e indicizzato."""
        if self.schema == "modern":
            return self._count_modern(chat, from_ms, to_ms)
        return self._count_legacy(chat, from_ms, to_ms)

    @staticmethod
    def _range_clause(ts_col: str, from_ms, to_ms) -> tuple[list[str], list]:
        clause = [f"{ts_col} > 0"]
        params: list[object] = []
        if from_ms is not None:
            clause.append(f"{ts_col} >= ?")
            params.append(from_ms)
        if to_ms is not None:
            clause.append(f"{ts_col} <= ?")
            params.append(to_ms)
        return clause, params

    def _count_modern(self, chat, from_ms, to_ms) -> tuple[int, int]:
        with closing(self._connect()) as con:
            tables = self._tables(con)
            cl, prm = self._range_clause("timestamp", from_ms, to_ms)
            where = " AND ".join(["chat_row_id = ?", *cl])
            msg = con.execute(
                f"SELECT COUNT(*) FROM message WHERE {where}",
                [chat.selector, *prm]).fetchone()[0]
            media = 0
            if "message_media" in tables:
                cl2, prm2 = self._range_clause("m.timestamp", from_ms, to_ms)
                where2 = " AND ".join(["m.chat_row_id = ?", *cl2])
                media = con.execute(
                    "SELECT COUNT(*) FROM message m "
                    "JOIN message_media mm ON mm.message_row_id = m._id "
                    f"WHERE {where2}", [chat.selector, *prm2]).fetchone()[0]
        return int(msg or 0), int(media or 0)

    def _count_legacy(self, chat, from_ms, to_ms) -> tuple[int, int]:
        with closing(self._connect()) as con:
            cols = self._columns(con, "messages")
            cl, prm = self._range_clause("timestamp", from_ms, to_ms)
            where = " AND ".join(["key_remote_jid = ?", *cl])
            msg = con.execute(
                f"SELECT COUNT(*) FROM messages WHERE {where}",
                [chat.selector, *prm]).fetchone()[0]
            media = 0
            if "media_wa_type" in cols:
                media = con.execute(
                    f"SELECT COUNT(*) FROM messages WHERE {where} "
                    "AND media_wa_type > 0",
                    [chat.selector, *prm]).fetchone()[0]
        return int(msg or 0), int(media or 0)

    # ── Modern ────────────────────────────────────────────────────────────
    def _list_chats_modern(self) -> list[ChatSummary]:
        out: list[ChatSummary] = []
        with closing(self._connect()) as con:
            chat_cols = self._columns(con, "chat")
            has_subject = "subject" in chat_cols
            has_display = "display_message_row_id" in chat_cols
            subject_expr = "c.subject" if has_subject else "NULL"

            # Conteggi + ultimo timestamp in UNA sola scansione aggregata
            # (evita sottoquery correlate per ogni chat → veloce anche su DB grandi).
            agg: dict[int, tuple[int, int]] = {}
            for row in con.execute(
                "SELECT chat_row_id AS cid, COUNT(*) AS cnt, MAX(timestamp) AS last_ts "
                "FROM message WHERE timestamp > 0 GROUP BY chat_row_id"
            ):
                agg[row["cid"]] = (row["cnt"], row["last_ts"])

            # Anteprima dell'ultimo messaggio: join diretto sul puntatore della
            # tabella chat, se la colonna esiste (nessuna scansione per chat).
            if has_display:
                last_join = "LEFT JOIN message dm ON dm._id = c.display_message_row_id"
                last_col = "dm.text_data AS last_text"
            else:
                last_join = ""
                last_col = "NULL AS last_text"

            rows = con.execute(
                f"""
                SELECT c._id AS chat_id, j.raw_string AS jid,
                       {subject_expr} AS subject, {last_col}
                FROM chat c
                JOIN jid j ON j._id = c.jid_row_id
                {last_join}
                """
            ).fetchall()

        for r in rows:
            cnt, last_ts = agg.get(r["chat_id"], (0, 0))
            if not cnt:
                continue
            jid = r["jid"] or ""
            is_group = _is_group_jid(jid)
            subject = r["subject"]
            if is_group:
                name = subject or _format_jid(jid)
            else:
                name = self._contact_name(jid) or _format_jid(jid)
            out.append(ChatSummary(
                selector=r["chat_id"],
                jid=jid,
                name=name or _format_jid(jid),
                is_group=is_group,
                last_ts=last_ts or 0,
                count=cnt or 0,
                last_text=(r["last_text"] or "").replace("\n", " ")[:120],
            ))
        out.sort(key=lambda c: c.last_ts, reverse=True)
        return out

    def _read_messages_modern(
        self, chat: ChatSummary, from_ms: int | None, to_ms: int | None
    ) -> list[WaMessage]:
        out: list[WaMessage] = []
        with closing(self._connect()) as con:
            msg_cols = self._columns(con, "message")
            tables = self._tables(con)
            has_sender = "sender_jid_row_id" in msg_cols
            has_media = "message_media" in tables

            sender_join = (
                "LEFT JOIN jid sj ON sj._id = m.sender_jid_row_id"
                if has_sender else ""
            )
            sender_col = "sj.raw_string AS sender_jid," if has_sender else \
                "NULL AS sender_jid,"
            media_join = (
                "LEFT JOIN message_media mm ON mm.message_row_id = m._id"
                if has_media else ""
            )
            media_cols = (
                "mm.file_path AS file_path, mm.mime_type AS mime_type"
                if has_media else "NULL AS file_path, NULL AS mime_type"
            )

            where = ["m.chat_row_id = ?", "m.timestamp > 0"]
            params: list[object] = [chat.selector]
            if from_ms is not None:
                where.append("m.timestamp >= ?")
                params.append(from_ms)
            if to_ms is not None:
                where.append("m.timestamp <= ?")
                params.append(to_ms)

            sql = f"""
                SELECT m.timestamp AS ts, m.from_me AS from_me,
                       m.text_data AS text_data,
                       {sender_col}
                       {media_cols}
                FROM message m
                {sender_join}
                {media_join}
                WHERE {' AND '.join(where)}
                ORDER BY m.timestamp ASC, m._id ASC
            """
            rows = con.execute(sql, params).fetchall()

        for r in rows:
            from_me = bool(r["from_me"])
            text = (r["text_data"] or "").strip()
            file_path = r["file_path"]
            if not text and not file_path:
                continue  # salta messaggi di sistema/protocollo vuoti
            out.append(WaMessage(
                ts=r["ts"] or 0,
                from_me=from_me,
                sender_label=self._sender_label(chat, from_me, r["sender_jid"]),
                text=text,
                media_relpath=file_path or None,
                media_mime=r["mime_type"] or None,
            ))
        return out

    # ── Legacy ────────────────────────────────────────────────────────────
    def _list_chats_legacy(self) -> list[ChatSummary]:
        out: list[ChatSummary] = []
        with closing(self._connect()) as con:
            rows = con.execute(
                """
                SELECT key_remote_jid AS jid,
                       MAX(timestamp) AS last_ts,
                       COUNT(*) AS cnt,
                       (SELECT data FROM messages m2
                          WHERE m2.key_remote_jid = messages.key_remote_jid
                            AND m2.data IS NOT NULL AND m2.data <> ''
                          ORDER BY m2.timestamp DESC LIMIT 1) AS last_text
                FROM messages
                WHERE key_remote_jid IS NOT NULL
                  AND key_remote_jid NOT IN ('-1', 'status@broadcast')
                GROUP BY key_remote_jid
                """
            ).fetchall()
        for r in rows:
            if not r["cnt"]:
                continue
            jid = r["jid"] or ""
            is_group = _is_group_jid(jid)
            if is_group:
                name = f"Gruppo {jid.split('@')[0][:10]}"
            else:
                name = self._contact_name(jid) or _format_jid(jid)
            out.append(ChatSummary(
                selector=jid,
                jid=jid,
                name=name,
                is_group=is_group,
                last_ts=r["last_ts"] or 0,
                count=r["cnt"] or 0,
                last_text=(r["last_text"] or "").replace("\n", " ")[:120],
            ))
        out.sort(key=lambda c: c.last_ts, reverse=True)
        return out

    def _read_messages_legacy(
        self, chat: ChatSummary, from_ms: int | None, to_ms: int | None
    ) -> list[WaMessage]:
        out: list[WaMessage] = []
        with closing(self._connect()) as con:
            cols = self._columns(con, "messages")
            has_resource = "remote_resource" in cols
            has_media_type = "media_wa_type" in cols
            res_col = "remote_resource," if has_resource else "NULL AS remote_resource,"
            mtype_col = "media_wa_type," if has_media_type else "0 AS media_wa_type,"

            where = ["key_remote_jid = ?", "timestamp > 0"]
            params: list[object] = [chat.selector]
            if from_ms is not None:
                where.append("timestamp >= ?")
                params.append(from_ms)
            if to_ms is not None:
                where.append("timestamp <= ?")
                params.append(to_ms)

            sql = f"""
                SELECT timestamp AS ts, key_from_me AS from_me, data AS text_data,
                       {res_col} {mtype_col}
                       media_mime_type AS mime_type
                FROM messages
                WHERE {' AND '.join(where)}
                ORDER BY timestamp ASC, _id ASC
            """
            rows = con.execute(sql, params).fetchall()

        for r in rows:
            from_me = bool(r["from_me"])
            text = (r["text_data"] or "").strip()
            media_type = r["media_wa_type"] or 0
            if not text and not media_type:
                continue
            note = ""
            if media_type and not text:
                note = "[media non esportabile da questo backup]"
            out.append(WaMessage(
                ts=r["ts"] or 0,
                from_me=from_me,
                sender_label=self._sender_label(chat, from_me, r["remote_resource"]),
                text=text or note,
                media_relpath=None,  # path locale non disponibile nello schema legacy
                media_mime=r["mime_type"] or None,
            ))
        return out

    # ── Helpers ───────────────────────────────────────────────────────────
    def _contact_name(self, jid: str | None) -> str | None:
        if not jid or not self.contacts:
            return None
        return self.contacts.get(normalize_number(jid))

    def _sender_label(
        self, chat: ChatSummary, from_me: bool, sender_jid: str | None
    ) -> str:
        if from_me:
            return "Io"
        if chat.is_group:
            if sender_jid:
                return self._contact_name(sender_jid) or _format_jid(sender_jid)
            return "Partecipante"
        return chat.name
