"""File/folder selection frame."""

from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

SUPPORTED_EXTENSIONS = (
    ".pdf", ".txt", ".eml", ".msg", ".docx", ".html", ".htm", ".md", ".rtf",
    ".jpg", ".jpeg", ".png", ".webp", ".tiff", ".tif", ".bmp", ".gif",
    ".mp3", ".wav", ".flac", ".m4a", ".ogg", ".mp4",
    ".p7m", ".zip", ".7z", ".tar", ".tgz",
)

_EXT_ICON = {
    ".pdf": "PDF",
    ".txt": "TXT",
    ".eml": "EML",
    ".msg": "MSG",
    ".docx": "DOCX",
    ".html": "HTML",
    ".htm": "HTML",
    ".md": "MD",
    ".rtf": "RTF",
    ".jpg": "IMG",
    ".jpeg": "IMG",
    ".png": "IMG",
    ".webp": "IMG",
    ".tiff": "IMG",
    ".tif": "IMG",
    ".bmp": "IMG",
    ".gif": "IMG",
    ".mp3": "AUD",
    ".wav": "AUD",
    ".flac": "AUD",
    ".m4a": "AUD",
    ".ogg": "AUD",
    ".mp4": "MP4",
    ".p7m": "P7M",
    ".zip": "ZIP",
    ".7z":  "7Z",
    ".tar": "TAR",
    ".tgz": "TAR",
}


class _FileRow(ctk.CTkFrame):
    """Single row in the file list: badge + name + optional copy button."""

    def __init__(self, parent: ctk.CTkScrollableFrame, path: Path):
        super().__init__(parent, fg_color="transparent", corner_radius=0)
        self.pack(fill="x", padx=2, pady=1)

        self._path = path
        self._md_path: Path | None = None

        tag = _EXT_ICON.get(path.suffix.lower(), "???")

        # Copy button (right side, hidden until MD is ready)
        self._copy_btn = ctk.CTkButton(
            self,
            text="⎘",
            width=26,
            height=20,
            font=ctk.CTkFont(size=12),
            fg_color="transparent",
            border_width=1,
            border_color="gray40",
            hover_color=("gray80", "gray30"),
            state="disabled",
            command=self._copy_to_clipboard,
        )
        self._copy_btn.pack(side="right", padx=(4, 2), pady=2)

        # File label
        ctk.CTkLabel(
            self,
            text=f"[{tag}]  {path.name}",
            font=ctk.CTkFont(family="Consolas", size=11),
            anchor="w",
        ).pack(side="left", fill="x", expand=True, padx=(4, 0), pady=2)

    def enable_copy(self, md_path: Path) -> None:
        self._md_path = md_path
        self._copy_btn.configure(
            state="normal",
            border_color=("gray50", "gray60"),
        )

    def disable_copy(self) -> None:
        self._md_path = None
        self._copy_btn.configure(state="disabled", border_color="gray40")

    def _copy_to_clipboard(self) -> None:
        if not self._md_path or not self._md_path.exists():
            return
        try:
            content = self._md_path.read_text(encoding="utf-8")
            root = self.winfo_toplevel()
            root.clipboard_clear()
            root.clipboard_append(content)
        except Exception:
            pass


