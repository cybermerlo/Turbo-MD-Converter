"""Output preview frame — paper-themed, single Markdown view + actions."""

from __future__ import annotations
import tkinter as tk
from pathlib import Path
from tkinter import filedialog
from tkinter import font as tkfont

import customtkinter as ctk

from gui import theme
from gui.frames.markdown_editor_window import MarkdownEditorWindow
from utils.system import open_with_system

_MERGE_EXTENSIONS = (".md", ".markdown")


class OutputFrame(ctk.CTkFrame):
    """Markdown preview canvas + small action toolbar above it."""

    def __init__(self, master, actions_parent=None, **kwargs):
        super().__init__(master, fg_color=theme.PAPER, corner_radius=0,
                         border_width=0, **kwargs)
        self._output_dir: Path | None = None
        self._all_md_paths: list[Path] = []
        self._current_md_path: Path | None = None
        self._combined_md_path: Path | None = None
        self._editor_window: MarkdownEditorWindow | None = None
        self._combined_editor_window: MarkdownEditorWindow | None = None
        self._merge_items: list[dict[str, object]] = []
        self._merge_path_keys: set[Path] = set()
        self._merge_window: ctk.CTkToplevel | None = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # ── Toolbar ───────────────────────────────────────────────────────
        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", padx=18, pady=(12, 8))

        self.title_lbl = ctk.CTkLabel(
            toolbar, text="Nessuna anteprima",
            font=theme.font(13, "bold"), text_color=theme.INK,
            anchor="w",
        )
        self.title_lbl.pack(side="left", fill="x", expand=True)

        doc_actions = ctk.CTkFrame(
            toolbar, fg_color=theme.CARD, corner_radius=6,
            border_width=1, border_color=theme.RULE,
        )
        doc_actions.pack(side="right", padx=(10, 0))

        self.copy_btn = theme.ghost_button(
            doc_actions, "Copia", width=72, height=28,
            command=self._copy_current,
        )
        self.copy_btn.pack(side="left", padx=(6, 4), pady=5)

        self.editor_btn = theme.ghost_button(
            doc_actions, "Apri editor", width=106, height=28,
            command=self.open_markdown_preview,
        )
        self.editor_btn.pack(side="left", padx=(0, 6), pady=5)

        # ── Preview body ──────────────────────────────────────────────────
        body = ctk.CTkFrame(self, fg_color=theme.CARD, corner_radius=8,
                            border_width=1, border_color=theme.RULE)
        body.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 12))
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=1)

        self.md_textbox = tk.Text(
            body, wrap="word",
            bg=theme.CARD, fg=theme.INK_2,
            insertbackground=theme.INK,
            relief="flat", bd=0, highlightthickness=0,
            padx=22, pady=18,
            font=(theme.ui_family(), 12),
            state="disabled",
        )
        self.md_textbox.grid(row=0, column=0, sticky="nsew")

        sb = ctk.CTkScrollbar(body, command=self.md_textbox.yview)
        preview_scrollbar_visible = {"value": False}

        def show_preview_scrollbar():
            if not preview_scrollbar_visible["value"]:
                sb.grid(row=0, column=1, sticky="ns")
                preview_scrollbar_visible["value"] = True

        def hide_preview_scrollbar():
            if preview_scrollbar_visible["value"]:
                sb.grid_remove()
                preview_scrollbar_visible["value"] = False

        theme.autohide_text_scrollbar(
            self.md_textbox, sb, show_preview_scrollbar, hide_preview_scrollbar,
        )

        self._setup_md_tags()

        # ── Actions row (mounted into actions_parent if given) ────────────
        action_row = actions_parent or ctk.CTkFrame(self, fg_color="transparent")
        if actions_parent is None:
            action_row.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 12))

        combined_actions = ctk.CTkFrame(
            action_row, fg_color=theme.CARD, corner_radius=6,
            border_width=1, border_color=theme.RULE,
        )
        combined_actions.pack(anchor="w", pady=(0, 6))
        self.copy_all_btn = theme.ghost_button(
            combined_actions, "Copia tutti",
            command=self._copy_all_md, state="disabled",
            width=100, height=28,
        )
        self.copy_all_btn.pack(side="left", padx=(6, 4), pady=5)

        self.export_all_btn = theme.ghost_button(
            combined_actions, "Salva unito...",
            command=self._export_all_md, state="disabled",
            width=110, height=28,
        )
        self.export_all_btn.pack(side="left", padx=(0, 4), pady=5)

        self.combined_editor_btn = theme.ghost_button(
            combined_actions, "Apri editor",
            command=self._open_combined_editor, state="disabled",
            width=110, height=28,
        )
        self.combined_editor_btn.pack(side="left", padx=(0, 6), pady=5)

        utility_actions = ctk.CTkFrame(
            action_row, fg_color="transparent",
        )
        utility_actions.pack(anchor="w")

        self.open_folder_btn = theme.ghost_button(
            utility_actions, "Apri cartella output",
            command=self._open_output_folder, state="disabled",
            width=160, height=28,
        )
        self.open_folder_btn.pack(side="left")

        self.merge_btn = theme.ghost_button(
            utility_actions, "Merge MD", width=90, height=28,
            command=self._open_merge_dialog,
        )
        self.merge_btn.pack(side="left", padx=(6, 0))

        self.clear_preview_btn = theme.ghost_button(
            utility_actions, "Pulisci", width=78, height=28,
            command=self.clear_preview,
        )
        self.clear_preview_btn.pack(side="left", padx=(6, 0))

        self.clear_preview()

    # ─── Markdown tag setup for inline preview ────────────────────────────
    def _setup_md_tags(self):
        base = tkfont.Font(font=self.md_textbox["font"])
        h1 = base.copy(); h1.configure(size=20, weight="bold")
        h2 = base.copy(); h2.configure(size=16, weight="bold")
        h3 = base.copy(); h3.configure(size=13, weight="bold")
        bold = base.copy(); bold.configure(weight="bold")
        italic = base.copy(); italic.configure(slant="italic")
        mono = tkfont.Font(family=theme.mono_family(), size=10)

        self.md_textbox.tag_configure("h1", font=h1, foreground=theme.INK,
                                      spacing1=12, spacing3=6)
        self.md_textbox.tag_configure("h2", font=h2, foreground=theme.INK,
                                      spacing1=10, spacing3=4)
        self.md_textbox.tag_configure("h3", font=h3, foreground=theme.INK,
                                      spacing1=8, spacing3=3)
        self.md_textbox.tag_configure("bold", font=bold, foreground=theme.INK)
        self.md_textbox.tag_configure("italic", font=italic)
        self.md_textbox.tag_configure("code", font=mono, background=theme.PAPER_2,
                                      foreground=theme.INK)
        self.md_textbox.tag_configure("placeholder",
                                      foreground=theme.INK_4, justify="center")

    def _apply_md_tags(self):
        for tag in ("h1", "h2", "h3", "bold", "italic", "code"):
            self.md_textbox.tag_remove(tag, "1.0", "end")

        line_count = int(self.md_textbox.index("end-1c").split(".")[0])
        for line_no in range(1, line_count + 1):
            ls, le = f"{line_no}.0", f"{line_no}.end"
            line = self.md_textbox.get(ls, le)
            if line.startswith("### "):
                self.md_textbox.tag_add("h3", ls, le)
            elif line.startswith("## "):
                self.md_textbox.tag_add("h2", ls, le)
            elif line.startswith("# "):
                self.md_textbox.tag_add("h1", ls, le)

            search = ls
            while True:
                s = self.md_textbox.search("**", search, le)
                if not s: break
                e = self.md_textbox.search("**", f"{s}+2c", le)
                if not e: break
                self.md_textbox.tag_add("bold", f"{s}+2c", e)
                search = f"{e}+2c"

            search = ls
            while True:
                s = self.md_textbox.search("`", search, le)
                if not s: break
                e = self.md_textbox.search("`", f"{s}+1c", le)
                if not e: break
                self.md_textbox.tag_add("code", s, f"{e}+1c")
                search = f"{e}+1c"

    # ─── Public API ───────────────────────────────────────────────────────
    def show_markdown_file(self, md_path: Path) -> None:
        self._current_md_path = md_path
        try:
            content = md_path.read_text(encoding="utf-8")
        except OSError:
            content = ""
        self.title_lbl.configure(text=md_path.name)
        self._fill_preview(content)
        self.editor_btn.configure(state="normal")
        self.copy_btn.configure(state="normal")

    def clear_preview(self, message: str = "") -> None:
        self._current_md_path = None
        self.title_lbl.configure(text="Nessuna anteprima")
        self.editor_btn.configure(state="disabled")
        self.copy_btn.configure(state="disabled")
        self.md_textbox.configure(state="normal")
        self.md_textbox.delete("1.0", "end")
        if not message:
            message = ("Seleziona un documento per vedere l'anteprima\n"
                       "del Markdown convertito qui.")
        self.md_textbox.insert("1.0", message, "placeholder")
        self.md_textbox.configure(state="disabled")

    def open_markdown_preview(self) -> None:
        if not self._current_md_path or not self._current_md_path.exists():
            return
        if self._editor_window and self._editor_window.winfo_exists():
            self._editor_window.lift()
            self._editor_window.focus()
            return
        self._editor_window = MarkdownEditorWindow(
            self, self._current_md_path,
            on_saved=self._on_editor_saved,
        )

    def set_output_dir(self, path: Path) -> None:
        self._output_dir = path
        self.open_folder_btn.configure(state="normal")

    def set_all_mds(self, md_paths: list[Path]) -> None:
        self._all_md_paths = [p for p in md_paths if p.exists()]
        self._combined_md_path = None
        if self._all_md_paths:
            self.copy_all_btn.configure(state="normal")
            self.export_all_btn.configure(state="normal")
            self.combined_editor_btn.configure(state="normal")

    def add_merge_paths(self, paths: list[Path]) -> None:
        added = 0
        for path in paths:
            path = Path(path)
            if path.is_dir():
                for ext in _MERGE_EXTENSIONS:
                    for child in sorted(path.glob(f"*{ext}")):
                        if self._add_merge_path(child):
                            added += 1
                continue
            if self._add_merge_path(path):
                added += 1
        if added and self._merge_window and self._merge_window.winfo_exists():
            self._refresh_merge_dialog()

    def clear(self) -> None:
        self.clear_preview()
        self._all_md_paths = []
        self._combined_md_path = None
        self.copy_all_btn.configure(state="disabled")
        self.export_all_btn.configure(state="disabled")
        self.combined_editor_btn.configure(state="disabled")

    # ─── Internals ────────────────────────────────────────────────────────
    def _fill_preview(self, content: str):
        self.md_textbox.configure(state="normal")
        self.md_textbox.delete("1.0", "end")
        self.md_textbox.insert("1.0", content or "")
        self._apply_md_tags()
        self.md_textbox.configure(state="disabled")

    def _on_editor_saved(self, md_path: Path, content: str) -> None:
        if self._current_md_path == md_path:
            self._fill_preview(content)

    def _add_merge_path(self, path: Path) -> bool:
        if path.suffix.lower() not in _MERGE_EXTENSIONS or not path.is_file():
            return False
        key = path.resolve(strict=False)
        if key in self._merge_path_keys:
            return False
        self._merge_path_keys.add(key)
        self._merge_items.append({"type": "path", "path": path})
        return True

    def _open_merge_dialog(self) -> None:
        if self._merge_window and self._merge_window.winfo_exists():
            self._merge_window.lift()
            self._merge_window.focus()
            return

        dlg = ctk.CTkToplevel(self)
        self._merge_window = dlg
        dlg.title("Merge Markdown")
        dlg.geometry("640x420")
        dlg.minsize(520, 340)
        dlg.transient(self)
        try:
            dlg.configure(fg_color=theme.PAPER)
        except Exception:
            pass

        head = ctk.CTkFrame(dlg, fg_color="transparent")
        head.pack(padx=18, pady=(16, 8), fill="x")
        ctk.CTkLabel(
            head, text="Merge Markdown",
            font=theme.font(15, "bold"), text_color=theme.INK,
        ).pack(side="left")
        self._merge_count_label = ctk.CTkLabel(
            head, text="0 elementi",
            font=theme.font(11, mono=True), text_color=theme.INK_3,
        )
        self._merge_count_label.pack(side="right")

        self._merge_listbox = tk.Text(
            dlg, height=10, wrap="word",
            bg=theme.CARD, fg=theme.INK_2,
            relief="flat", bd=0, highlightthickness=1,
            highlightbackground=theme.RULE,
            padx=12, pady=10,
            font=(theme.mono_family(), 10),
            state="disabled",
        )
        self._merge_listbox.pack(padx=18, pady=(0, 10), fill="both", expand=True)

        actions = ctk.CTkFrame(dlg, fg_color="transparent")
        actions.pack(padx=18, pady=(0, 16), fill="x")

        theme.ghost_button(actions, "Aggiungi MD", width=110, height=28,
                           command=self._pick_merge_files).pack(side="left")
        theme.ghost_button(actions, "Incolla", width=80, height=28,
                           command=self._paste_merge_text).pack(side="left", padx=(6, 0))
        theme.ghost_button(actions, "Svuota", width=80, height=28,
                           command=self._clear_merge_items).pack(side="left", padx=(6, 0))
        theme.amber_button(actions, "Copia", width=90, height=28,
                           command=self._copy_merge_md).pack(side="right", padx=(6, 0))
        theme.ghost_button(actions, "Salva...", width=90, height=28,
                           command=self._export_merge_md).pack(side="right")

        self._refresh_merge_dialog()

    def _refresh_merge_dialog(self) -> None:
        if not self._merge_window or not self._merge_window.winfo_exists():
            return
        self._merge_listbox.configure(state="normal")
        self._merge_listbox.delete("1.0", "end")
        if not self._merge_items:
            self._merge_listbox.insert("1.0", "Aggiungi file .md o incolla testo Markdown.")
        else:
            lines = []
            for idx, item in enumerate(self._merge_items, start=1):
                if item.get("type") == "path":
                    lines.append(f"{idx}. {Path(item['path']).name}")
                else:
                    preview = " ".join(str(item.get("content", "")).split())[:72]
                    lines.append(f"{idx}. {item.get('label')} - {preview}")
            self._merge_listbox.insert("1.0", "\n".join(lines))
        self._merge_listbox.configure(state="disabled")
        n = len(self._merge_items)
        self._merge_count_label.configure(text=f"{n} elemento" if n == 1 else f"{n} elementi")

    def _pick_merge_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Seleziona Markdown da unire",
            filetypes=[("Markdown", "*.md *.markdown"), ("Tutti i file", "*.*")],
        )
        self.add_merge_paths([Path(p) for p in paths])

    def _paste_merge_text(self) -> None:
        try:
            text = self.winfo_toplevel().clipboard_get().strip()
        except Exception:
            return
        if not text:
            return
        paths = []
        for line in text.splitlines():
            candidate = Path(line.strip().strip('"'))
            if candidate.exists():
                paths.append(candidate)
        if paths:
            self.add_merge_paths(paths)
            return
        label = f"Appunti {sum(1 for item in self._merge_items if item.get('type') == 'text') + 1}"
        self._merge_items.append({"type": "text", "label": label, "content": text})
        self._refresh_merge_dialog()

    def _clear_merge_items(self) -> None:
        self._merge_items.clear()
        self._merge_path_keys.clear()
        self._refresh_merge_dialog()

    def _build_manual_merge_md(self) -> str:
        parts = []
        for item in self._merge_items:
            if item.get("type") == "path":
                path = Path(item["path"])
                try:
                    content = path.read_text(encoding="utf-8").strip()
                except OSError:
                    continue
                label = path.stem
            else:
                content = str(item.get("content", "")).strip()
                label = str(item.get("label", "Appunti"))
            if content:
                parts.append(f"<!-- {label} -->\n\n{content}")
        return "\n\n---\n\n".join(parts)

    def _copy_merge_md(self) -> None:
        combined = self._build_manual_merge_md()
        if not combined:
            return
        root = self.winfo_toplevel()
        root.clipboard_clear()
        root.clipboard_append(combined)

    def _export_merge_md(self) -> None:
        combined = self._build_manual_merge_md()
        if not combined:
            return
        save_path = filedialog.asksaveasfilename(
            title="Salva merge Markdown",
            defaultextension=".md",
            filetypes=[("Markdown", "*.md"), ("Testo", "*.txt"), ("Tutti i file", "*.*")],
            initialfile="merge_markdown.md",
        )
        if save_path:
            try:
                Path(save_path).write_text(combined, encoding="utf-8")
            except OSError:
                pass

    def _copy_current(self) -> None:
        if not self._current_md_path or not self._current_md_path.exists():
            return
        try:
            content = self._current_md_path.read_text(encoding="utf-8")
        except OSError:
            return
        root = self.winfo_toplevel()
        root.clipboard_clear()
        root.clipboard_append(content)
        self.copy_btn.configure(text="Copiato")
        self.after(1500, lambda: self.copy_btn.configure(text="Copia"))

    def _build_combined_md(self) -> str:
        parts = []
        for p in self._all_md_paths:
            try:
                content = p.read_text(encoding="utf-8").strip()
                if content:
                    parts.append(f"<!-- {p.stem} -->\n\n{content}")
            except OSError:
                pass
        return "\n\n---\n\n".join(parts)

    def _default_combined_path(self) -> Path | None:
        if self._combined_md_path:
            return self._combined_md_path
        if self._output_dir and self._output_dir.exists():
            return self._output_dir / "documenti_uniti.md"
        for path in self._all_md_paths:
            if path.parent.exists():
                return path.parent / "documenti_uniti.md"
        return None

    def _write_combined_md(self, path: Path, content: str) -> bool:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        except OSError:
            return False
        self._combined_md_path = path
        return True

    def _copy_all_md(self) -> None:
        combined = self._build_combined_md()
        if not combined:
            return
        root = self.winfo_toplevel()
        root.clipboard_clear()
        root.clipboard_append(combined)
        self.copy_all_btn.configure(text="✓ Copiato")
        self.after(1800, lambda: self.copy_all_btn.configure(text="Copia tutti"))

    def _export_all_md(self) -> None:
        combined = self._build_combined_md()
        if not combined:
            return
        save_path = filedialog.asksaveasfilename(
            title="Salva MD unito",
            defaultextension=".md",
            filetypes=[("Markdown", "*.md"), ("Testo", "*.txt"), ("Tutti i file", "*.*")],
            initialfile="documenti_uniti.md",
        )
        if not save_path:
            return
        try:
            ok = self._write_combined_md(Path(save_path), combined)
            if ok:
                self.export_all_btn.configure(text="✓ Salvato")
                self.after(1800, lambda: self.export_all_btn.configure(text="Salva unito..."))
        except OSError:
            pass

    def _open_combined_editor(self) -> None:
        if self._combined_editor_window and self._combined_editor_window.winfo_exists():
            self._combined_editor_window.lift()
            self._combined_editor_window.focus()
            return
        combined = self._build_combined_md()
        if not combined:
            return
        path = self._default_combined_path()
        if path is None:
            save_path = filedialog.asksaveasfilename(
                title="Salva MD unito",
                defaultextension=".md",
                filetypes=[("Markdown", "*.md"), ("Testo", "*.txt"), ("Tutti i file", "*.*")],
                initialfile="documenti_uniti.md",
            )
            if not save_path:
                return
            path = Path(save_path)
        if not self._write_combined_md(path, combined):
            return
        self._combined_editor_window = MarkdownEditorWindow(self, path)

    def _open_output_folder(self) -> None:
        if self._output_dir and self._output_dir.exists():
            open_with_system(self._output_dir)
