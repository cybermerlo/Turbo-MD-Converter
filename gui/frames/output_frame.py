"""Output preview frame."""

import subprocess
import sys
from pathlib import Path

import customtkinter as ctk


class OutputFrame(ctk.CTkFrame):
    """Results preview with an 'open folder' shortcut."""

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

        # ── Open folder button ────────────────────────────────────────────────
        self.open_folder_btn = ctk.CTkButton(
            self,
            text="Apri cartella di output",
            command=self._open_output_folder,
            state="disabled",
            width=180,
        )
        self.open_folder_btn.pack(pady=(0, 8))

        self._output_dir: Path | None = None

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

    def clear(self) -> None:
        self.md_textbox.configure(state="normal")
        self.md_textbox.delete("1.0", "end")
        self.md_textbox.configure(state="disabled")

    def set_enabled(self, enabled: bool) -> None:
        pass  # kept for API compatibility

    # ─── Internal ────────────────────────────────────────────────────────────

    def _open_output_folder(self) -> None:
        if self._output_dir and self._output_dir.exists():
            if sys.platform == "win32":
                subprocess.Popen(["explorer", str(self._output_dir)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(self._output_dir)])
            else:
                subprocess.Popen(["xdg-open", str(self._output_dir)])
