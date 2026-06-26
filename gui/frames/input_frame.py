"""File selection sidebar — dropzone + file rows with status pill, size, pages."""

from __future__ import annotations
import ctypes
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from gui import theme
from gui.resources import app_capture_dir

SUPPORTED_EXTENSIONS = (
    ".pdf", ".txt", ".eml", ".msg", ".docx", ".html", ".htm", ".md", ".rtf",
    ".jpg", ".jpeg", ".png", ".webp", ".tiff", ".tif", ".bmp", ".gif",
    ".mp3", ".wav", ".flac", ".m4a", ".ogg", ".mp4", ".opus",
    ".p7m", ".zip", ".7z", ".tar", ".tgz", ".wachat",
)

CF_HDROP = 15


def _format_size(num_bytes: int) -> str:
    if num_bytes is None:
        return ""
    n = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(n)} {unit}"
            return f"{n:.1f} {unit}".replace(".0 ", " ")
        n /= 1024
    return f"{n:.1f} GB"


def _count_pdf_pages(path: Path) -> int | None:
    try:
        import fitz  # PyMuPDF
        with fitz.open(str(path)) as doc:
            return doc.page_count
    except Exception:
        return None


def _normalise_candidate_path(raw: str) -> Path | None:
    text = raw.strip().strip('"')
    if not text:
        return None
    if text.startswith("file://"):
        try:
            import urllib.parse
            import urllib.request
            text = urllib.request.url2pathname(urllib.parse.urlparse(text).path)
        except Exception:
            return None
    return Path(text)


def _clipboard_file_paths_win32() -> list[Path]:
    """Read files copied in Windows Explorer from the clipboard."""
    if sys.platform != "win32":
        return []

    from ctypes import wintypes

    user32 = ctypes.windll.user32
    shell32 = ctypes.windll.shell32
    user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
    user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = wintypes.HANDLE
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = wintypes.BOOL
    shell32.DragQueryFileW.argtypes = [
        wintypes.HANDLE,
        wintypes.UINT,
        wintypes.LPWSTR,
        wintypes.UINT,
    ]
    shell32.DragQueryFileW.restype = wintypes.UINT

    if not user32.IsClipboardFormatAvailable(CF_HDROP):
        return []

    if not user32.OpenClipboard(None):
        return []
    try:
        hdrop = user32.GetClipboardData(CF_HDROP)
        if not hdrop:
            return []

        count = shell32.DragQueryFileW(hdrop, 0xFFFFFFFF, None, 0)
        paths = []
        for i in range(count):
            length = shell32.DragQueryFileW(hdrop, i, None, 0)
            if length <= 0:
                continue
            buf = ctypes.create_unicode_buffer(length + 1)
            shell32.DragQueryFileW(hdrop, i, buf, length + 1)
            paths.append(Path(buf.value))
        return paths
    finally:
        user32.CloseClipboard()


def _clipboard_image():
    """Return a PIL Image from clipboard, or None if no image is available."""
    try:
        from PIL import ImageGrab, Image
        result = ImageGrab.grabclipboard()
        if isinstance(result, Image.Image):
            return result
    except Exception:
        pass

    if sys.platform == "linux":
        for cmd in (
            ["xclip", "-selection", "clipboard", "-target", "image/png", "-o"],
            ["wl-paste", "--type", "image/png"],
        ):
            try:
                import io
                from PIL import Image
                r = subprocess.run(cmd, capture_output=True, timeout=3)
                if r.returncode == 0 and r.stdout:
                    return Image.open(io.BytesIO(r.stdout))
            except Exception:
                continue

    return None


def _paths_from_clipboard_text(text: str) -> list[Path]:
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return []

    paths: list[Path] = []
    for line in lines:
        path = _normalise_candidate_path(line)
        if path is None or not path.exists():
            return []
        if path.is_file() and path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            return []
        paths.append(path)
    return paths


