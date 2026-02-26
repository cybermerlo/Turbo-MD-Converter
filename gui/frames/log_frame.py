"""Real-time log display frame."""

from datetime import datetime

import customtkinter as ctk


class LogFrame(ctk.CTkFrame):
    """Scrollable log area showing timestamped messages."""

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)

        self.label = ctk.CTkLabel(self, text="Log", font=ctk.CTkFont(weight="bold"))
        self.label.pack(padx=10, pady=(5, 0), anchor="w")

        self.textbox = ctk.CTkTextbox(self, height=150, font=ctk.CTkFont(size=12))
        self.textbox.pack(padx=10, pady=5, fill="both", expand=True)
        self.textbox.configure(state="disabled")

    def append(self, message: str, level: str = "INFO") -> None:
        """Add a timestamped log entry."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        prefix = f"[{timestamp}] [{level}] "

        self.textbox.configure(state="normal")
        self.textbox.insert("end", prefix + message + "\n")
        self.textbox.see("end")
        self.textbox.configure(state="disabled")

    def clear(self) -> None:
        """Clear all log entries."""
        self.textbox.configure(state="normal")
        self.textbox.delete("1.0", "end")
        self.textbox.configure(state="disabled")
