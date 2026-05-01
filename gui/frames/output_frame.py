"""Output preview frame."""

import subprocess
import sys
import tkinter as tk
from tkinter import font as tkfont
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

_MERGE_EXTENSIONS = (".md", ".markdown")
_PREVIEW_TAB_NAME = "Apri editor Markdown"


class MarkdownEditorWindow(ctk.CTkToplevel):
    """Large editable Markdown preview with lightweight rich styling and autosave."""

    def __init__(self, master, md_path: Path, on_saved: callable | None = None):
        super().__init__(master)
        self.title(f"Anteprima Markdown - {md_path.name}")
        self.geometry("920x720")
        self.minsize(720, 520)
        self.transient(master)

        self.md_path = md_path
        self.on_saved = on_saved
        self._save_after_id: str | None = None
        self._highlight_after_id: str | None = None

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(padx=14, pady=(12, 6), fill="x")

        ctk.CTkLabel(
            header,
            text=md_path.name,
            font=ctk.CTkFont(size=16, weight="bold"),
        ).pack(side="left", fill="x", expand=True, anchor="w")

        self.status_label = ctk.CTkLabel(
            header,
            text="Salvato",
            font=ctk.CTkFont(size=11),
            text_color="gray55",
        )
        self.status_label.pack(side="right")

        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.pack(padx=14, pady=(0, 8), fill="x")

        ctk.CTkButton(
            toolbar,
            text="B",
            width=34,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=lambda: self._wrap_selection("**", "**"),
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            toolbar,
            text="I",
            width=34,
            font=ctk.CTkFont(size=13, slant="italic"),
            fg_color="transparent",
            border_width=1,
            command=lambda: self._wrap_selection("*", "*"),
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            toolbar,
            text="U",
            width=34,
            font=ctk.CTkFont(size=13, underline=True),
            fg_color="transparent",
            border_width=1,
            command=lambda: self._wrap_selection("<u>", "</u>"),
        ).pack(side="left")

        body = ctk.CTkFrame(self)
        body.pack(padx=14, pady=(0, 14), fill="both", expand=True)

        self.text = tk.Text(
            body,
            wrap="word",
            undo=True,
            padx=14,
            pady=12,
            borderwidth=0,
            highlightthickness=0,
            font=("Segoe UI", 11),
        )
        scrollbar = ctk.CTkScrollbar(body, command=self.text.yview)
        self.text.configure(yscrollcommand=scrollbar.set)
        self.text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self._configure_tags()
        self._load_file()
        self.text.bind("<<Modified>>", self._on_modified)
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _configure_tags(self) -> None:
        base = tkfont.Font(font=self.text["font"])
        h1 = base.copy()
        h1.configure(size=18, weight="bold")
        h2 = base.copy()
        h2.configure(size=15, weight="bold")
        bold = base.copy()
        bold.configure(weight="bold")
        mono = tkfont.Font(family="Consolas", size=10)

        self.text.tag_configure("h1", font=h1, spacing1=10, spacing3=6)
        self.text.tag_configure("h2", font=h2, spacing1=8, spacing3=4)
        self.text.tag_configure("bold", font=bold)
        italic = base.copy()
        italic.configure(slant="italic")
        underline = base.copy()
        underline.configure(underline=True)
        self.text.tag_configure("italic", font=italic)
        self.text.tag_configure("underline", font=underline)
        self.text.tag_configure("code", font=mono, background="#eeeeee")

    def _load_file(self) -> None:
        try:
            content = self.md_path.read_text(encoding="utf-8")
        except OSError:
            content = ""
        self.text.insert("1.0", content)
        self.text.edit_modified(False)
        self._apply_markdown_tags()

    def _on_modified(self, _event=None) -> None:
        if not self.text.edit_modified():
            return
        self.text.edit_modified(False)
        self.status_label.configure(text="Modificato...")
        if self._save_after_id:
            self.after_cancel(self._save_after_id)
        if self._highlight_after_id:
            self.after_cancel(self._highlight_after_id)
        self._save_after_id = self.after(500, self._save)
        self._highlight_after_id = self.after(350, self._apply_markdown_tags)

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
            self.text.tag_add(
                "sel",
                f"{start}+{len(prefix)}c",
                f"{start}+{len(prefix) + len(selected)}c",
            )
        self.text.focus_set()
        self.text.edit_modified(True)
        self._on_modified()

    def _apply_markdown_tags(self) -> None:
        self._highlight_after_id = None
        cursor = self.text.index("insert")
        for tag in ("h1", "h2", "bold", "italic", "underline", "code"):
            self.text.tag_remove(tag, "1.0", "end")

        line_count = int(self.text.index("end-1c").split(".")[0])
        for line_no in range(1, line_count + 1):
            line_start = f"{line_no}.0"
            line_end = f"{line_no}.end"
            line = self.text.get(line_start, line_end)
            if line.startswith("# "):
                self.text.tag_add("h1", line_start, line_end)
            elif line.startswith("## "):
                self.text.tag_add("h2", line_start, line_end)

            search_from = line_start
            while True:
                start = self.text.search("**", search_from, line_end)
                if not start:
                    break
                end = self.text.search("**", f"{start}+2c", line_end)
                if not end:
                    break
                self.text.tag_add("bold", f"{start}+2c", end)
                search_from = f"{end}+2c"

            search_from = line_start
            while True:
                start = self.text.search("<u>", search_from, line_end)
                if not start:
                    break
                end = self.text.search("</u>", f"{start}+3c", line_end)
                if not end:
                    break
                self.text.tag_add("underline", f"{start}+3c", end)
                search_from = f"{end}+4c"

            search_from = line_start
            while True:
                start = self.text.search("*", search_from, line_end)
                if not start:
                    break
                if self.text.get(start, f"{start}+2c") == "**":
                    search_from = f"{start}+2c"
                    continue
                end = self.text.search("*", f"{start}+1c", line_end)
                if not end:
                    break
                if self.text.get(end, f"{end}+2c") == "**":
                    search_from = f"{end}+2c"
                    continue
                self.text.tag_add("italic", f"{start}+1c", end)
                search_from = f"{end}+1c"

            search_from = line_start
            while True:
                start = self.text.search("`", search_from, line_end)
                if not start:
                    break
                end = self.text.search("`", f"{start}+1c", line_end)
                if not end:
                    break
                self.text.tag_add("code", start, f"{end}+1c")
                search_from = f"{end}+1c"

        self.text.mark_set("insert", cursor)

    def _close(self) -> None:
        if self._save_after_id:
            self.after_cancel(self._save_after_id)
            self._save()
        self.destroy()