class _FileRow(ctk.CTkFrame):
    """One row: badge + name+meta + status pill."""

    def __init__(self, parent, path: Path, on_select, on_open, **kwargs):
        super().__init__(parent, fg_color="transparent", corner_radius=6, **kwargs)
        self._path = path
        self._md_path: Path | None = None
        self._on_select = on_select
        self._on_open = on_open
        self._status = "queue"
        self._cost = 0.0
        self._selected = False

        ext = path.suffix.lower()
        badge_key = theme.EXT_TO_BADGE.get(ext, "TXT")
        bg, fg = theme.BADGE_COLORS.get(badge_key, (theme.PAPER_2, theme.INK_2))

        self.grid_columnconfigure(1, weight=1)

        self._badge = ctk.CTkLabel(
            self, text=badge_key,
            width=34, height=34,
            corner_radius=4,
            fg_color=bg, text_color=fg,
            font=theme.font(9, "bold", mono=True),
        )
        self._badge.grid(row=0, column=0, rowspan=2, padx=(8, 8), pady=6, sticky="w")

        self._name_lbl = ctk.CTkLabel(
            self, text=path.name,
            font=theme.font(12, "normal"),
            text_color=theme.INK,
            anchor="w",
        )
        self._name_lbl.grid(row=0, column=1, sticky="ew", pady=(8, 0))

        self._meta_lbl = ctk.CTkLabel(
            self, text=self._meta_text(),
            font=theme.font(10, mono=True),
            text_color=theme.INK_3,
            anchor="w",
        )
        self._meta_lbl.grid(row=1, column=1, sticky="ew", pady=(0, 8))

        self._status_lbl = ctk.CTkLabel(
            self, text="",
            corner_radius=10,
            font=theme.font(10, "bold"),
        )
        self._status_lbl.grid(row=0, column=2, rowspan=2, padx=(6, 8))
        self._render_status()

        for w in (self, self._badge, self._name_lbl, self._meta_lbl, self._status_lbl):
            w.bind("<Button-1>", self._handle_select)
            w.bind("<Double-Button-1>", self._handle_open)

    @property
    def path(self) -> Path:
        return self._path

    def _meta_text(self) -> str:
        bits = []
        try:
            bits.append(_format_size(self._path.stat().st_size))
        except Exception:
            pass
        ext = self._path.suffix.lower()
        if ext == ".pdf":
            pages = _count_pdf_pages(self._path)
            if pages is not None:
                bits.append(f"{pages} pag.")
        if self._cost > 0:
            bits.append(f"${self._cost:.4f}")
        return "  ·  ".join(bits)

    def _render_status(self):
        labels = {
            "queue": "in coda",
            "run":   "OCR…",
            "ok":    "✓ pronto",
            "warn":  "⚠ avviso",
            "err":   "✕ errore",
        }
        bg, border, fg = theme.STATUS_COLORS[self._status]
        self._status_lbl.configure(
            text=labels[self._status],
            fg_color=bg, text_color=fg,
            width=68 if self._status != "run" else 60,
            height=20,
        )

    def set_selected(self, selected: bool):
        self._selected = selected
        if selected:
            self.configure(fg_color=theme.CARD, border_width=1, border_color=theme.AMBER)
        else:
            self.configure(fg_color="transparent", border_width=0)

    def set_status(self, status: str):
        if status not in theme.STATUS_COLORS:
            status = "queue"
        self._status = status
        self._render_status()

    def set_cost(self, cost: float):
        self._cost = cost
        self._meta_lbl.configure(text=self._meta_text())

    def enable_copy(self, md_path: Path):
        self._md_path = md_path
        self.set_status("ok")

    def disable_copy(self):
        self._md_path = None

    @property
    def md_path(self) -> Path | None:
        return self._md_path

    def _handle_select(self, _e=None):
        self.focus_set()
        self._on_select(self._path)

    def _handle_open(self, _e=None):
        self._on_open(self._path)
        return "break"


