"""File/folder selection frame."""

from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

SUPPORTED_EXTENSIONS = (".pdf", ".txt", ".eml", ".msg")

_EXT_ICON = {
    ".pdf": "PDF",
    ".txt": "TXT",
    ".eml": "EML",
    ".msg": "MSG",
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
                ("Documenti supportati", "*.pdf *.txt *.eml *.msg"),
                ("PDF", "*.pdf"),
                ("Testo", "*.txt"),
                ("Email", "*.eml *.msg"),
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
        self.clear_btn.configure(state=state)
