"""Editable Markdown preview window with lightweight rich styling."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont

import customtkinter as ctk

from gui import theme


class MarkdownEditorWindow(ctk.CTkToplevel):
    """Large editable Markdown preview with lightweight rich styling and autosave."""

    def __init__(self, master, md_path: Path, on_saved: callable | None = None):
        super().__init__(master)
        self.title(f"Anteprima Markdown â€” {md_path.name}")
        self.geometry("960x740")
        self.minsize(720, 520)
        self.transient(master)
        try:
            self.configure(fg_color=theme.PAPER)
        except Exception:
            pass

        self.md_path = md_path
        self.on_saved = on_saved
        self._save_after_id: str | None = None
        self._highlight_after_id: str | None = None
        self._search_after_id: str | None = None
        self._search_matches: list[tuple[str, str]] = []
        self._search_index = -1
        self.search_var = ctk.StringVar(value="")

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(padx=18, pady=(14, 6), fill="x")

        ctk.CTkLabel(
            header, text=md_path.name,
            font=theme.font(15, "bold"), text_color=theme.INK,
        ).pack(side="left", fill="x", expand=True, anchor="w")

        self.status_label = ctk.CTkLabel(
            header, text="Salvato",
            font=theme.font(11), text_color=theme.INK_3,
        )
        self.status_label.pack(side="right")

        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.pack(padx=18, pady=(0, 8), fill="x")

        for label, weight, prefix, suffix in (
            ("B", "bold",   "**",  "**"),
            ("I", "italic", "*",   "*"),
            ("U", "under",  "<u>", "</u>"),
        ):
            btn = theme.ghost_button(
                toolbar, label,
                width=32, height=28,
                command=lambda p=prefix, s=suffix: self._wrap_selection(p, s),
            )
            btn.pack(side="left", padx=(0, 4))

        search_box = ctk.CTkFrame(
            toolbar, fg_color=theme.CARD, corner_radius=6,
            border_width=1, border_color=theme.RULE,
        )
        search_box.pack(side="right")

        self.search_entry = ctk.CTkEntry(
            search_box, textvariable=self.search_var,
            placeholder_text="Cerca", width=220, height=28,
            fg_color=theme.CARD_2, border_color=theme.RULE,
            text_color=theme.INK, font=theme.font(11),
        )
        self.search_entry.pack(side="left", padx=(6, 4), pady=5)

        self.search_count_label = ctk.CTkLabel(
            search_box, text="",
            width=54, font=theme.font(10, mono=True), text_color=theme.INK_3,
        )
        self.search_count_label.pack(side="left", padx=(0, 2))

        self.search_prev_btn = theme.ghost_button(
            search_box, "â†‘", width=30, height=28,
            command=lambda: self._move_search(-1),
        )
        self.search_prev_btn.pack(side="left", padx=(0, 4), pady=5)

        self.search_next_btn = theme.ghost_button(
            search_box, "â†“", width=30, height=28,
            command=lambda: self._move_search(1),
        )
        self.search_next_btn.pack(side="left", padx=(0, 4), pady=5)

        self.search_clear_btn = theme.ghost_button(
            search_box, "Ã—", width=30, height=28,
            command=self._clear_search,
        )
        self.search_clear_btn.pack(side="left", padx=(0, 6), pady=5)
        self.search_var.trace_add("write", lambda *_: self._schedule_search_refresh())

        body = ctk.CTkFrame(self, fg_color=theme.CARD, corner_radius=8,
                            border_width=1, border_color=theme.RULE)
        body.pack(padx=18, pady=(0, 14), fill="both", expand=True)

        self.text = tk.Text(
            body, wrap="word", undo=True,
            padx=18, pady=14,
            borderwidth=0, highlightthickness=0,
            bg=theme.CARD, fg=theme.INK,
            insertbackground=theme.INK,
            font=(theme.ui_family(), 12),
        )
        scrollbar = ctk.CTkScrollbar(body, command=self.text.yview)
        self.text.pack(side="left", fill="both", expand=True)
        scrollbar_visible = {"value": False}

        def show_editor_scrollbar():
            if not scrollbar_visible["value"]:
                scrollbar.pack(side="right", fill="y")
                scrollbar_visible["value"] = True

        def hide_editor_scrollbar():
            if scrollbar_visible["value"]:
                scrollbar.pack_forget()
                scrollbar_visible["value"] = False

        theme.autohide_text_scrollbar(
            self.text, scrollbar, show_editor_scrollbar, hide_editor_scrollbar,
        )

        self._configure_tags()
        self._load_file()
        self.text.bind("<<Modified>>", self._on_modified)
        self.text.bind("<Control-f>", self._focus_search)
        self.bind("<Control-f>", self._focus_search)
        self.search_entry.bind("<Return>", lambda _e: self._move_search(1))
        self.search_entry.bind("<Shift-Return>", lambda _e: self._move_search(-1))
        self.search_entry.bind("<Escape>", lambda _e: self._clear_search())
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _configure_tags(self) -> None:
        base = tkfont.Font(font=self.text["font"])
        h1 = base.copy(); h1.configure(size=20, weight="bold")
        h2 = base.copy(); h2.configure(size=16, weight="bold")
        bold = base.copy(); bold.configure(weight="bold")
        italic = base.copy(); italic.configure(slant="italic")
        underline = base.copy(); underline.configure(underline=True)
        mono = tkfont.Font(family=theme.mono_family(), size=10)

        self.text.tag_configure("h1", font=h1, spacing1=12, spacing3=6)
        self.text.tag_configure("h2", font=h2, spacing1=8, spacing3=4)
        self.text.tag_configure("bold", font=bold)
        self.text.tag_configure("italic", font=italic)
        self.text.tag_configure("underline", font=underline)
        self.text.tag_configure("code", font=mono, background=theme.PAPER_2)
        self.text.tag_configure("search_match", background=theme.AMBER_SOFT)
        self.text.tag_configure("search_current",
                                background=theme.AMBER, foreground="#ffffff")
        self.text.tag_raise("search_match")
        self.text.tag_raise("search_current")

    def _load_file(self) -> None:
        try:
            content = self.md_path.read_text(encoding="utf-8")
        except OSError:
            content = ""
        self.text.insert("1.0", content)
        self.text.edit_modified(False)
        self._apply_markdown_tags()

    def _on_modified(self, _e=None) -> None:
        if not self.text.edit_modified():
            return
        self.text.edit_modified(False)
        self.status_label.configure(text="Modificatoâ€¦")
        if self._save_after_id:
            self.after_cancel(self._save_after_id)
        if self._highlight_after_id:
            self.after_cancel(self._highlight_after_id)
        if self._search_after_id:
            self.after_cancel(self._search_after_id)
        self._save_after_id = self.after(500, self._save)
        self._highlight_after_id = self.after(350, self._apply_markdown_tags)
        self._search_after_id = self.after(380, self._refresh_search_highlights)

    def _save(self) -> None:
        self._save_after_id = None
        content = self.text.get("1.0", "end-1c")
        try:
            self.md_path.write_text(content, encoding="utf-8")
            self.status_label.configure(text="Salvato")
            if self.on_saved:
                self.on_saved(self.md_path, content)
        except OSError as exc:
            self.status_label.configure(text=f"Errore: {exc}")

    def _wrap_selection(self, prefix: str, suffix: str) -> None:
        try:
            start = self.text.index("sel.first")
            end = self.text.index("sel.last")
        except tk.TclError:
            insert = self.text.index("insert")
            self.text.insert(insert, prefix + suffix)
            self.text.mark_set("insert", f"{insert}+{len(prefix)}c")
        else:
            selected = self.text.get(start, end)
            self.text.delete(start, end)
            self.text.insert(start, f"{prefix}{selected}{suffix}")
            self.text.tag_remove("sel", "1.0", "end")
            self.text.tag_add("sel", f"{start}+{len(prefix)}c",
                              f"{start}+{len(prefix) + len(selected)}c")
        self.text.focus_set()
        self.text.edit_modified(True)
        self._on_modified()

    def _focus_search(self, _e=None):
        self.search_entry.focus_set()
        self.search_entry.select_range(0, "end")
        return "break"

    def _clear_search(self, _e=None):
        self.search_var.set("")
        self.text.tag_remove("search_match", "1.0", "end")
        self.text.tag_remove("search_current", "1.0", "end")
        self._search_matches = []
        self._search_index = -1
        self.search_count_label.configure(text="")
        self.text.focus_set()
        return "break"

    def _schedule_search_refresh(self):
        if self._search_after_id:
            self.after_cancel(self._search_after_id)
        self._search_after_id = self.after(120, self._refresh_search_highlights)

    def _refresh_search_highlights(self):
        self._search_after_id = None
        self.text.tag_remove("search_match", "1.0", "end")
        self.text.tag_remove("search_current", "1.0", "end")
        query = self.search_var.get()
        self._search_matches = []
        self._search_index = -1
        if not query:
            self.search_count_label.configure(text="")
            return

        start = "1.0"
        while True:
            match_start = self.text.search(query, start, "end", nocase=True)
            if not match_start:
                break
            match_end = f"{match_start}+{len(query)}c"
            self.text.tag_add("search_match", match_start, match_end)
            self._search_matches.append((match_start, match_end))
            start = match_end

        if not self._search_matches:
            self.search_count_label.configure(text="0")
            return

        insert = self.text.index("insert")
        selected = 0
        for idx, (match_start, _match_end) in enumerate(self._search_matches):
            if self.text.compare(match_start, ">=", insert):
                selected = idx
                break
        self._select_search_match(selected, scroll=False)

    def _move_search(self, step: int):
        if not self.search_var.get():
            self._focus_search()
            return "break"
        if not self._search_matches:
            self._refresh_search_highlights()
        if not self._search_matches:
            return "break"
        self._select_search_match((self._search_index + step) % len(self._search_matches))
        return "break"

    def _select_search_match(self, index: int, scroll: bool = True):
        if not self._search_matches:
            return
        self._search_index = max(0, min(index, len(self._search_matches) - 1))
        match_start, match_end = self._search_matches[self._search_index]
        self.text.tag_remove("search_current", "1.0", "end")
        self.text.tag_add("search_current", match_start, match_end)
        self.text.mark_set("insert", match_start)
        if scroll:
            self.text.see(match_start)
        self.search_count_label.configure(
            text=f"{self._search_index + 1}/{len(self._search_matches)}"
        )

    def _apply_markdown_tags(self) -> None:
        self._highlight_after_id = None
        cursor = self.text.index("insert")
        for tag in ("h1", "h2", "bold", "italic", "underline", "code"):
            self.text.tag_remove(tag, "1.0", "end")

        line_count = int(self.text.index("end-1c").split(".")[0])
        for line_no in range(1, line_count + 1):
            line_start = f"{line_no}.0"
            line_end   = f"{line_no}.end"
            line = self.text.get(line_start, line_end)
            if line.startswith("# "):
                self.text.tag_add("h1", line_start, line_end)
            elif line.startswith("## "):
                self.text.tag_add("h2", line_start, line_end)

            search_from = line_start
            while True:
                start = self.text.search("**", search_from, line_end)
                if not start: break
                end = self.text.search("**", f"{start}+2c", line_end)
                if not end: break
                self.text.tag_add("bold", f"{start}+2c", end)
                search_from = f"{end}+2c"

            search_from = line_start
            while True:
                start = self.text.search("<u>", search_from, line_end)
                if not start: break
                end = self.text.search("</u>", f"{start}+3c", line_end)
                if not end: break
                self.text.tag_add("underline", f"{start}+3c", end)
                search_from = f"{end}+4c"

            search_from = line_start
            while True:
                start = self.text.search("*", search_from, line_end)
                if not start: break
                if self.text.get(start, f"{start}+2c") == "**":
                    search_from = f"{start}+2c"
                    continue
                end = self.text.search("*", f"{start}+1c", line_end)
                if not end: break
                if self.text.get(end, f"{end}+2c") == "**":
                    search_from = f"{end}+2c"
                    continue
                self.text.tag_add("italic", f"{start}+1c", end)
                search_from = f"{end}+1c"

            search_from = line_start
            while True:
                start = self.text.search("`", search_from, line_end)
                if not start: break
                end = self.text.search("`", f"{start}+1c", line_end)
                if not end: break
                self.text.tag_add("code", start, f"{end}+1c")
                search_from = f"{end}+1c"

        self.text.mark_set("insert", cursor)

    def _close(self) -> None:
        if self._save_after_id:
            self.after_cancel(self._save_after_id)
            self._save()
        if self._highlight_after_id:
            self.after_cancel(self._highlight_after_id)
        if self._search_after_id:
            self.after_cancel(self._search_after_id)
        self.destroy()