class InputFrame(ctk.CTkFrame):
    """Sidebar: dropzone + actions + scrollable file list + footer counts."""

    def __init__(self, master, on_files_changed=None, on_selection_changed=None,
                 on_open_requested=None, on_import_whatsapp=None, **kwargs):
        super().__init__(master, fg_color=theme.PAPER, corner_radius=0,
                         border_width=0, **kwargs)
        self.on_files_changed = on_files_changed
        self.on_selection_changed = on_selection_changed
        self.on_open_requested = on_open_requested
        self.on_import_whatsapp = on_import_whatsapp

        self._file_paths: list[Path] = []
        self._rows: dict[Path, _FileRow] = {}
        self._selected_path: Path | None = None
        self._clipboard_paths: set[Path] = set()

        self.grid_rowconfigure(3, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # ── Header / dropzone ─────────────────────────────────────────────
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 6))
        theme.section_label(head, "Documenti").pack(anchor="w", pady=(0, 6))

        self.dropzone = ctk.CTkFrame(
            head, fg_color=theme.CARD,
            border_width=1, border_color=theme.RULE_STRONG,
            corner_radius=8, height=68,
        )
        self.dropzone.pack(fill="x")
        self.dropzone.pack_propagate(False)

        self.dropzone_title = ctk.CTkLabel(
            self.dropzone, text="Trascina o incolla i file qui",
            font=theme.font(12, "bold"), text_color=theme.INK,
        )
        self.dropzone_title.pack(pady=(12, 0))
        ctk.CTkLabel(
            self.dropzone,
            text="PDF · immagini · DOCX · audio · email · archivi · Ctrl+V",
            font=theme.font(10), text_color=theme.INK_3,
        ).pack(pady=(2, 12))

        # ── Action buttons ────────────────────────────────────────────────
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.grid(row=1, column=0, sticky="ew", padx=14, pady=(2, 8))

        self.add_files_btn = theme.ghost_button(
            btn_row, "Aggiungi file", command=self._select_files, height=30,
        )
        self.add_files_btn.pack(side="left", padx=(0, 5), fill="x", expand=True)

        self.add_folder_btn = theme.ghost_button(
            btn_row, "Cartella", command=self._select_folder, height=30,
        )
        self.add_folder_btn.pack(side="left", padx=(0, 5), fill="x", expand=True)

        self.paste_text_btn = theme.ghost_button(
            btn_row, "Appunti", command=self.paste_from_clipboard, height=30,
        )
        self.paste_text_btn.pack(side="left", fill="x", expand=True)

        # ── Importa da WhatsApp ───────────────────────────────────────────
        wa_row = ctk.CTkFrame(self, fg_color="transparent")
        wa_row.grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 8))
        self.wa_import_btn = theme.ghost_button(
            wa_row, "Importa da WhatsApp", command=self._import_whatsapp,
            height=30,
        )
        self.wa_import_btn.pack(fill="x", expand=True)

        # ── File list (scrollable) ────────────────────────────────────────
        list_wrap = ctk.CTkFrame(self, fg_color=theme.PAPER, corner_radius=0)
        list_wrap.grid(row=3, column=0, sticky="nsew", padx=8, pady=0)
        list_wrap.grid_rowconfigure(0, weight=1)
        list_wrap.grid_columnconfigure(0, weight=1)

        self.file_list = ctk.CTkScrollableFrame(
            list_wrap,
            fg_color=theme.PAPER,
            scrollbar_fg_color=theme.PAPER,
            scrollbar_button_color=theme.RULE,
            scrollbar_button_hover_color=theme.INK_3,
            corner_radius=0,
        )
        self.file_list.grid(row=0, column=0, sticky="nsew")
        theme.autohide_scrollable_frame(self.file_list)

        self._empty_lbl = ctk.CTkLabel(
            self.file_list,
            text="Nessun documento.\nTrascina qui i file o usa i pulsanti.",
            font=theme.font(11), text_color=theme.INK_4, justify="center",
        )
        self._empty_lbl.pack(pady=40)

        # ── Footer ────────────────────────────────────────────────────────
        footer = ctk.CTkFrame(self, fg_color=theme.PAPER, corner_radius=0,
                              height=64)
        footer.grid(row=4, column=0, sticky="ew")
        theme.hairline(footer).pack(fill="x", side="top")

        inner = ctk.CTkFrame(footer, fg_color="transparent")
        inner.pack(fill="x", padx=14, pady=10)

        self.count_label = ctk.CTkLabel(
            inner, text="Nessun documento selezionato",
            font=theme.font(11, mono=True), text_color=theme.INK_3, anchor="w",
        )
        self.count_label.pack(side="left", fill="x", expand=True)

        self.clear_btn = theme.ghost_button(
            inner, "Svuota lista", command=self._clear_files, width=110, height=26,
        )
        self.clear_btn.pack(side="right")

    # ─── Selection helpers ────────────────────────────────────────────────
    def _import_whatsapp(self):
        if callable(self.on_import_whatsapp):
            self.on_import_whatsapp()

    def _select_files(self):
        paths = filedialog.askopenfilenames(
            title="Seleziona documenti",
            filetypes=[
                ("Documenti supportati", "*.pdf *.txt *.eml *.msg *.docx *.html *.htm *.md *.rtf *.jpg *.jpeg *.png *.webp *.tiff *.tif *.bmp *.gif *.mp3 *.wav *.flac *.m4a *.ogg *.mp4 *.opus *.p7m *.zip *.7z *.tar *.tgz *.wachat"),
                ("PDF", "*.pdf"),
                ("Immagini", "*.jpg *.jpeg *.png *.webp *.tiff *.tif *.bmp *.gif"),
                ("Testo ed Email", "*.txt *.eml *.msg *.md *.html *.htm *.rtf"),
                ("Office/RTF", "*.docx *.rtf"),
                ("Audio / Video", "*.mp3 *.wav *.flac *.m4a *.ogg *.mp4 *.opus"),
                ("Firmati e Archivi", "*.p7m *.zip *.7z *.tar *.tgz"),
                ("WhatsApp", "*.wachat"),
                ("Tutti i file", "*.*"),
            ],
        )
        if paths:
            for p in paths:
                path = Path(p)
                # Coerente con add_paths/clipboard: il filtro "Tutti i file" non
                # deve far entrare estensioni non supportate (fallirebbero a valle).
                if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                    continue
                if path not in self._file_paths:
                    self._file_paths.append(path)
            self._refresh_list()

    def _select_folder(self):
        folder = filedialog.askdirectory(title="Seleziona cartella")
        if folder:
            folder_path = Path(folder)
            candidates = []
            for ext in SUPPORTED_EXTENSIONS:
                candidates.extend(folder_path.glob(f"*{ext}"))
            for f in sorted(candidates):
                if f not in self._file_paths:
                    self._file_paths.append(f)
            self._refresh_list()

    def _clear_files(self):
        self._file_paths.clear()
        self._refresh_list()

    def _refresh_list(self):
        for w in self.file_list.winfo_children():
            w.destroy()
        self._rows.clear()

        if not self._file_paths:
            self._empty_lbl = ctk.CTkLabel(
                self.file_list,
                text="Nessun documento.\nTrascina qui i file, incolla con Ctrl+V o usa i pulsanti.",
                font=theme.font(11), text_color=theme.INK_4, justify="center",
            )
            self._empty_lbl.pack(pady=40)
        else:
            for path in self._file_paths:
                row = _FileRow(self.file_list, path,
                               on_select=self.select_path,
                               on_open=self._open_path)
                row.pack(fill="x", padx=2, pady=1)
                self._rows[path] = row
                row.set_selected(path == self._selected_path)

        if self._selected_path not in self._file_paths:
            self._selected_path = None

        n = len(self._file_paths)
        if n == 0:
            self.count_label.configure(text="Nessun documento selezionato")
        elif n == 1:
            self.count_label.configure(text="1 documento")
        else:
            self.count_label.configure(text=f"{n} documenti")

        if self.on_files_changed:
            self.on_files_changed(self._file_paths)

    def paste_from_clipboard(self) -> bool:
        paths = _clipboard_file_paths_win32()
        text = ""
        if not paths:
            try:
                text = self.master.clipboard_get()
                paths = _paths_from_clipboard_text(text)
            except Exception:
                text = ""

        if paths:
            before = len(self._file_paths)
            self.add_paths(paths)
            if len(self._file_paths) > before:
                self.select_path(self._file_paths[-1])
            return True

        img = _clipboard_image()
        if img is not None:
            return self._paste_image(img)

        return self._paste_text(text)

    def _paste_image(self, img) -> bool:
        try:
            ts = time.strftime("%Y%m%d_%H%M%S")
            tfile = app_capture_dir() / f"Appunti_{ts}.png"
            img.save(str(tfile), "PNG")
            if tfile not in self._file_paths:
                self._file_paths.append(tfile)
                self._clipboard_paths.add(tfile)
            self._refresh_list()
            self.select_path(tfile)
            return True
        except Exception:
            return False

    def _paste_text(self, text: str | None = None) -> bool:
        try:
            if text is None:
                text = self.master.clipboard_get()
            if not text or not text.strip():
                return False
            ts = time.strftime("%Y%m%d_%H%M%S")
            tfile = app_capture_dir() / f"Appunti_{ts}.txt"
            tfile.write_text(text, encoding="utf-8")
            if tfile not in self._file_paths:
                self._file_paths.append(tfile)
                self._clipboard_paths.add(tfile)
            self._refresh_list()
            self.select_path(tfile)
            return True
        except Exception:
            return False

    # ─── Public API (kept compatible) ─────────────────────────────────────
    def get_file_paths(self) -> list[Path]:
        return list(self._file_paths)

    def get_selected_path(self) -> Path | None:
        return self._selected_path

    def add_paths(self, paths: list[Path]):
        for path in paths:
            path = Path(path)
            if path.is_dir():
                cands = []
                for ext in SUPPORTED_EXTENSIONS:
                    cands.extend(path.glob(f"*{ext}"))
                for c in sorted(cands):
                    if c not in self._file_paths:
                        self._file_paths.append(c)
                continue
            if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            if path not in self._file_paths:
                self._file_paths.append(path)
        self._refresh_list()
        if paths and self._selected_path is None and self._file_paths:
            self.select_path(self._file_paths[-1])

    def set_enabled(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        for b in (self.add_files_btn, self.add_folder_btn,
                  self.paste_text_btn, self.wa_import_btn, self.clear_btn):
            b.configure(state=state)

    def set_md_for_file(self, input_path: Path, md_path: Path):
        row = self._rows.get(input_path)
        if row:
            row.enable_copy(md_path)

    def set_status_for_file(self, input_path: Path, status: str):
        input_path = Path(input_path)
        row = self._rows.get(input_path)
        if row is None:
            try:
                resolved = input_path.resolve()
            except OSError:
                resolved = input_path
            for path, candidate in self._rows.items():
                try:
                    if path.resolve() == resolved:
                        candidate.set_status(status)
                        return
                except OSError:
                    if path == input_path:
                        candidate.set_status(status)
                        return
            return
        row.set_status(status)

    def set_cost_for_file(self, input_path: Path, cost: float):
        row = self._rows.get(input_path)
        if row:
            row.set_cost(cost)

    def replace_path(self, old: Path, new: Path):
        old, new = Path(old), Path(new)
        try:
            i = self._file_paths.index(old)
        except ValueError:
            return
        self._file_paths[i] = new
        if old in self._clipboard_paths:
            self._clipboard_paths.remove(old)
            self._clipboard_paths.add(new)
        was_sel = self._selected_path == old
        if was_sel:
            self._selected_path = new
        self._refresh_list()
        if was_sel:
            self.select_path(new)

    def reset_copy_buttons(self):
        for row in self._rows.values():
            row.disable_copy()
            row.set_status("queue")
            row.set_cost(0.0)

    def select_path(self, path: Path | None):
        if path is not None and path not in self._file_paths:
            return
        self._selected_path = path
        for p, row in self._rows.items():
            row.set_selected(p == path)
        if self.on_selection_changed:
            self.on_selection_changed(path)

    def remove_selected(self):
        if not self._selected_path:
            return
        p = self._selected_path
        if p in self._file_paths:
            self._file_paths.remove(p)
        self._clipboard_paths.discard(p)
        self._selected_path = None
        self._refresh_list()
        if self.on_selection_changed:
            self.on_selection_changed(None)

    def is_clipboard_path(self, path: Path) -> bool:
        if path in self._clipboard_paths:
            return True
        temp_root = Path(tempfile.gettempdir()) / "OCR_LangExtract"
        try:
            return path.parent == temp_root and path.name.startswith("Appunti_")
        except Exception:
            return False

    def handle_delete_key(self, _e=None):
        self.remove_selected()
        return "break"

    def get_rows(self):
        """Return [(path, status, cost), ...] in display order — used by cost chart."""
        out = []
        for p in self._file_paths:
            row = self._rows.get(p)
            if row:
                out.append((p, row._status, row._cost))
            else:
                out.append((p, "queue", 0.0))
        return out

    def _open_path(self, path: Path):
        self.select_path(path)
        if self.on_open_requested:
            self.on_open_requested(path, self.is_clipboard_path(path))
            return
        self._open_with_default_app(path)

    @staticmethod
    def _open_with_default_app(path: Path):
        if not path.exists():
            return
        if sys.platform == "win32":
            import os
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
