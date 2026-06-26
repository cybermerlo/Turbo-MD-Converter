"""Dialog di identificazione interlocutori (post-batch).

Mostra, per ogni speaker rilevato dalla diarization, alcuni spezzoni di testo con
timestamp e un pulsante ▶ per ascoltarne l'audio (estratto al volo con ffmpeg).
L'utente assegna un nome a ciascuno; alla conferma ritorna la mappa
``{speaker_id: nome}`` tramite la callback ``on_done`` (None se salta).
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

import customtkinter as ctk

from gui import theme
from ocr.audio_transcriber import _format_timestamp
from utils.ffmpeg_tools import _safe_unlink, extract_audio_segment


def _open_with_default_player(path: Path) -> None:
    """Apre un file audio col player predefinito del sistema."""
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


class SpeakerIdentificationWindow(ctk.CTkToplevel):
    def __init__(
        self,
        master,
        *,
        file_label: str,
        audio_path: Path,
        snippets_by_speaker: dict[str, list[dict]],
        on_done,
    ):
        super().__init__(master)
        self._audio_path = Path(audio_path)
        self._on_done = on_done
        self._done = False
        self._entries: dict[str, ctk.CTkEntry] = {}
        self._tmp_snippets: list[Path] = []

        self.title(f"Identifica interlocutori — {file_label}")
        self.configure(fg_color=theme.PAPER)
        self.geometry("560x560")
        self.minsize(460, 420)
        self.protocol("WM_DELETE_WINDOW", self._skip)
        try:
            self.transient(master)
        except Exception:
            pass

        ctk.CTkLabel(
            self, text=f"Più interlocutori rilevati in “{file_label}”",
            font=theme.font(15, "bold"), text_color=theme.INK, anchor="w",
        ).pack(fill="x", padx=16, pady=(14, 2))
        ctk.CTkLabel(
            self,
            text=("Assegna un nome a ciascuno (▶ per ascoltare). I nomi vuoti "
                  "restano come 'speaker_N'."),
            font=theme.font(11), text_color=theme.INK_3, anchor="w", justify="left",
            wraplength=520,
        ).pack(fill="x", padx=16, pady=(0, 10))

        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=8, pady=0)

        for speaker_id, snippets in snippets_by_speaker.items():
            self._build_speaker_card(body, speaker_id, snippets)

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(fill="x", padx=16, pady=12)
        theme.ghost_button(footer, "Salta", command=self._skip, width=110).pack(side="left")
        theme.amber_button(
            footer, "Conferma e rinomina", command=self._confirm, width=190,
        ).pack(side="right")

        try:
            self.after(120, self.grab_set)
        except Exception:
            pass

    def _build_speaker_card(self, parent, speaker_id: str, snippets: list[dict]) -> None:
        card = ctk.CTkFrame(parent, fg_color=theme.CARD, corner_radius=8,
                            border_width=1, border_color=theme.RULE)
        card.pack(fill="x", padx=8, pady=6)

        head = ctk.CTkFrame(card, fg_color="transparent")
        head.pack(fill="x", padx=10, pady=(10, 4))
        ctk.CTkLabel(head, text=speaker_id, font=theme.font(12, "bold", mono=True),
                     text_color=theme.INK_2).pack(side="left")
        entry = ctk.CTkEntry(head, width=240, placeholder_text="Nome interlocutore")
        entry.pack(side="right")
        self._entries[speaker_id] = entry

        for snip in snippets:
            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", padx=10, pady=(0, 6))
            ts = _format_timestamp(snip.get("start") or 0)
            play = theme.ghost_button(
                row, f"▶ {ts}", width=74,
                command=lambda s=snip: self._play(s),
            )
            play.pack(side="left", padx=(0, 8))
            ctk.CTkLabel(
                row, text=snip.get("text", ""), font=theme.font(11),
                text_color=theme.INK, anchor="w", justify="left", wraplength=380,
            ).pack(side="left", fill="x", expand=True)

    def _play(self, snip: dict) -> None:
        def work():
            seg = extract_audio_segment(
                self._audio_path, snip.get("start") or 0.0, snip.get("end") or 0.0,
            )
            if not seg:
                return
            self._tmp_snippets.append(seg)
            try:
                _open_with_default_player(seg)
            except Exception:
                pass

        threading.Thread(target=work, daemon=True).start()

    def _collect_labels(self) -> dict[str, str]:
        labels: dict[str, str] = {}
        for sid, entry in self._entries.items():
            name = entry.get().strip()
            if name:
                labels[sid] = name
        return labels

    def _confirm(self) -> None:
        self._finish(self._collect_labels())

    def _skip(self) -> None:
        self._finish(None)

    def _finish(self, labels) -> None:
        if self._done:
            return
        self._done = True
        for tmp in self._tmp_snippets:
            _safe_unlink(tmp)
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()
        if self._on_done:
            self._on_done(labels)
