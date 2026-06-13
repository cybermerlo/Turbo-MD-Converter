"""Costruzione del pacchetto conversazione ".wachat".

Un ".wachat" è uno zip contenente:
    transcript.txt   – la chat con placeholder media "[[MEDIA: media/<file>]]"
    media/<file>     – solo i media della conversazione selezionata
    manifest.json    – metadati (nome chat, periodo, conteggi)

Viene letto dalla pipeline (pipeline/whatsapp_sources.py) come singolo input,
producendo un unico file Markdown.
"""

from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TranscriptEntry:
    ts_label: str
    sender: str
    text: str = ""
    media_name: str | None = None   # nome file dentro media/ (o None se solo testo)


@dataclass
class BuildStats:
    message_count: int = 0
    media_count: int = 0
    voice_note_count: int = 0
    missing_media: int = 0
    extra: dict = field(default_factory=dict)


def _render_transcript(
    chat_name: str,
    period_label: str,
    entries: list[TranscriptEntry],
    available: set[str],
) -> str:
    lines = [f"WhatsApp — {chat_name}", f"Periodo: {period_label}", ""]
    for e in entries:
        prefix = f"[{e.ts_label}] {e.sender}:"
        if e.media_name:
            if e.media_name in available:
                body = f"[[MEDIA: media/{e.media_name}]]"
            else:
                body = "[media non disponibile sul telefono]"
            if e.text:
                body = f"{body} {e.text}"
            lines.append(f"{prefix} {body}")
        else:
            lines.append(f"{prefix} {e.text}")
    return "\n".join(lines) + "\n"


def build_wachat(
    output_path: Path,
    chat_name: str,
    period_label: str,
    entries: list[TranscriptEntry],
    media_dir: Path,
    stats: BuildStats | None = None,
) -> Path:
    """Scrive il pacchetto .wachat e lo ritorna.

    `media_dir` contiene i file media già scaricati, nominati esattamente come
    i `media_name` delle entry. I media referenziati ma assenti vengono segnalati
    nella trascrizione come non disponibili.
    """
    output_path = Path(output_path)
    media_dir = Path(media_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    referenced = [e.media_name for e in entries if e.media_name]
    available = {
        name for name in referenced
        if (media_dir / name).exists()
    }

    transcript = _render_transcript(chat_name, period_label, entries, available)

    stats = stats or BuildStats()
    manifest = {
        "type": "whatsapp_chat",
        "version": 1,
        "chat_name": chat_name,
        "period": period_label,
        "message_count": stats.message_count or len(entries),
        "media_count": stats.media_count or len(available),
        "voice_note_count": stats.voice_note_count,
        "missing_media": stats.missing_media or (len(referenced) - len(available)),
        "generated_by": "Turbo MD Converter — WhatsApp import",
        **stats.extra,
    }

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("transcript.txt", transcript)
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        for name in sorted(available):
            zf.write(media_dir / name, f"media/{name}")

    return output_path
