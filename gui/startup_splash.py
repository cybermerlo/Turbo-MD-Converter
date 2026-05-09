"""Small startup splash shown while the main UI is being prepared."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk


class StartupSplash:
    def __init__(self, project_root: Path):
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.configure(bg="#f5efe6")
        self.root.attributes("-topmost", True)

        width, height = 360, 180
        x = int((self.root.winfo_screenwidth() - width) / 2)
        y = int((self.root.winfo_screenheight() - height) / 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

        frame = tk.Frame(
            self.root,
            bg="#fbf7f0",
            highlightthickness=1,
            highlightbackground="#e3d9c8",
        )
        frame.pack(fill="both", expand=True, padx=1, pady=1)

        self._logo = None
        logo_path = project_root / "logo.png"
        if logo_path.exists():
            try:
                from PIL import Image, ImageTk

                image = Image.open(logo_path).resize((48, 48))
                self._logo = ImageTk.PhotoImage(image)
                tk.Label(frame, image=self._logo, bg="#fbf7f0").pack(pady=(24, 8))
            except Exception:
                pass

        tk.Label(
            frame,
            text="Turbo MD Converter",
            bg="#fbf7f0",
            fg="#1c1814",
            font=("Segoe UI", 13, "bold"),
        ).pack()

        self.status_label = tk.Label(
            frame,
            text="Caricamento...",
            bg="#fbf7f0",
            fg="#8a7e6e",
            font=("Segoe UI", 9),
        )
        self.status_label.pack(pady=(8, 10))

        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Startup.Horizontal.TProgressbar",
            troughcolor="#efe7da",
            background="#c08a3a",
            bordercolor="#efe7da",
            lightcolor="#c08a3a",
            darkcolor="#c08a3a",
        )
        self.progress = ttk.Progressbar(
            frame,
            mode="indeterminate",
            length=220,
            style="Startup.Horizontal.TProgressbar",
        )
        self.progress.pack()
        self.progress.start(12)
        self.root.update()

    def set_status(self, message: str) -> None:
        self.status_label.configure(text=message)
        self.root.update()

    def close(self) -> None:
        try:
            self.progress.stop()
            self.root.destroy()
        except tk.TclError:
            pass
