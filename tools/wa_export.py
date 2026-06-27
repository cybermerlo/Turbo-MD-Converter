"""CLI di test per l'import chat da WhatsApp Desktop (v1: solo testo).

Elenca le chat e/o esporta una chat in Markdown leggendo il DB locale dell'app
ufficiale (nessuna connessione, nessun rischio ban).

Esempi:
    python tools/wa_export.py list
    python tools/wa_export.py export --chat 0
    python tools/wa_export.py export --chat "45625504731340@lid" --since 2026-05-01
    python tools/wa_export.py export --chat 1 --search piscina --out C:\\tmp\\chat.md
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from whatsapp.desktop_crypto import WhatsAppDesktopError  # noqa: E402
from whatsapp.desktop_reader import WhatsAppDesktopReader, build_markdown  # noqa: E402


def _parse_date(s: str) -> int:
    return int(dt.datetime.strptime(s, "%Y-%m-%d").timestamp())


def _safe_filename(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', "_", name).strip() or "chat"


def _default_out_dir() -> Path:
    base = Path.home() / "Downloads"
    if not base.exists():
        base = Path.home()
    out = base / "Turbo MD Converter"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _select_chat(chats, ref: str):
    if ref.isdigit() and int(ref) < len(chats):
        return chats[int(ref)]
    for c in chats:
        if c.chat_id == ref:
            return c
    return None


def cmd_list(reader: WhatsAppDesktopReader) -> int:
    chats = reader.list_chats()
    print(f"{'#':>3}  {'tipo':5}  {'msg':>7}  {'ultimo':10}  nome  [chatId]")
    for i, c in enumerate(chats):
        last = (dt.datetime.fromtimestamp(c.last_ts).strftime("%Y-%m-%d")
                if c.last_ts else "?")
        print(f"{i:>3}  {c.kind:5}  {c.message_count:>7}  {last:10}  "
              f"{c.name}  [{c.chat_id}]")
    print(f"\n{len(chats)} chat. Esporta con: python tools/wa_export.py export --chat <#>")
    return 0


def cmd_export(reader: WhatsAppDesktopReader, args) -> int:
    chats = reader.list_chats()
    chat = _select_chat(chats, args.chat)
    if not chat:
        print(f"Chat '{args.chat}' non trovata. Usa 'list' per vedere gli indici.")
        return 2
    since = _parse_date(args.since) if args.since else None
    until = _parse_date(args.until) + 86399 if args.until else None
    msgs = reader.read_messages(chat.chat_id, since, until, args.search)
    md = build_markdown(chat, msgs)
    out = (Path(args.out) if args.out
           else _default_out_dir() / f"WhatsApp - {_safe_filename(chat.name)}.md")
    out.write_text(md, encoding="utf-8")
    print(f"Scritti {len(msgs)} messaggi in: {out}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Export chat WhatsApp Desktop (v1 testo)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="elenca le chat")
    ex = sub.add_parser("export", help="esporta una chat in Markdown")
    ex.add_argument("--chat", required=True, help="indice (da 'list') o chatId")
    ex.add_argument("--since", help="data inizio YYYY-MM-DD (inclusa)")
    ex.add_argument("--until", help="data fine YYYY-MM-DD (inclusa)")
    ex.add_argument("--search", help="filtra i messaggi che contengono questo testo")
    ex.add_argument("--out", help="file .md di destinazione")
    ap.add_argument("--localstate", help="percorso LocalState (auto se omesso)")
    ap.add_argument("--oduid", help="ODUID hex (override, se necessario)")
    args = ap.parse_args()

    try:
        with WhatsAppDesktopReader(
            localstate=Path(args.localstate) if args.localstate else None,
            oduid_hex=args.oduid,
        ) as reader:
            if args.cmd == "list":
                return cmd_list(reader)
            return cmd_export(reader, args)
    except WhatsAppDesktopError as e:
        print(f"Errore: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
