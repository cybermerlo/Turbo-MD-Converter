"""Overall batch progress and cumulative cost display."""

import customtkinter as ctk

_GREEN = "#2ecc71"
_ORANGE = "#e67e22"


class ProgressFrame(ctk.CTkFrame):
    """Shows overall file-batch progress and running total cost."""

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)

        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.pack(padx=14, pady=(12, 12), fill="x")

        # ── Header row: section label + file count ────────────────────────────
        header_row = ctk.CTkFrame(inner, fg_color="transparent")
        header_row.pack(fill="x", pady=(0, 4))

        self._header_label = ctk.CTkLabel(
            header_row, text="AVANZAMENTO",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="gray60",
        )
        self._header_label.pack(side="left")

        self._count_label = ctk.CTkLabel(
            header_row, text="—",
            font=ctk.CTkFont(size=14, weight="bold"),
        )
        self._count_label.pack(side="right")

        # ── Progress bar ──────────────────────────────────────────────────────
        self._progress_bar = ctk.CTkProgressBar(inner, height=18)
        self._progress_bar.pack(fill="x", pady=(0, 4))
        self._progress_bar.set(0)

        # ── Status subtitle ───────────────────────────────────────────────────
        self._status_label = ctk.CTkLabel(
            inner, text="In attesa",
            font=ctk.CTkFont(size=11),
            text_color="gray55",
        )
        self._status_label.pack(anchor="w", pady=(0, 12))

        # ── Divider ───────────────────────────────────────────────────────────
        ctk.CTkFrame(inner, height=1, fg_color="gray30").pack(fill="x", pady=(0, 10))

        # ── Cost row ─────────────────────────────────────────────────────────
        cost_row = ctk.CTkFrame(inner, fg_color="transparent")
        cost_row.pack(fill="x")

        ctk.CTkLabel(
            cost_row, text="COSTO",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="gray60",
        ).pack(side="left")

        self._cost_label = ctk.CTkLabel(
            cost_row, text="$0.0000",
            font=ctk.CTkFont(size=18, weight="bold"),
        )
        self._cost_label.pack(side="right")

    # ─── Public API ───────────────────────────────────────────────────────────

    def set_batch(self, total_files: int) -> None:
        """Called once when a new batch starts."""
        doc = "documento" if total_files == 1 else "documenti"
        self._header_label.configure(text="AVANZAMENTO", text_color="gray60")
        self._count_label.configure(text=f"0 / {total_files}", text_color=("gray10", "gray90"))
        self._progress_bar.set(0)
        self._reset_bar_color()
        self._status_label.configure(
            text=f"Elaborazione di {total_files} {doc} in corso…",
            text_color="gray55",
        )
        self._cost_label.configure(text="$0.0000", text_color=("gray10", "gray90"))

    def update_files(self, done: int, total: int, cost_usd: float) -> None:
        """Called each time a file completes or cost updates incrementally."""
        progress = done / total if total > 0 else 0
        self._progress_bar.set(min(progress, 1.0))
        self._count_label.configure(text=f"{done} / {total}")
        remaining = total - done
        if remaining > 0:
            rem_word = "rimanente" if remaining == 1 else "rimanenti"
            self._status_label.configure(
                text=f"{done} completat{'o' if done == 1 else 'i'}  ·  {remaining} {rem_word}",
                text_color="gray55",
            )
        self._cost_label.configure(text=f"${cost_usd:.4f}")

    def update_cost(self, cost_usd: float) -> None:
        """Update cost display incrementally (during processing)."""
        self._cost_label.configure(text=f"${cost_usd:.4f}")

    def mark_complete(self, done: int, total: int, cost_usd: float, failed: int = 0) -> None:
        """Called when the entire batch finishes — make it graphically evident."""
        self._progress_bar.set(1.0)
        all_ok = failed == 0

        if all_ok:
            self._progress_bar.configure(progress_color=_GREEN)
            self._header_label.configure(text="COMPLETATO  ✓", text_color=_GREEN)
            self._count_label.configure(
                text=f"{done} / {total}",
                text_color=_GREEN,
            )
            doc = "documento elaborato" if done == 1 else "documenti elaborati"
            self._status_label.configure(
                text=f"Tutti i {done} {doc} con successo.",
                text_color=_GREEN,
            )
        else:
            self._progress_bar.configure(progress_color=_ORANGE)
            self._header_label.configure(text="COMPLETATO", text_color=_ORANGE)
            self._count_label.configure(
                text=f"{done} / {total}",
                text_color=_ORANGE,
            )
            self._status_label.configure(
                text=f"{done - failed} riusciti  ·  {failed} errori su {total} file",
                text_color=_ORANGE,
            )
        self._cost_label.configure(text=f"${cost_usd:.4f}")

    def reset(self) -> None:
        self._header_label.configure(text="AVANZAMENTO", text_color="gray60")
        self._count_label.configure(text="—", text_color=("gray10", "gray90"))
        self._progress_bar.set(0)
        self._reset_bar_color()
        self._status_label.configure(text="In attesa", text_color="gray55")
        self._cost_label.configure(text="$0.0000", text_color=("gray10", "gray90"))

    # ─── Internal ─────────────────────────────────────────────────────────────

    def _reset_bar_color(self) -> None:
        try:
            default = ctk.ThemeManager.theme["CTkProgressBar"]["progress_color"]
            self._progress_bar.configure(progress_color=default)
        except Exception:
            pass
