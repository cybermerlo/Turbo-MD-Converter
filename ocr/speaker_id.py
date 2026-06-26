"""Identificazione degli interlocutori dopo una trascrizione diarizzata.

Quando ElevenLabs Scribe rileva più speaker, la trascrizione esce con etichette
provvisorie (``speaker_0``, ``speaker_1`` …). Questo modulo:
- sceglie alcuni spezzoni rappresentativi per ogni speaker (testo + intervallo
  temporale) da mostrare all'utente per il riconoscimento;
- riscrive il file ``.md`` sostituendo le etichette provvisorie con i nomi reali.

La logica è pura/testabile; la UI vive in ``gui/frames/speaker_id_window.py``.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def pick_speaker_snippets(
    segments: list[dict],
    max_snippets: int = 3,
    max_chars: int = 160,
) -> dict[str, list[dict]]:
    """Per ogni speaker, scegli fino a ``max_snippets`` battute rappresentative.

    Preferisce le battute più lunghe (più riconoscibili), poi le riordina in
    ordine cronologico. Ritorna ``{speaker_id: [{"start","end","text"}]}``.
    """
    by_speaker: dict[str, list[dict]] = {}
    for s in segments:
        by_speaker.setdefault(s["speaker_id"], []).append(s)

    result: dict[str, list[dict]] = {}
    for sid, segs in by_speaker.items():
        longest = sorted(segs, key=lambda x: len(x["text"]), reverse=True)[:max_snippets]
        chosen = sorted(longest, key=lambda x: (x.get("start") or 0.0))
        result[sid] = [
            {
                "start": c.get("start"),
                "end": c.get("end"),
                "text": (c["text"][:max_chars] + "…") if len(c["text"]) > max_chars
                else c["text"],
            }
            for c in chosen
        ]
    return result


def rewrite_transcript_in_md(
    md_path: Path,
    segments: list[dict],
    labels: dict[str, str],
) -> bool:
    """Sostituisce le etichette provvisorie con i nomi scelti dall'utente.

    Ritorna True se il file è stato modificato. Prima tenta di sostituire l'intero
    blocco trascritto (1:1 con ``build_transcript``); in fallback rietichetta
    riga-per-riga il token ``] speaker_X:``. Scrittura atomica.
    """
    from ocr.audio_transcriber import build_transcript, distinct_speakers

    path = Path(md_path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False

    clean_labels = {
        sid: name.strip()
        for sid, name in (labels or {}).items()
        if name and name.strip() and name.strip() != sid
    }
    if not clean_labels:
        return False

    old_block = build_transcript(segments)
    new_block = build_transcript(segments, clean_labels)
    if old_block and new_block != old_block and old_block in text:
        updated = text.replace(old_block, new_block, 1)
    else:
        updated = text
        for sid in distinct_speakers(segments):
            label = clean_labels.get(sid)
            if label:
                updated = updated.replace(f"] {sid}:", f"] {label}:")

    if updated == text:
        return False

    _atomic_write(path, updated)
    return True


def _atomic_write(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".md-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
