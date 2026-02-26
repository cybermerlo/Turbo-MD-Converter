"""File/folder selection frame."""

from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk


class InputFrame(ctk.CTkFrame):
    """File selection panel with list of selected PDFs."""

    def __init__(self, master, on_files_changed: callable = None, **kwargs):
        super().__init__(master, **kwargs)
        self.on_files_changed = on_files_changed
        self._pdf_paths: list[Path] = []

        # Title
        self.title_label = ctk.CTkLabel(
            self, text="Documenti PDF",
            font=ctk.CTkFont(size=14, weight="bold"),
        )
        self.title_label.pack(padx=10, pady=(10, 5), anchor="w")

        # Buttons frame
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(padx=10, pady=5, fill="x")

        self.add_files_btn = ctk.CTkButton(
            btn_frame, text="Aggiungi PDF",
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
        """Open file dialog to select PDF files."""
        paths = filedialog.askopenfilenames(
            title="Seleziona file PDF",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if paths:
            for p in paths:
                path = Path(p)
                if path not in self._pdf_paths:
                    self._pdf_paths.append(path)
            self._refresh_list()

    def _select_folder(self) -> None:
        """Open folder dialog and add all PDFs in it."""
        folder = filedialog.askdirectory(title="Seleziona cartella con PDF")
        if folder:
            folder_path = Path(folder)
            for pdf in sorted(folder_path.glob("*.pdf")):
                if pdf not in self._pdf_paths:
                    self._pdf_paths.append(pdf)
            self._refresh_list()

    def _clear_files(self) -> None:
        """Remove all selected files."""
        self._pdf_paths.clear()
        self._refresh_list()

    def _refresh_list(self) -> None:
        """Update the displayed file list."""
        self.file_list.configure(state="normal")
        self.file_list.delete("1.0", "end")
        for i, path in enumerate(self._pdf_paths):
            self.file_list.insert("end", f"{i + 1}. {path.name}\n")
        self.file_list.configure(state="disabled")

        self.count_label.configure(text=f"{len(self._pdf_paths)} file selezionati")

        if self.on_files_changed:
            self.on_files_changed(self._pdf_paths)

    def get_pdf_paths(self) -> list[Path]:
        """Return currently selected PDF paths."""
        return list(self._pdf_paths)

    def set_enabled(self, enabled: bool) -> None:
        """Enable/disable file selection buttons."""
        state = "normal" if enabled else "disabled"
        self.add_files_btn.configure(state=state)
        self.add_folder_btn.configure(state=state)
        self.clear_btn.configure(state=state)
