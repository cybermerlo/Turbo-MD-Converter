"""Check-for-updates dialog."""

import tempfile
import threading
from pathlib import Path

import customtkinter as ctk

from version import VERSION


class UpdateDialog(ctk.CTkToplevel):
    """Modal dialog that checks GitHub releases and optionally downloads + installs."""

    def __init__(self, master):
        super().__init__(master)
        self.title("Verifica aggiornamenti")
        self.geometry("480x340")
        self.minsize(420, 280)
        self.resizable(False, False)
        self.grab_set()

        self._cancel_event = threading.Event()
        self._installer_path: Path | None = None

        # ── Current version label (always visible) ────────────────────────────
        ctk.CTkLabel(
            self,
            text=f"Versione installata:  {VERSION}",
            font=ctk.CTkFont(size=12),
            text_color="gray60",
        ).pack(padx=20, pady=(18, 0), anchor="w")

        # ── Dynamic content area ──────────────────────────────────────────────
        self._content = ctk.CTkFrame(self, fg_color="transparent")
        self._content.pack(padx=20, pady=10, fill="both", expand=True)

        # ── Bottom button row ─────────────────────────────────────────────────
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(padx=20, pady=(0, 16), fill="x")

        self._action_btn = ctk.CTkButton(
            btn_row, text="", state="disabled", width=180,
            command=self._on_action,
        )
        self._action_btn.pack(side="left")

        ctk.CTkButton(
            btn_row, text="Chiudi",
            fg_color="transparent", border_width=1, width=90,
            command=self._on_close,
        ).pack(side="right")

        self._show_checking()
        self.after(100, self._start_check)

    # ─── States ───────────────────────────────────────────────────────────────

    def _clear_content(self) -> None:
        for w in self._content.winfo_children():
            w.destroy()

    def _show_checking(self) -> None:
        self._clear_content()
        self._action_btn.configure(state="disabled", text="")
        ctk.CTkLabel(
            self._content, text="Verifica in corso…",
            font=ctk.CTkFont(size=13), text_color="gray60",
        ).pack(pady=(20, 8))
        bar = ctk.CTkProgressBar(self._content, mode="indeterminate")
        bar.pack(fill="x", pady=4)
        bar.start()
        self._indeterminate_bar = bar

    def _show_up_to_date(self) -> None:
        self._clear_content()
        self._action_btn.configure(state="disabled", text="")
        ctk.CTkLabel(
            self._content, text="✓  Sei aggiornato!",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color="#2ecc71",
        ).pack(pady=(24, 0))
        ctk.CTkLabel(
            self._content, text="Stai usando l'ultima versione disponibile.",
            font=ctk.CTkFont(size=12), text_color="gray60",
        ).pack(pady=6)

    def _show_update_available(self, info: dict) -> None:
        self._clear_content()

        ctk.CTkLabel(
            self._content,
            text=f"Nuova versione disponibile:  {info['version']}",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(anchor="w", pady=(4, 8))

        if info.get("release_notes"):
            notes_box = ctk.CTkTextbox(
                self._content, height=90,
                font=ctk.CTkFont(size=11),
            )
            notes_box.pack(fill="x", pady=(0, 8))
            notes_box.insert("1.0", info["release_notes"])
            notes_box.configure(state="disabled")

        size_mb = info.get("asset_size", 0) / 1_048_576
        if size_mb > 0:
            ctk.CTkLabel(
                self._content,
                text=f"Dimensione installer: {size_mb:.1f} MB",
                font=ctk.CTkFont(size=11), text_color="gray60",
            ).pack(anchor="w")

        self._action_btn.configure(
            state="normal", text="↓  Scarica e installa",
        )
        self._pending_info = info

    def _show_downloading(self, asset_name: str) -> None:
        self._clear_content()
        self._action_btn.configure(state="disabled", text="Download in corso…")

        ctk.CTkLabel(
            self._content, text=f"Download: {asset_name}",
            font=ctk.CTkFont(size=12), text_color="gray60",
        ).pack(anchor="w", pady=(8, 4))

        self._dl_bar = ctk.CTkProgressBar(self._content)
        self._dl_bar.pack(fill="x", pady=4)
        self._dl_bar.set(0)

        self._dl_pct = ctk.CTkLabel(
            self._content, text="0%",
            font=ctk.CTkFont(size=12), text_color="gray60",
        )
        self._dl_pct.pack(anchor="e")

    def _show_ready(self, installer_path: Path) -> None:
        self._clear_content()
        self._installer_path = installer_path

        ctk.CTkLabel(
            self._content, text="✓  Download completato!",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#2ecc71",
        ).pack(pady=(16, 6))
        ctk.CTkLabel(
            self._content,
            text="L'app si chiuderà e l'installazione partirà automaticamente.",
            font=ctk.CTkFont(size=11), text_color="gray60",
            wraplength=400,
        ).pack(pady=4)

        self._action_btn.configure(
            state="normal", text="▶  Installa ora",
        )

    def _show_error(self, message: str) -> None:
        self._clear_content()
        self._action_btn.configure(state="disabled", text="")
        ctk.CTkLabel(
            self._content, text="Errore",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#e74c3c",
        ).pack(anchor="w", pady=(8, 4))
        ctk.CTkLabel(
            self._content, text=message,
            font=ctk.CTkFont(size=11), text_color="gray60",
            wraplength=420, justify="left",
        ).pack(anchor="w")

    # ─── Logic ────────────────────────────────────────────────────────────────

    def _start_check(self) -> None:
        threading.Thread(target=self._check_thread, daemon=True).start()

    def _check_thread(self) -> None:
        from utils.updater import get_latest_release, is_newer
        try:
            info = get_latest_release()
        except RuntimeError as e:
            self.after(0, self._show_error, str(e))
            return

        if is_newer(info["version"], VERSION):
            self.after(0, self._show_update_available, info)
        else:
            self.after(0, self._show_up_to_date)

    def _on_action(self) -> None:
        if self._installer_path:
            self._do_install()
        elif hasattr(self, "_pending_info"):
            self._start_download(self._pending_info)

    def _start_download(self, info: dict) -> None:
        url = info.get("download_url")
        name = info.get("asset_name", "installer.exe")
        if not url:
            self._show_error("Nessun installer trovato in questa release.")
            return

        self._show_downloading(name)
        self._cancel_event.clear()

        def thread():
            from utils.updater import download_installer
            tmp_dir = Path(tempfile.mkdtemp(prefix="turbomd_update_"))
            dest = tmp_dir / name
            try:
                download_installer(
                    url, dest,
                    progress_cb=lambda p: self.after(0, self._update_progress, p),
                    cancel_event=self._cancel_event,
                )
                if not self._cancel_event.is_set():
                    self.after(0, self._show_ready, dest)
            except RuntimeError as e:
                self.after(0, self._show_error, str(e))

        threading.Thread(target=thread, daemon=True).start()

    def _update_progress(self, fraction: float) -> None:
        if hasattr(self, "_dl_bar"):
            self._dl_bar.set(min(fraction, 1.0))
        if hasattr(self, "_dl_pct"):
            self._dl_pct.configure(text=f"{int(fraction * 100)}%")

    def _do_install(self) -> None:
        from utils.updater import launch_installer_and_exit
        if self._installer_path and self._installer_path.exists():
            launch_installer_and_exit(self._installer_path)

    def _on_close(self) -> None:
        self._cancel_event.set()
        self.grab_release()
        self.destroy()
