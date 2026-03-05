"""Output format selection and results preview frame."""

import subprocess
import sys
from pathlib import Path

import customtkinter as ctk


class OutputFrame(ctk.CTkFrame):
    """Output options and results preview with tabs."""

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)

        # Output format selection
        format_frame = ctk.CTkFrame(self, fg_color="transparent")
        format_frame.pack(padx=10, pady=(10, 5), fill="x")

        ctk.CTkLabel(
            format_frame, text="Formato output:",
            font=ctk.CTkFont(weight="bold"),
        ).pack(side="left", padx=(0, 10))

        self.md_var = ctk.BooleanVar(value=True)
        self.md_check = ctk.CTkCheckBox(
            format_frame, text="Markdown", variable=self.md_var,
        )
        self.md_check.pack(side="left", padx=(0, 10))

        self.json_var = ctk.BooleanVar(value=False)
        self.json_check = ctk.CTkCheckBox(
            format_frame, text="JSON", variable=self.json_var,
        )
        self.json_check.pack(side="left")

        # Results preview tabview
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(padx=10, pady=5, fill="both", expand=True)

        self.tab_md = self.tabview.add("Markdown")
        self.tab_json = self.tabview.add("JSON")

        self.md_textbox = ctk.CTkTextbox(
            self.tab_md, font=ctk.CTkFont(family="Consolas", size=12),
        )
        self.md_textbox.pack(fill="both", expand=True)
        self.md_textbox.configure(state="disabled")

        self.json_textbox = ctk.CTkTextbox(
            self.tab_json, font=ctk.CTkFont(family="Consolas", size=12),
        )
        self.json_textbox.pack(fill="both", expand=True)
        self.json_textbox.configure(state="disabled")

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
        formats = []
        if self.md_var.get():
            formats.append("markdown")
        if self.json_var.get():
            formats.append("json")
        return formats

    def show_markdown(self, content: str) -> None:
        """Display markdown content in the preview tab."""
        self.md_textbox.configure(state="normal")
        self.md_textbox.delete("1.0", "end")
        self.md_textbox.insert("1.0", content)
        self.md_textbox.configure(state="disabled")
        self.tabview.set("Markdown")

    def show_json(self, content: str) -> None:
        """Display JSON content in the preview tab."""
        self.json_textbox.configure(state="normal")
        self.json_textbox.delete("1.0", "end")
        self.json_textbox.insert("1.0", content)
        self.json_textbox.configure(state="disabled")

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
        self.json_textbox.configure(state="normal")
        self.json_textbox.delete("1.0", "end")
        self.json_textbox.configure(state="disabled")

    def set_enabled(self, enabled: bool) -> None:
        """Enable/disable format checkboxes."""
        state = "normal" if enabled else "disabled"
        self.md_check.configure(state=state)
        self.json_check.configure(state=state)
