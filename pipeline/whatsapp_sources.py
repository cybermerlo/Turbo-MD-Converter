"""Sorgente WhatsApp: legge un pacchetto ".wachat" e lo unisce in un testo unico.

Specchio di `pipeline/email_sources.py`: il corpo (transcript.txt) viene unito ai
contenuti dei media, ognuno convertito in testo tramite `process_attachment`
(immagini → OCR Gemini, note vocali → trascrizione ElevenLabs). Tutto inline, in
ordine cronologico → una sola stringa → un solo Markdown.
"""

from __future__ import annotations

import re
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path

# Placeholder media nel transcript: "[[MEDIA: media/IMG-001.jpg]]"
_MEDIA_RE = re.compile(r"\[\[MEDIA:\s*(media/[^\]\s]+)\]\]")


def _safe_extract_all(zf: zipfile.ZipFile, dest: Path) -> None:
    """Estrae lo zip in `dest` rifiutando le voci che evadono dalla cartella.

    Un `.wachat` è uno zip: un pacchetto malevolo con nomi tipo `../../x`
    (Zip Slip / path traversal) potrebbe altrimenti scrivere fuori da `dest`.
    """
    dest_resolved = dest.resolve()
    for member in zf.infolist():
        target = (dest / member.filename).resolve()
        if target != dest_resolved and dest_resolved not in target.parents:
            raise RuntimeError(f"voce non sicura nel pacchetto: {member.filename!r}")
    zf.extractall(dest)


def extract_whatsapp_parts(
    file_path: Path,
    process_attachment: Callable[[Path], str],
    emit_log: Callable[[str, str], None],
    cancel_event=None,
) -> str:
    """Scompatta il .wachat, inlinea i media e ritorna il testo combinato."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        try:
            with zipfile.ZipFile(file_path) as zf:
                _safe_extract_all(zf, tmp)
        except Exception as e:
            raise RuntimeError(
                f"Pacchetto WhatsApp non valido '{file_path.name}': {e}"
            ) from e

        transcript_path = tmp / "transcript.txt"
        if not transcript_path.exists():
            raise RuntimeError(
                f"Pacchetto WhatsApp '{file_path.name}' privo di transcript.txt"
            )
        transcript = transcript_path.read_text(encoding="utf-8", errors="replace")

        # Raccoglie i riferimenti media unici, preservando l'ordine.
        unique_refs: list[str] = []
        for m in _MEDIA_RE.finditer(transcript):
            rel = m.group(1)
            if rel not in unique_refs:
                unique_refs.append(rel)

        total = len(unique_refs)
        if total:
            emit_log(f"Conversazione WhatsApp: {total} media da elaborare", "INFO")

        resolved: dict[str, str] = {}
        for i, rel in enumerate(unique_refs, 1):
            if cancel_event is not None and cancel_event.is_set():
                break
            media_path = tmp / rel
            name = Path(rel).name
            if not media_path.exists():
                resolved[rel] = f"[media non disponibile: {name}]"
                continue
            emit_log(f"Elaborazione media WhatsApp {i}/{total}: {name}", "INFO")
            text = process_attachment(media_path)
            resolved[rel] = (text or "").strip() or f"[media senza testo estraibile: {name}]"

        def _replace(match: re.Match) -> str:
            rel = match.group(1)
            name = Path(rel).name
            body = resolved.get(rel, f"[media non disponibile: {name}]")
            return f"\n\n--- MEDIA: {name} ---\n{body}\n--- FINE MEDIA ---\n"

        return _MEDIA_RE.sub(_replace, transcript)
