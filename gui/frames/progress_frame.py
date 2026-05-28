"""Status strip across the top of the canvas + small cost chart canvas."""

from __future__ import annotations
import tkinter as tk
import customtkinter as ctk

from gui import theme


class ProgressFrame(ctk.CTkFrame):
    """Compact horizontal status strip: count · progress bar · state text."""

    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color=theme.PAPER, corner_radius=0, **kwargs)
        # bottom hairline
        theme.hairline(self).pack(side="bottom", fill="x")

        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.pack(fill="x", padx=18, pady=14)

        self._count = ctk.CTkLabel(
            inner, text="0 / 0",
            font=theme.font(14, "bold", mono=True), text_color=theme.INK_2,
        )
        self._count.pack(side="left", padx=(0, 14))

        self._bar = ctk.CTkProgressBar(
            inner, height=14, corner_radius=7,
            fg_color=theme.PAPER_2,
            progress_color=theme.AMBER,
            border_width=1,
            border_color=theme.RULE_STRONG,
        )
        self._bar.pack(side="left", fill="x", expand=True, padx=(0, 14))
        self._bar.set(0)

        self._state = ctk.CTkLabel(
            inner, text="In attesa",
            font=theme.font(12), text_color=theme.INK_3,
        )
        self._state.pack(side="left")

        # Hidden frame kept for action buttons that the OutputFrame mounts here.
        self.actions_frame = ctk.CTkFrame(self, fg_color="transparent")

    def set_batch(self, total_files: int):
        self._count.configure(text=f"0 / {total_files}", text_color=theme.INK_2)
        self._bar.set(0)
        self._bar.configure(progress_color=theme.AMBER)
        doc = "documento" if total_files == 1 else "documenti"
        self._state.configure(
            text=f"Elaborazione di {total_files} {doc} in corso…",
            text_color=theme.INK_3,
        )

    def update_files(self, done: int, total: int, _cost_usd: float = 0.0):
        progress = (done / total) if total > 0 else 0
        self._bar.set(min(progress, 1.0))
        self._count.configure(text=f"{done} / {total}", text_color=theme.INK)
        remaining = total - done
        if remaining > 0:
            rem_word = "rimanente" if remaining == 1 else "rimanenti"
            doc_word = "completato" if done == 1 else "completati"
            self._state.configure(
                text=f"{done} {doc_word}  ·  {remaining} {rem_word}",
                text_color=theme.INK_3,
            )

    def update_cost(self, _cost_usd: float):
        # Cost is shown in the right-rail cost chart and topbar; nothing here.
        pass

    def mark_complete(
        self,
        done: int,
        total: int,
        _cost_usd: float,
        failed: int = 0,
        final_check_failed: bool = False,
        final_check_issue_count: int = 0,
    ):
        self._bar.set(1.0)
        if failed == 0 and not final_check_failed:
            self._bar.configure(progress_color=theme.OK)
            self._count.configure(text=f"{done} / {total}", text_color=theme.OK)
            doc = "documento elaborato" if done == 1 else "documenti elaborati"
            self._state.configure(
                text=f"✓ Completato — tutti i {done} {doc} con successo",
                text_color=theme.OK,
            )
        elif failed == 0 and final_check_failed:
            self._bar.configure(progress_color=theme.WARN)
            self._count.configure(text=f"{done} / {total}", text_color=theme.WARN)
            avvisi = (
                f"{final_check_issue_count} avvis"
                f"{'o' if final_check_issue_count == 1 else 'i'}"
            )
            self._state.configure(
                text=(
                    f"⚠ Completato — check finale errori non superato "
                    f"({avvisi})"
                ),
                text_color=theme.WARN,
            )
        else:
            self._bar.configure(progress_color=theme.ERR)
            self._count.configure(text=f"{done} / {total}", text_color=theme.ERR)
            self._state.configure(
                text=f"⚠ Completato — {done - failed} riusciti, {failed} errori su {total}",
                text_color=theme.ERR,
            )

    def reset(self):
        self._count.configure(text="0 / 0", text_color=theme.INK_2)
        self._bar.set(0)
        self._bar.configure(progress_color=theme.AMBER)
        self._state.configure(text="In attesa", text_color=theme.INK_3)


