"""Output format selection and results preview frame."""

import subprocess
import sys
from pathlib import Path

import customtkinter as ctk


class OutputFrame(ctk.CTkFrame):
    """Output options and results preview with tabs."""

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)

        # Results preview
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(padx=10, pady=(10, 5), fill="both", expand=True)

        self.tab_md = self.tabview.add("Markdown")

        self.md_textbox = ctk.CTkTextbox(
            self.tab_md, font=ctk.CTkFont(family="Consolas", size=12),
        )
        self.md_textbox.pack(fill="both", expand=True)
        self.md_textbox.configure(state="disabled")

        # Open output folder button
        self.open_folder_btn = ctk.CTkButton(
            self, text="Apri Cartella Output",
            command=self._open_output_folder,
            state="disabled",
        )
        self.open_folder_btn.pack(padx=10, pady=(0, 10))

        self._output_dir: Path | None = None

    def get_output_formats(self) -> list[str]:
        """Return selected output format names."""
        return ["markdown"]

    def show_markdown(self, content: str) -> None:
        """Display markdown content in the preview tab."""
        self.md_textbox.configure(state="normal")
        self.md_textbox.delete("1.0", "end")
        self.md_textbox.insert("1.0", content)
        self.md_textbox.configure(state="disabled")
        self.tabview.set("Markdown")

    def show_json(self, content: str) -> None:
        """No-op: JSON output is no longer supported."""
        pass

    def set_output_dir(self, path: Path) -> None:
        """Set the output directory for the open folder button."""
        self._output_dir = path
        self.open_folder_btn.configure(state="normal")

    def _open_output_folder(self) -> None:
        """Open the output directory in the system file explorer."""
        if self._output_dir and self._output_dir.exists():
            if sys.platform == "win32":
                subprocess.Popen(["explorer", str(self._output_dir)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(self._output_dir)])
            else:
                subprocess.Popen(["xdg-open", str(self._output_dir)])

    def clear(self) -> None:
        """Clear preview content."""
        self.md_textbox.configure(state="normal")
        self.md_textbox.delete("1.0", "end")
        self.md_textbox.configure(state="disabled")

    def set_enabled(self, enabled: bool) -> None:
        """Enable/disable controls (no-op, kept for API compatibility)."""
        pass
