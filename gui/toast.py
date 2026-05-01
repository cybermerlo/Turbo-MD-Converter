"""Persistent error toasts — anchored to bottom-right of main window."""

from __future__ import annotations
import customtkinter as ctk
from gui import theme


class _Toast(ctk.CTkFrame):
    def __init__(self, master, title, message, level="error", on_dismiss=None, **kwargs):
        bg = theme.CARD_2
        accent = theme.ERR if level == "error" else theme.WARN
        soft = theme.ERR_SOFT if level == "error" else theme.WARN_SOFT
        ic_fg = "#7a2e1d" if level == "error" else "#7a5418"

        super().__init__(master, fg_color=bg, corner_radius=8,
                         border_width=1, border_color=theme.RULE, **kwargs)
        self._on_dismiss = on_dismiss

        # Left accent stripe
        stripe = ctk.CTkFrame(self, fg_color=accent, width=3, corner_radius=0)
        stripe.pack(side="left", fill="y")

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(side="left", fill="both", expand=True, padx=(10, 6), pady=8)

        head = ctk.CTkFrame(body, fg_color="transparent")
        head.pack(fill="x")
        ic = ctk.CTkLabel(head, text="!" if level != "error" else "X",
                          width=16, height=16, corner_radius=8,
                          fg_color=soft, text_color=ic_fg,
                          font=theme.font(10, "bold", mono=True))
        ic.pack(side="left", padx=(0, 6))
        ctk.CTkLabel(head, text=title, font=theme.font(12, "bold"),
                     text_color=theme.INK, anchor="w").pack(side="left", fill="x", expand=True)
        x_btn = ctk.CTkButton(head, text="×", width=18, height=18,
                              fg_color="transparent", hover_color=theme.PAPER_2,
                              text_color=theme.INK_3, border_width=0,
                              font=theme.font(14), command=self._dismiss)
        x_btn.pack(side="right")

        ctk.CTkLabel(body, text=message, font=theme.font(11, mono=True),
                     text_color=theme.INK_2, anchor="w", justify="left",
                     wraplength=300).pack(fill="x", pady=(2, 0))

    def _dismiss(self):
        if self._on_dismiss:
            self._on_dismiss(self)
        self.destroy()


class ToastStack(ctk.CTkFrame):
    """Container anchored to bottom-right that stacks toasts."""

    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self._toasts = {}  # key → _Toast widget

    def show(self, key, title, message, level="error"):
        """Show or replace a toast under the given key (de-dupe by key)."""
        if key in self._toasts:
            try:
                self._toasts[key].destroy()
            except Exception:
                pass
        t = _Toast(self, title=title, message=message, level=level,
                   on_dismiss=lambda w, k=key: self._on_toast_closed(k))
        t.pack(fill="x", pady=(0, 8), padx=0)
        self._toasts[key] = t

    def _on_toast_closed(self, key):
        self._toasts.pop(key, None)

    def clear(self):
        for t in list(self._toasts.values()):
            try:
                t.destroy()
            except Exception:
                pass
        self._toasts.clear()