class OutputFrame(ctk.CTkFrame):
    """Results preview with output actions."""

    def __init__(self, master, actions_parent=None, **kwargs):
        super().__init__(master, **kwargs)
        self._output_dir: Path | None = None
        self._all_md_paths: list[Path] = []
        self._current_md_path: Path | None = None
        self._editor_window: MarkdownEditorWindow | None = None
        self._suppress_tab_command = False

        # ── Preview tab ───────────────────────────────────────────────────────
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(padx=10, pady=(10, 4), fill="both", expand=True)

        self.tab_md = self.tabview.add(_PREVIEW_TAB_NAME)

        self.md_textbox = ctk.CTkTextbox(
            self.tab_md,
            font=ctk.CTkFont(family="Consolas", size=11),
        )
        self.md_textbox.pack(fill="both", expand=True)
        self.md_textbox.configure(state="disabled")
        self._bind_preview_tab()

        self._merge_items: list[dict[str, object]] = []
        self._merge_path_keys: set[Path] = set()

        self.merge_frame = ctk.CTkFrame(self, fg_color=("gray92", "gray14"), corner_radius=6)
        self.merge_frame.pack(padx=10, pady=(0, 6), fill="x")

        merge_header = ctk.CTkFrame(self.merge_frame, fg_color="transparent")
        merge_header.pack(padx=10, pady=(8, 4), fill="x")

        ctk.CTkLabel(
            merge_header,
            text="MERGE MARKDOWN",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color="gray60",
        ).pack(side="left")

        self.merge_count_label = ctk.CTkLabel(
            merge_header,
            text="0 file",
            font=ctk.CTkFont(size=11),
            text_color="gray55",
        )
        self.merge_count_label.pack(side="right")

        self.merge_drop_box = ctk.CTkTextbox(
            self.merge_frame,
            height=58,
            font=ctk.CTkFont(family="Consolas", size=10),
            wrap="word",
        )
        self.merge_drop_box.pack(padx=10, pady=(0, 6), fill="x")
        self.merge_drop_box.bind("<Control-v>", self._paste_merge_from_clipboard)
        self.merge_drop_box.bind("<Command-v>", self._paste_merge_from_clipboard)

        merge_actions = ctk.CTkFrame(self.merge_frame, fg_color="transparent")
        merge_actions.pack(padx=10, pady=(0, 8), fill="x")

        self.merge_paste_btn = ctk.CTkButton(
            merge_actions,
            text="Incolla",
            command=self._paste_merge_from_clipboard,
            width=82,
            fg_color="transparent",
            border_width=1,
        )
        self.merge_paste_btn.pack(side="left")

        self.merge_clear_btn = ctk.CTkButton(
            merge_actions,
            text="Svuota",
            command=self._clear_merge_items,
            width=78,
            fg_color="transparent",
            border_width=1,
            state="disabled",
        )
        self.merge_clear_btn.pack(side="left", padx=(6, 0))

        self.merge_copy_btn = ctk.CTkButton(
            merge_actions,
            text="Copia merge",
            command=self._copy_merge_md,
            width=112,
            state="disabled",
        )
        self.merge_copy_btn.pack(side="right")

        self.merge_save_btn = ctk.CTkButton(
            merge_actions,
            text="Salva merge...",
            command=self._export_merge_md,
            width=118,
            fg_color="transparent",
            border_width=1,
            state="disabled",
        )
        self.merge_save_btn.pack(side="right", padx=(0, 6))

        self._refresh_merge_box()

        # ── Action buttons row ────────────────────────────────────────────────
        action_row = actions_parent or ctk.CTkFrame(self, fg_color="transparent")
        if actions_parent is None:
            action_row.pack(padx=10, pady=(0, 8), fill="x")

        self.open_folder_btn = ctk.CTkButton(
            action_row,
            text="Apri cartella output",
            command=self._open_output_folder,
            state="disabled",
            width=160,
        )
        self.open_folder_btn.pack(side="left")

        self.copy_all_btn = ctk.CTkButton(
            action_row,
            text="⎘  Copia tutti",
            command=self._copy_all_md,
            state="disabled",
            width=120,
            fg_color="transparent",
            border_width=1,
        )
        self.copy_all_btn.pack(side="left", padx=(8, 0))

        self.export_all_btn = ctk.CTkButton(
            action_row,
            text="↓  Salva unito…",
            command=self._export_all_md,
            state="disabled",
            width=130,
            fg_color="transparent",
            border_width=1,
        )
        self.export_all_btn.pack(side="left", padx=(6, 0))

    # ─── Public API ──────────────────────────────────────────────────────────

    def get_output_formats(self) -> list[str]:
        return ["markdown"]

    def show_markdown(self, content: str) -> None:
        self._current_md_path = None
        self.md_textbox.configure(state="normal")
        self.md_textbox.delete("1.0", "end")
        self.md_textbox.insert("1.0", content)
        self.md_textbox.configure(state="disabled")
        self._set_markdown_tab()

    def show_markdown_file(self, md_path: Path) -> None:
        self._current_md_path = md_path
        try:
            content = md_path.read_text(encoding="utf-8")
        except OSError:
            content = ""
        self.md_textbox.configure(state="normal")
        self.md_textbox.delete("1.0", "end")
        self.md_textbox.insert("1.0", content)
        self.md_textbox.configure(state="disabled")
        self._set_markdown_tab()

    def clear_preview(self, message: str = "") -> None:
        self._current_md_path = None
        self.md_textbox.configure(state="normal")
        self.md_textbox.delete("1.0", "end")
        if message:
            self.md_textbox.insert("1.0", message)
        self.md_textbox.configure(state="disabled")
        self._set_markdown_tab()

    def refresh_current_preview(self) -> None:
        if self._current_md_path and self._current_md_path.exists():
            self.show_markdown_file(self._current_md_path)

    def open_markdown_preview(self) -> None:
        if not self._current_md_path or not self._current_md_path.exists():
            return
        if self._editor_window and self._editor_window.winfo_exists():
            self._editor_window.lift()
            self._editor_window.focus()
            return
        self._editor_window = MarkdownEditorWindow(
            self,
            self._current_md_path,
            on_saved=self._on_editor_saved,
        )

    def show_json(self, content: str) -> None:
        pass  # JSON output not used

    def set_output_dir(self, path: Path) -> None:
        self._output_dir = path
        self.open_folder_btn.configure(state="normal")

    def set_all_mds(self, md_paths: list[Path]) -> None:
        """Enable copy-all and export buttons with the given MD file list."""
        self._all_md_paths = [p for p in md_paths if p.exists()]
        if self._all_md_paths:
            self.copy_all_btn.configure(state="normal")
            self.export_all_btn.configure(state="normal")

    def add_merge_paths(self, paths: list[Path]) -> None:
        """Add Markdown files to the manual merge area."""
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
        if added:
            self._refresh_merge_box()

    def clear(self) -> None:
        self.md_textbox.configure(state="normal")
        self.md_textbox.delete("1.0", "end")
        self.md_textbox.configure(state="disabled")
        self._current_md_path = None
        self._all_md_paths = []
        self.copy_all_btn.configure(state="disabled")
        self.export_all_btn.configure(state="disabled")

    def set_enabled(self, enabled: bool) -> None:
        pass  # kept for API compatibility

    # ─── Internal ────────────────────────────────────────────────────────────

    def _bind_preview_tab(self) -> None:
        try:
            self.tabview.configure(command=self._on_tab_selected)
        except Exception:
            pass
        try:
            self.tabview._segmented_button._buttons_dict[_PREVIEW_TAB_NAME].configure(
                command=self.open_markdown_preview
            )
        except Exception:
            pass

    def _on_tab_selected(self) -> None:
        if not self._suppress_tab_command:
            self.open_markdown_preview()

    def _set_markdown_tab(self) -> None:
        self._suppress_tab_command = True
        try:
            self.tabview.set(_PREVIEW_TAB_NAME)
        finally:
            self._suppress_tab_command = False

    def _on_editor_saved(self, md_path: Path, content: str) -> None:
        if self._current_md_path == md_path:
            self.md_textbox.configure(state="normal")
            self.md_textbox.delete("1.0", "end")
            self.md_textbox.insert("1.0", content)
            self.md_textbox.configure(state="disabled")

    def _add_merge_path(self, path: Path) -> bool:
        if path.suffix.lower() not in _MERGE_EXTENSIONS or not path.is_file():
            return False
        key = path.resolve(strict=False)
        if key in self._merge_path_keys:
            return False
        self._merge_path_keys.add(key)
        self._merge_items.append({"type": "path", "path": path})
        return True

    def _paste_merge_from_clipboard(self, event=None):
        clipboard_paths = self._clipboard_file_paths()
        if clipboard_paths:
            self.add_merge_paths(clipboard_paths)
            return "break"

        try:
            text = self.winfo_toplevel().clipboard_get()
        except Exception:
            return "break"

        text = text.strip()
        if not text:
            return "break"

        paths = self._clipboard_text_to_paths(text)
        if paths:
            self.add_merge_paths(paths)
            return "break"

        label = f"Appunti {sum(1 for item in self._merge_items if item.get('type') == 'text') + 1}"
        self._merge_items.append({"type": "text", "label": label, "content": text})
        self._refresh_merge_box()
        return "break"

    def _clipboard_text_to_paths(self, text: str) -> list[Path]:
        paths: list[Path] = []

        def normalize(raw: str) -> Path | None:
            value = raw.strip().strip('"')
            if value.startswith("{") and value.endswith("}"):
                value = value[1:-1].strip()
            if value.startswith("file://"):
                import urllib.parse
                import urllib.request
                value = urllib.request.url2pathname(urllib.parse.urlparse(value).path)
            if not value:
                return None
            path = Path(value)
            return path if path.exists() else None

        for line in text.splitlines():
            path = normalize(line)
            if path:
                paths.append(path)

        if paths:
            return paths

        try:
            split_items = self.tk.splitlist(text)
        except Exception:
            split_items = []
        for item in split_items:
            path = normalize(item)
            if path:
                paths.append(path)
        return paths

    def _clipboard_file_paths(self) -> list[Path]:
        if sys.platform != "win32":
            return []

        try:
            import ctypes
            from ctypes import wintypes
        except Exception:
            return []

        user32 = ctypes.windll.user32
        shell32 = ctypes.windll.shell32
        cf_hdrop = 15

        user32.OpenClipboard.argtypes = [wintypes.HWND]
        user32.OpenClipboard.restype = wintypes.BOOL
        user32.CloseClipboard.argtypes = []
        user32.CloseClipboard.restype = wintypes.BOOL
        user32.GetClipboardData.argtypes = [wintypes.UINT]
        user32.GetClipboardData.restype = wintypes.HANDLE
        shell32.DragQueryFileW.argtypes = [
            wintypes.HANDLE,
            wintypes.UINT,
            wintypes.LPWSTR,
            wintypes.UINT,
        ]
        shell32.DragQueryFileW.restype = wintypes.UINT

        if not user32.OpenClipboard(None):
            return []

        try:
            handle = user32.GetClipboardData(cf_hdrop)
            if not handle:
                return []
            count = shell32.DragQueryFileW(handle, 0xFFFFFFFF, None, 0)
            paths = []
            for index in range(count):
                length = shell32.DragQueryFileW(handle, index, None, 0)
                buffer = ctypes.create_unicode_buffer(length + 1)
                shell32.DragQueryFileW(handle, index, buffer, length + 1)
                if buffer.value:
                    paths.append(Path(buffer.value))
            return paths
        finally:
            user32.CloseClipboard()

    def _refresh_merge_box(self) -> None:
        self.merge_drop_box.configure(state="normal")
        self.merge_drop_box.delete("1.0", "end")

        if not self._merge_items:
            self.merge_drop_box.insert(
                "1.0",
                "Trascina qui file .md, oppure incolla percorsi o testo Markdown.",
            )
        else:
            lines = []
            for idx, item in enumerate(self._merge_items, start=1):
                if item.get("type") == "path":
                    path = item["path"]
                    lines.append(f"{idx}. {Path(path).name}")
                else:
                    content = str(item.get("content", ""))
                    preview = " ".join(content.split())[:72]
                    lines.append(f"{idx}. {item.get('label')} - {preview}")
            self.merge_drop_box.insert("1.0", "\n".join(lines))

        self.merge_drop_box.configure(state="disabled")
        state = "normal" if self._merge_items else "disabled"
        self.merge_clear_btn.configure(state=state)
        self.merge_copy_btn.configure(state=state)
        self.merge_save_btn.configure(state=state)
        n = len(self._merge_items)
        self.merge_count_label.configure(text=f"{n} elemento" if n == 1 else f"{n} elementi")

    def _clear_merge_items(self) -> None:
        self._merge_items.clear()
        self._merge_path_keys.clear()
        self._refresh_merge_box()

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
        self.merge_copy_btn.configure(text="Copiato")
        self.after(1800, lambda: self.merge_copy_btn.configure(text="Copia merge"))

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
        if not save_path:
            return
        try:
            Path(save_path).write_text(combined, encoding="utf-8")
            self.merge_save_btn.configure(text="Salvato")
            self.after(1800, lambda: self.merge_save_btn.configure(text="Salva merge..."))
        except OSError:
            pass

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

    def _copy_all_md(self) -> None:
        combined = self._build_combined_md()
        if not combined:
            return
        root = self.winfo_toplevel()
        root.clipboard_clear()
        root.clipboard_append(combined)
        # Brief visual feedback
        self.copy_all_btn.configure(text="✓  Copiato!")
        self.after(1800, lambda: self.copy_all_btn.configure(text="⎘  Copia tutti"))

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
            Path(save_path).write_text(combined, encoding="utf-8")
            # Brief visual feedback
            self.export_all_btn.configure(text="✓  Salvato!")
            self.after(1800, lambda: self.export_all_btn.configure(text="↓  Salva unito…"))
        except OSError:
            pass

    def _open_output_folder(self) -> None:
        if self._output_dir and self._output_dir.exists():
            if sys.platform == "win32":
                subprocess.Popen(["explorer", str(self._output_dir)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(self._output_dir)])
            else:
                subprocess.Popen(["xdg-open", str(self._output_dir)])