class CostChart(ctk.CTkFrame):
    """Small per-file bar chart drawn on a tk.Canvas + total + tooltip."""

    HEIGHT = 56

    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color=theme.CARD, corner_radius=6,
                         border_width=1, border_color=theme.RULE, **kwargs)
        self._rows: list[tuple[str, str, float]] = []   # (label, status, cost)
        self._tooltip = None
        self._tooltip_after_id = None

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=12, pady=(10, 6))

        left = ctk.CTkFrame(head, fg_color="transparent")
        left.pack(side="left")
        self._total_lbl = ctk.CTkLabel(
            left, text="$0.0000",
            font=theme.font(16, "bold", mono=True), text_color=theme.INK,
        )
        self._total_lbl.pack(anchor="w")
        ctk.CTkLabel(
            left, text="COSTO CUMULATIVO",
            font=theme.font(9, "bold"), text_color=theme.INK_3,
        ).pack(anchor="w")

        self._count_lbl = ctk.CTkLabel(
            head, text="0/0",
            font=theme.font(11, mono=True), text_color=theme.INK_3,
            anchor="e",
        )
        self._count_lbl.pack(side="right")

        self._canvas = tk.Canvas(
            self, height=self.HEIGHT,
            bg=theme.CARD, highlightthickness=0, bd=0,
        )
        self._canvas.pack(fill="x", padx=12, pady=(0, 4))

        axis = ctk.CTkFrame(self, fg_color="transparent")
        axis.pack(fill="x", padx=12, pady=(0, 10))
        self._axis_left = ctk.CTkLabel(axis, text="—",
            font=theme.font(9, mono=True), text_color=theme.INK_4)
        self._axis_left.pack(side="left")
        self._axis_right = ctk.CTkLabel(axis, text="—",
            font=theme.font(9, mono=True), text_color=theme.INK_4)
        self._axis_right.pack(side="right")

        self._canvas.bind("<Configure>", lambda _e: self._redraw())
        self._canvas.bind("<Motion>", self._on_motion)
        self._canvas.bind("<Leave>", self._hide_tooltip)

    def update_data(self, rows):
        """rows = list[(label, status, cost)]."""
        self._rows = list(rows)
        total = sum(c for _, _, c in self._rows)
        priced = sum(1 for _, _, c in self._rows if c > 0)
        self._total_lbl.configure(text=f"${total:.4f}")
        self._count_lbl.configure(text=f"{priced}/{len(self._rows)}  con costo")
        if self._rows:
            self._axis_left.configure(text="doc 1")
            self._axis_right.configure(text=f"doc {len(self._rows)}")
        else:
            self._axis_left.configure(text="—")
            self._axis_right.configure(text="—")
        self._redraw()

    def _redraw(self):
        c = self._canvas
        c.delete("all")
        if not self._rows:
            c.create_text(
                int(c.winfo_width() / 2), int(self.HEIGHT / 2),
                text="In attesa del primo documento",
                fill=theme.INK_4, font=(theme.ui_family(), 9),
            )
            return

        n = len(self._rows)
        w = max(c.winfo_width(), 1)
        gap = 3
        bw = max(2, (w - gap * (n - 1)) / n)
        max_cost = max((c2 for _, _, c2 in self._rows), default=0.001)
        if max_cost <= 0:
            max_cost = 0.001
        H = self.HEIGHT

        self._bar_rects = []  # (x0, x1, label, status, cost)
        for i, (label, status, cost) in enumerate(self._rows):
            x0 = int(i * (bw + gap))
            x1 = int(x0 + bw)
            if cost > 0:
                h = max(6, (cost / max_cost) * (H - 4))
            else:
                h = 3
            y0 = H - h
            y1 = H

            color = {
                "ok":   theme.AMBER,
                "run":  theme.INK,
                "err":  theme.ERR,
                "warn": theme.WARN,
            }.get(status, theme.RULE_STRONG)

            c.create_rectangle(x0, y0, x1, y1, fill=color, width=0)
            self._bar_rects.append((x0, x1, label, status, cost))

    def _on_motion(self, event):
        if not getattr(self, "_bar_rects", None):
            return
        for x0, x1, label, status, cost in self._bar_rects:
            if x0 <= event.x <= x1:
                self._show_tooltip(event.x_root, event.y_root, label, cost)
                return
        self._hide_tooltip()

    def _show_tooltip(self, x_root, y_root, label, cost):
        if self._tooltip is None:
            self._tooltip = tk.Toplevel(self)
            self._tooltip.overrideredirect(True)
            self._tooltip.attributes("-topmost", True)
            try:
                self._tooltip.config(bg=theme.INK)
            except Exception:
                pass
            self._tip_lbl = tk.Label(
                self._tooltip,
                bg=theme.INK, fg=theme.PAPER,
                font=(theme.mono_family(), 9),
                padx=6, pady=3, bd=0,
            )
            self._tip_lbl.pack()
        text = f"{label[:32]}  ·  ${cost:.4f}" if cost > 0 else f"{label[:32]}  ·  —"
        self._tip_lbl.configure(text=text)
        self._tooltip.geometry(f"+{x_root + 10}+{y_root + 14}")
        self._tooltip.deiconify()

    def _hide_tooltip(self, _e=None):
        if self._tooltip is not None:
            try:
                self._tooltip.withdraw()
            except Exception:
                pass
