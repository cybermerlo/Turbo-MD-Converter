"""Output preview frame."""

import subprocess
import sys
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk


class OutputFrame(ctk.CTkFrame):
    """Results preview with output actions."""

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)

        # ── Preview tab ───────────────────────────────────────────────────────
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(padx=10, pady=(10, 4), fill="both", expand=True)

        self.tab_md = self.tabview.add("Anteprima Markdown")

        self.md_textbox = ctk.CTkTextbox(
            self.tab_md,
            font=ctk.CTkFont(family="Consolas", size=11),
        )
        self.md_textbox.pack(fill="both", expand=True)
        self.md_textbox.configure(state="disabled")

        # ── Action buttons row ────────────────────────────────────────────────
        action_row = ctk.CTkFrame(self, fg_color="transparent")
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

        self._output_dir: Path | None = None
        self._all_md_paths: list[Path] = []

    # ─── Public API ──────────────────────────────────────────────────────────

    def get_output_formats(self) -> list[str]:
        return ["markdown"]

    def show_markdown(self, content: str) -> None:
        self.md_textbox.configure(state="normal")
        self.md_textbox.delete("1.0", "end")
        self.md_textbox.insert("1.0", content)
        self.md_textbox.configure(state="disabled")
        self.tabview.set("Anteprima Markdown")

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

    def clear(self) -> None:
        self.md_textbox.configure(state="normal")
        self.md_textbox.delete("1.0", "end")
        self.md_textbox.configure(state="disabled")
        self._all_md_paths = []
        self.copy_all_btn.configure(state="disabled")
        self.export_all_btn.configure(state="disabled")

    def set_enabled(self, enabled: bool) -> None:
        pass  # kept for API compatibility

    # ─── Internal ────────────────────────────────────────────────────────────

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
