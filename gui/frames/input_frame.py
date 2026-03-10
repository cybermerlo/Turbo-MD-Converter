"""File/folder selection frame."""

from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

SUPPORTED_EXTENSIONS = (".pdf", ".txt", ".eml")


class InputFrame(ctk.CTkFrame):
    """File selection panel with list of selected documents."""

    def __init__(self, master, on_files_changed: callable = None, **kwargs):
        super().__init__(master, **kwargs)
        self.on_files_changed = on_files_changed
        self._file_paths: list[Path] = []

        # Title
        self.title_label = ctk.CTkLabel(
            self, text="Documenti",
            font=ctk.CTkFont(size=14, weight="bold"),
        )
        self.title_label.pack(padx=10, pady=(10, 5), anchor="w")
        ctk.CTkLabel(
            self, text="Trascina qui i file PDF, TXT o EML o usa i pulsanti sotto",
            font=ctk.CTkFont(size=11),
            text_color="gray",
        ).pack(padx=10, pady=(0, 5), anchor="w")

        # Buttons frame
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(padx=10, pady=5, fill="x")

        self.add_files_btn = ctk.CTkButton(
            btn_frame, text="Aggiungi File",
            command=self._select_files, width=120,
        )
        self.add_files_btn.pack(side="left", padx=(0, 5))

        self.add_folder_btn = ctk.CTkButton(
            btn_frame, text="Aggiungi Cartella",
            command=self._select_folder, width=130,
        )
        self.add_folder_btn.pack(side="left", padx=(0, 5))

        self.clear_btn = ctk.CTkButton(
            btn_frame, text="Pulisci",
            command=self._clear_files, width=80,
            fg_color="gray40", hover_color="gray30",
        )
        self.clear_btn.pack(side="right")

        # File list
        self.file_list = ctk.CTkTextbox(self, height=120, font=ctk.CTkFont(size=12))
        self.file_list.pack(padx=10, pady=5, fill="both", expand=True)
        self.file_list.configure(state="disabled")

        # Count label
        self.count_label = ctk.CTkLabel(self, text="0 file selezionati")
        self.count_label.pack(padx=10, pady=(0, 5), anchor="w")

    def _select_files(self) -> None:
        """Open file dialog to select PDF, TXT or EML files."""
        paths = filedialog.askopenfilenames(
            title="Seleziona file",
            filetypes=[
                ("Documenti supportati", "*.pdf *.txt *.eml"),
                ("PDF files", "*.pdf"),
                ("Text files", "*.txt"),
                ("Email files", "*.eml"),
                ("All files", "*.*"),
            ],
        )
        if paths:
            for p in paths:
                path = Path(p)
                if path not in self._file_paths:
                    self._file_paths.append(path)
            self._refresh_list()

    def _select_folder(self) -> None:
        """Open folder dialog and add all supported files in it."""
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
        """Remove all selected files."""
        self._file_paths.clear()
        self._refresh_list()

    def _refresh_list(self) -> None:
        """Update the displayed file list."""
        self.file_list.configure(state="normal")
        self.file_list.delete("1.0", "end")
        for i, path in enumerate(self._file_paths):
            self.file_list.insert("end", f"{i + 1}. {path.name}\n")
        self.file_list.configure(state="disabled")

        self.count_label.configure(text=f"{len(self._file_paths)} file selezionati")

        if self.on_files_changed:
            self.on_files_changed(self._file_paths)

    def get_file_paths(self) -> list[Path]:
        """Return currently selected file paths."""
        return list(self._file_paths)

    # Keep backward-compatible alias
    def get_pdf_paths(self) -> list[Path]:
        """Alias for get_file_paths() for backward compatibility."""
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
        """Enable/disable file selection buttons."""
        state = "normal" if enabled else "disabled"
        self.add_files_btn.configure(state=state)
        self.add_folder_btn.configure(state=state)
        self.clear_btn.configure(state=state)