class InputFrame(ctk.CTkFrame):
    """File selection panel with list of selected documents."""

    def __init__(self, master, on_files_changed: callable = None, **kwargs):
        super().__init__(master, **kwargs)
        self.on_files_changed = on_files_changed
        self._file_paths: list[Path] = []
        self._rows: dict[Path, _FileRow] = {}

        # ── Header ───────────────────────────────────────────────────────────
        ctk.CTkLabel(
            self,
            text="DOCUMENTI",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color="gray60",
        ).pack(padx=12, pady=(10, 2), anchor="w")

        ctk.CTkLabel(
            self,
            text="Trascina qui i file, oppure usa i pulsanti",
            font=ctk.CTkFont(size=11),
            text_color="gray50",
        ).pack(padx=12, pady=(0, 6), anchor="w")

        # ── Buttons ──────────────────────────────────────────────────────────
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(padx=12, pady=(0, 6), fill="x")

        self.add_files_btn = ctk.CTkButton(
            btn_row, text="Aggiungi file",
            command=self._select_files, width=110,
        )
        self.add_files_btn.pack(side="left", padx=(0, 5))

        self.add_folder_btn = ctk.CTkButton(
            btn_row, text="Cartella…",
            command=self._select_folder, width=90,
        )
        self.add_folder_btn.pack(side="left", padx=(0, 5))

        self.paste_text_btn = ctk.CTkButton(
            btn_row, text="Incolla Appunti",
            command=self._paste_text, width=110,
        )
        self.paste_text_btn.pack(side="left", padx=(0, 5))

        self.clear_btn = ctk.CTkButton(
            btn_row, text="Svuota",
            command=self._clear_files, width=70,
            fg_color="transparent",
            border_width=1,
        )
        self.clear_btn.pack(side="right")

        # ── File list (scrollable rows) ───────────────────────────────────────
        self.file_list = ctk.CTkScrollableFrame(
            self,
            fg_color=("gray92", "gray14"),
            corner_radius=6,
            scrollbar_button_color=("gray70", "gray35"),
        )
        self.file_list.pack(padx=12, pady=(0, 4), fill="both", expand=True)

        # ── Count ─────────────────────────────────────────────────────────────
        self.count_label = ctk.CTkLabel(
            self, text="Nessun documento selezionato",
            font=ctk.CTkFont(size=11),
            text_color="gray50",
        )
        self.count_label.pack(padx=12, pady=(0, 8), anchor="w")

    # ─── File selection ───────────────────────────────────────────────────────

    def _select_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Seleziona documenti",
            filetypes=[
                ("Documenti supportati", "*.pdf *.txt *.eml *.msg *.docx *.html *.htm *.md *.rtf *.jpg *.jpeg *.png *.webp *.tiff *.tif *.bmp *.gif *.mp3 *.wav *.flac *.m4a *.ogg *.mp4 *.p7m *.zip *.7z *.tar *.tgz"),
                ("PDF", "*.pdf"),
                ("Immagini", "*.jpg *.jpeg *.png *.webp *.tiff *.tif *.bmp *.gif"),
                ("Testo ed Email", "*.txt *.eml *.msg *.md *.html *.htm *.rtf"),
                ("Office/RTF", "*.docx *.rtf"),
                ("Audio / Video", "*.mp3 *.wav *.flac *.m4a *.ogg *.mp4"),
                ("Firmati e Archivi", "*.p7m *.zip *.7z *.tar *.tgz"),
                ("Tutti i file", "*.*"),
            ],
        )
        if paths:
            for p in paths:
                path = Path(p)
                if path not in self._file_paths:
                    self._file_paths.append(path)
            self._refresh_list()

    def _select_folder(self) -> None:
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

    def _clear_files(self) -> None:
        self._file_paths.clear()
        self._refresh_list()

    def _refresh_list(self) -> None:
        # Destroy all existing row widgets
        for widget in self.file_list.winfo_children():
            widget.destroy()
        self._rows.clear()

        for path in self._file_paths:
            row = _FileRow(self.file_list, path)
            self._rows[path] = row

        n = len(self._file_paths)
        if n == 0:
            self.count_label.configure(text="Nessun documento selezionato")
        elif n == 1:
            self.count_label.configure(text="1 documento selezionato")
        else:
            self.count_label.configure(text=f"{n} documenti selezionati")

        if self.on_files_changed:
            self.on_files_changed(self._file_paths)

    def _paste_text(self) -> None:
        """Legge il testo dagli appunti e crea un file di testo temporaneo."""
        try:
            clipboard_text = self.master.clipboard_get()
            if not clipboard_text or not clipboard_text.strip():
                return

            import time
            import tempfile

            timestamp = time.strftime("%Y%m%d_%H%M%S")
            temp_dir = Path(tempfile.gettempdir()) / "OCR_LangExtract"
            temp_dir.mkdir(exist_ok=True, parents=True)

            temp_file = temp_dir / f"Appunti_{timestamp}.txt"
            temp_file.write_text(clipboard_text, encoding="utf-8")

            if temp_file not in self._file_paths:
                self._file_paths.append(temp_file)
            self._refresh_list()

        except Exception:
            pass

    # ─── Public API ──────────────────────────────────────────────────────────

    def get_file_paths(self) -> list[Path]:
        return list(self._file_paths)

    def get_pdf_paths(self) -> list[Path]:
        """Alias for backward compatibility."""
        return self.get_file_paths()

    def add_paths(self, paths: list[Path]) -> None:
        """Add file paths (e.g. from drag & drop). Skips unsupported formats and duplicates."""
        for path in paths:
            path = Path(path)
            if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            if path not in self._file_paths:
                self._file_paths.append(path)
        self._refresh_list()

    def set_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self.add_files_btn.configure(state=state)
        self.add_folder_btn.configure(state=state)
        self.paste_text_btn.configure(state=state)
        self.clear_btn.configure(state=state)

    def set_md_for_file(self, input_path: Path, md_path: Path) -> None:
        """Enable the copy button for a specific input file after conversion."""
        row = self._rows.get(input_path)
        if row:
            row.enable_copy(md_path)

    def reset_copy_buttons(self) -> None:
        """Disable all per-file copy buttons (call at start of a new batch)."""
        for row in self._rows.values():
            row.disable_copy()
