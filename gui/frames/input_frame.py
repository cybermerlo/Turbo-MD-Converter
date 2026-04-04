"""File/folder selection frame."""

from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

SUPPORTED_EXTENSIONS = (
    ".pdf", ".txt", ".eml", ".msg", ".docx", ".html", ".htm", ".md", ".rtf",
    ".jpg", ".jpeg", ".png", ".webp", ".tiff", ".tif", ".bmp", ".gif",
    ".mp3", ".wav", ".flac", ".m4a", ".ogg",
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
}


class InputFrame(ctk.CTkFrame):
    """File selection panel with list of selected documents."""

    def __init__(self, master, on_files_changed: callable = None, **kwargs):
        super().__init__(master, **kwargs)
        self.on_files_changed = on_files_changed
        self._file_paths: list[Path] = []

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

        # ── File list ─────────────────────────────────────────────────────────
        self.file_list = ctk.CTkTextbox(
            self,
            font=ctk.CTkFont(family="Consolas", size=11),
        )
        self.file_list.pack(padx=12, pady=(0, 4), fill="both", expand=True)
        self.file_list.configure(state="disabled")

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
                ("Documenti supportati", "*.pdf *.txt *.eml *.msg *.docx *.html *.htm *.md *.rtf *.jpg *.jpeg *.png *.webp *.tiff *.tif *.bmp *.gif *.mp3 *.wav *.flac *.m4a *.ogg"),
                ("PDF", "*.pdf"),
                ("Immagini", "*.jpg *.jpeg *.png *.webp *.tiff *.tif *.bmp *.gif"),
                ("Testo ed Email", "*.txt *.eml *.msg *.md *.html *.htm *.rtf"),
                ("Office/RTF", "*.docx *.rtf"),
                ("Audio", "*.mp3 *.wav *.flac *.m4a *.ogg"),
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
        self.file_list.configure(state="normal")
        self.file_list.delete("1.0", "end")
        for i, path in enumerate(self._file_paths):
            tag = _EXT_ICON.get(path.suffix.lower(), "???")
            self.file_list.insert("end", f"[{tag}]  {path.name}\n")
        self.file_list.configure(state="disabled")

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
            
            # Crea un file temporaneo con il testo
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            temp_dir = Path(tempfile.gettempdir()) / "OCR_LangExtract"
            temp_dir.mkdir(exist_ok=True, parents=True)
            
            temp_file = temp_dir / f"Appunti_{timestamp}.txt"
            temp_file.write_text(clipboard_text, encoding="utf-8")
            
            if temp_file not in self._file_paths:
                self._file_paths.append(temp_file)
            self._refresh_list()
            
        except Exception:
            # Nessun testo negli appunti o errore lettura
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
