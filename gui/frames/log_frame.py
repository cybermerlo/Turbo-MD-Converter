"""Collapsible log drawer at the bottom of the canvas."""

from __future__ import annotations
from datetime import datetime
import tkinter as tk
import customtkinter as ctk

from gui import theme


class LogFrame(ctk.CTkFrame):
    """A drawer that toggles between collapsed (just the head) and open."""

    HEAD_HEIGHT = 36
    OPEN_HEIGHT = 200
    MAX_LINES = 2000

    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color=theme.PAPER, corner_radius=0, **kwargs)
        self._open = True
        self._error_count = 0
        self._warn_count = 0
        self._total_count = 0

        # Top hairline
        theme.hairline(self).pack(fill="x", side="top")

        # ── Head row ──────────────────────────────────────────────────────
        self.head = ctk.CTkFrame(self, fg_color=theme.PAPER, corner_radius=0,
                                 height=self.HEAD_HEIGHT, cursor="hand2")
        self.head.pack(fill="x", side="top")
        self.head.pack_propagate(False)

        head_inner = ctk.CTkFrame(self.head, fg_color="transparent")
        head_inner.pack(fill="both", expand=True, padx=18, pady=0)

        self.chev_lbl = ctk.CTkLabel(
            head_inner, text="▾", font=theme.font(11, mono=True),
            text_color=theme.INK_3, width=14,
        )
        self.chev_lbl.pack(side="left")

        ctk.CTkLabel(
            head_inner, text="LOG",
            font=theme.font(10, "bold"), text_color=theme.INK_3,
        ).pack(side="left", padx=(4, 8))

        self.badge = ctk.CTkLabel(
            head_inner, text="0 eventi",
            font=theme.font(10, mono=True),
            fg_color=theme.PAPER_2, text_color=theme.INK_3,
            corner_radius=10, height=18, width=80,
        )
        self.badge.pack(side="left")

        self.clear_btn = theme.ghost_button(
            head_inner, "Pulisci", command=self.clear, width=70, height=22,
        )
        self.clear_btn.pack(side="right")

        # Click-to-toggle on the head only (button stays clickable)
        for w in (self.head, head_inner, self.chev_lbl):
            w.bind("<Button-1>", lambda _e: self.toggle())

        # ── Body (textbox) ────────────────────────────────────────────────
        self.body_holder = ctk.CTkFrame(
            self, fg_color=theme.PAPER, corner_radius=0,
            height=self.OPEN_HEIGHT,
        )
        self.body_holder.pack(fill="x", side="bottom")
        self.body_holder.pack_propagate(False)

        self.textbox = tk.Text(
            self.body_holder,
            bg=theme.PAPER, fg=theme.INK_2,
            font=(theme.mono_family(), 10),
            relief="flat", padx=18, pady=8,
            highlightthickness=0, bd=0, wrap="word",
            state="disabled",
        )
        self.textbox.pack(fill="both", expand=True, side="left")

        sb = ctk.CTkScrollbar(self.body_holder, command=self.textbox.yview)
        scrollbar_visible = {"value": False}

        def show_scrollbar():
            if not scrollbar_visible["value"]:
                sb.pack(side="right", fill="y")
                scrollbar_visible["value"] = True

        def hide_scrollbar():
            if scrollbar_visible["value"]:
                sb.pack_forget()
                scrollbar_visible["value"] = False

        theme.autohide_text_scrollbar(
            self.textbox, sb, show_scrollbar, hide_scrollbar,
        )

        self.textbox.tag_config("ts",      foreground=theme.INK_4)
        self.textbox.tag_config("info",    foreground=theme.INK_2)
        self.textbox.tag_config("warning", foreground="#7a5418")
        self.textbox.tag_config("error",   foreground="#7a2e1d")
        self.textbox.tag_config("level",   font=(theme.mono_family(), 10, "bold"))

    # ─── Public API ───────────────────────────────────────────────────────
    def toggle(self):
        self.set_open(not self._open)

    def set_open(self, opened: bool):
        if opened == self._open:
            return
        self._open = opened
        if opened:
            self.body_holder.pack(fill="x", side="bottom")
            self.chev_lbl.configure(text="▾")
        else:
            self.body_holder.pack_forget()
            self.chev_lbl.configure(text="▸")

    def append(self, message: str, level: str = "INFO"):
        ts = datetime.now().strftime("%H:%M:%S")
        self._total_count += 1
        if level == "ERROR":
            self._error_count += 1
        elif level == "WARNING":
            self._warn_count += 1

        self.textbox.configure(state="normal")
        self.textbox.insert("end", f"[{ts}] ", "ts")
        if level == "ERROR":
            self.textbox.insert("end", "ERRORE  ", ("level", "error"))
        elif level == "WARNING":
            self.textbox.insert("end", "AVVISO  ", ("level", "warning"))
        else:
            self.textbox.insert("end", "INFO    ", ("level", "info"))
        tag = "error" if level == "ERROR" else "warning" if level == "WARNING" else "info"
        self.textbox.insert("end", message + "\n", tag)
        line_count = int(self.textbox.index("end-1c").split(".")[0])
        if line_count > self.MAX_LINES:
            self.textbox.delete("1.0", f"{line_count - self.MAX_LINES}.0")
        self.textbox.see("end")
        self.textbox.configure(state="disabled")
        self._refresh_badge()

    def clear(self):
        self.textbox.configure(state="normal")
        self.textbox.delete("1.0", "end")
        self.textbox.configure(state="disabled")
        self._error_count = 0
        self._warn_count = 0
        self._total_count = 0
        self._refresh_badge()

    def _refresh_badge(self):
        bits = [f"{self._total_count} eventi"]
        if self._error_count:
            bits.append(f"{self._error_count} err")
        if self._warn_count:
            bits.append(f"{self._warn_count} warn")
        self.badge.configure(text=" · ".join(bits))
        if self._error_count > 0:
            self.badge.configure(fg_color=theme.ERR_SOFT, text_color="#7a2e1d")
        elif self._warn_count > 0:
            self.badge.configure(fg_color=theme.WARN_SOFT, text_color="#7a5418")
        else:
            self.badge.configure(fg_color=theme.PAPER_2, text_color=theme.INK_3)
