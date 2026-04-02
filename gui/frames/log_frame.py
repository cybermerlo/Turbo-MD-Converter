"""Real-time log display frame."""

from datetime import datetime

import customtkinter as ctk


class LogFrame(ctk.CTkFrame):
    """Scrollable log area showing timestamped messages."""

    _LEVEL_COLORS = {
        "ERROR":   "#e05555",
        "WARNING": "#e09555",
        "INFO":    None,   # default text color
    }

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)

        # Header row: label + clear button
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(padx=10, pady=(6, 0), fill="x")

        ctk.CTkLabel(
            header,
            text="LOG",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color="gray60",
        ).pack(side="left")

        ctk.CTkButton(
            header,
            text="Pulisci",
            width=60,
            height=22,
            font=ctk.CTkFont(size=11),
            fg_color="transparent",
            border_width=1,
            command=self.clear,
        ).pack(side="right")

        self.textbox = ctk.CTkTextbox(
            self,
            height=160,
            font=ctk.CTkFont(family="Consolas", size=11),
        )
        self.textbox.pack(padx=10, pady=(4, 8), fill="both", expand=True)
        self.textbox.configure(state="disabled")

        # Configure colour tags
        self.textbox.tag_config("error",   foreground="#e05555")
        self.textbox.tag_config("warning", foreground="#e09555")

    def append(self, message: str, level: str = "INFO") -> None:
        """Add a timestamped log entry."""
        ts = datetime.now().strftime("%H:%M:%S")
        level_tag = level.lower() if level in ("ERROR", "WARNING") else ""

        self.textbox.configure(state="normal")

        # Timestamp in muted colour
        self.textbox.insert("end", f"[{ts}] ", "ts")

        # Level prefix for non-info messages
        if level == "ERROR":
            self.textbox.insert("end", "[ERRORE] ", "error")
        elif level == "WARNING":
            self.textbox.insert("end", "[AVVISO] ", "warning")

        # Message text (with level colour if applicable)
        tag = level_tag if level_tag else ""
        self.textbox.insert("end", message + "\n", tag)

        self.textbox.see("end")
        self.textbox.configure(state="disabled")

    def clear(self) -> None:
        """Clear all log entries."""
        self.textbox.configure(state="normal")
        self.textbox.delete("1.0", "end")
        self.textbox.configure(state="disabled")
