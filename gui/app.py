"""Turbo MD Converter — main window (paper + amber redesign)."""

from __future__ import annotations
import logging
import os
import queue
import subprocess
import sys
from pathlib import Path

import customtkinter as ctk
from tkinterdnd2 import DND_FILES, TkinterDnD

from config.settings import AppConfig, save_config
from gui import theme
from gui.resources import resource_path
from gui.frames.input_frame import InputFrame
from gui.frames.log_frame import LogFrame
from gui.frames.output_frame import OutputFrame
from gui.frames.progress_frame import ProgressFrame
from gui.frames.settings_frame import SettingsWindow
from gui.options_panel import OptionsPanel
from gui.pipeline_event_handler import PipelineEventHandler
from gui.toast import ToastStack
from pipeline.events import PipelineEvent
from pipeline.worker import PipelineWorker
from utils.system import no_window_kwargs, open_with_system
from version import VERSION


class TurboMDConverterApp(ctk.CTk, TkinterDnD.DnDWrapper):
    """Main application window — 3-column paper layout."""

    def __init__(self, config: AppConfig, initial_files: list[Path] | None = None):
        super().__init__()
        self.TkdndVersion = TkinterDnD._require(self)

        # Theme must be set BEFORE any widgets are created
        theme.install_theme()

        self.title("Turbo MD Converter")
        try:
            icon_path = resource_path("logo.ico")
            if icon_path.exists():
                self.iconbitmap(str(icon_path))
        except Exception:
            pass
        self.geometry("1380x840")
        self.minsize(1180, 680)
        self.configure(fg_color=theme.PAPER)

        self.config = config
        self.gui_queue: queue.Queue[PipelineEvent] = queue.Queue()
        self.worker: PipelineWorker | None = None

        self._batch_total: int = 0
        self._batch_done: int = 0
        self._base_cost: float = 0.0
        self._current_ocr_cost: float = 0.0
        self._converted_mds: dict[Path, Path] = {}
        self._cost_per_input: dict[Path, float] = {}
        self._error_keys: dict[Path, str] = {}
        # input_path → segments diarizzati, per l'identificazione interlocutori a fine batch.
        self._pending_speaker_ids: dict[Path, list] = {}

        self._build_layout()
        self._setup_drag_drop()
        self._setup_paste_shortcut()
        self.bind("<Delete>", self._on_delete_key)
        self._start_queue_polling()

        # initial state
        self._sync_options_to_config()
        self._refresh_cost_chart()

        if initial_files:
            self.after(100, lambda: self.input_frame.add_paths(initial_files))
        self.after(500, self._check_sendto_shortcut)

    # ─── Layout ──────────────────────────────────────────────────────────────
    def _build_layout(self) -> None:
        self.grid_columnconfigure(0, weight=0, minsize=340)  # sidebar
        self.grid_columnconfigure(1, weight=0, minsize=420)  # options
        self.grid_columnconfigure(2, weight=1, minsize=360)  # preview/log canvas
        self.grid_rowconfigure(1, weight=1)      # row 0 = topbar, row 1 = body

        # ── Top bar ──────────────────────────────────────────────────────
        topbar = ctk.CTkFrame(self, fg_color=theme.PAPER, corner_radius=0,
                              height=58)
        topbar.grid(row=0, column=0, columnspan=3, sticky="ew")
        topbar.grid_propagate(False)
        theme.hairline(topbar).pack(side="bottom", fill="x")

        topbar_inner = ctk.CTkFrame(topbar, fg_color="transparent")
        topbar_inner.pack(fill="both", expand=True, padx=22, pady=10)

        # Brand mark
        try:
            from PIL import Image
            logo_path = resource_path("logo.png")
            if logo_path.exists():
                img = Image.open(logo_path)
                self.logo_img = ctk.CTkImage(light_image=img, dark_image=img,
                                             size=(28, 28))
                ctk.CTkLabel(topbar_inner, image=self.logo_img, text="").pack(
                    side="left", padx=(0, 10))
        except Exception:
            pass

        ctk.CTkLabel(
            topbar_inner, text="Turbo MD Converter",
            font=theme.font(15, "bold"), text_color=theme.INK,
        ).pack(side="left")
        ctk.CTkLabel(
            topbar_inner, text=f"v{VERSION}",
            font=theme.font(10, mono=True), text_color=theme.INK_4,
        ).pack(side="left", padx=(10, 0), pady=(4, 0))

        # Right side: cost summary
        self.topbar_cost_lbl = ctk.CTkLabel(
            topbar_inner, text="$0.0000",
            font=theme.font(13, "bold", mono=True), text_color=theme.INK,
        )
        self.topbar_cost_lbl.pack(side="right")
        ctk.CTkLabel(
            topbar_inner, text="COSTO SESSIONE",
            font=theme.font(9, "bold"), text_color=theme.INK_3,
        ).pack(side="right", padx=(0, 8), pady=(2, 0))

        # ── Sidebar ──────────────────────────────────────────────────────
        sidebar = ctk.CTkFrame(self, fg_color=theme.PAPER, corner_radius=0,
                               width=340)
        sidebar.grid(row=1, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        # vertical hairline on the right
        rule = ctk.CTkFrame(sidebar, width=1, fg_color=theme.RULE,
                            corner_radius=0)
        rule.pack(side="right", fill="y")

        self.input_frame = InputFrame(
            sidebar,
            on_files_changed=self._on_files_changed,
            on_selection_changed=self._on_input_selection_changed,
            on_open_requested=self._open_input_file,
            on_import_whatsapp=self._open_whatsapp_import,
        )
        self.input_frame.pack(side="left", fill="both", expand=True)

        # ── Canvas (center column) ───────────────────────────────────────
        canvas = ctk.CTkFrame(self, fg_color=theme.PAPER, corner_radius=0)
        canvas.grid(row=1, column=2, sticky="nsew")
        canvas.grid_columnconfigure(0, weight=1)
        canvas.grid_rowconfigure(1, weight=1)   # output frame stretches

        self.progress_frame = ProgressFrame(canvas)
        self.progress_frame.grid(row=0, column=0, sticky="ew")

        self.output_frame = OutputFrame(canvas)
        self.output_frame.grid(row=1, column=0, sticky="nsew")

        self.log_frame = LogFrame(canvas)
        self.log_frame.grid(row=2, column=0, sticky="ew")

        # ── Options panel (middle column) ────────────────────────────────
        opts_wrap = ctk.CTkFrame(self, fg_color=theme.PAPER, corner_radius=0,
                                 width=420)
        opts_wrap.grid(row=1, column=1, sticky="nsew")
        opts_wrap.grid_propagate(False)
        rule2 = ctk.CTkFrame(opts_wrap, width=1, fg_color=theme.RULE,
                             corner_radius=0)
        rule2.pack(side="right", fill="y")

        self.options_panel = OptionsPanel(
            opts_wrap, self.config,
            on_change=self._on_options_change,
            on_start=self._start_processing,
            on_cancel=self._cancel_processing,
            on_open_settings=self._open_settings,
            on_open_updates=self._open_update_dialog,
            on_open_rename_context=self._open_rename_context_dialog,
        )
        self.options_panel.pack(side="left", fill="both", expand=True)

        # ── Toast stack (overlay anchored bottom-right) ──────────────────
        self.toast_stack = ToastStack(self)
        # Position above the log drawer
        self._reposition_toast_stack()
        self._toast_reposition_pending = False
        self.bind("<Configure>", lambda _e: self._schedule_toast_reposition())

        self._event_handler = PipelineEventHandler(self)

    def _schedule_toast_reposition(self):
        if self._toast_reposition_pending:
            return
        self._toast_reposition_pending = True
        self.after_idle(self._reposition_toast_stack)

    def _reposition_toast_stack(self):
        self._toast_reposition_pending = False
        if not hasattr(self, "toast_stack"):
            return
        try:
            self.toast_stack.place(
                in_=self,
                relx=1.0, rely=1.0,
                anchor="se",
                x=-360, y=-72,
                width=360,
            )
        except Exception:
            pass

    # ─── Drag & drop ─────────────────────────────────────────────────────────
    def _setup_drag_drop(self) -> None:
        self._register_drop_targets(
            self._on_drop_files,
            self,
            self.input_frame,
            self.input_frame.file_list,
            self.input_frame.dropzone,
            *self.input_frame.dropzone.winfo_children(),
            self.output_frame,
            self.output_frame.md_textbox,
        )

    def _register_drop_targets(self, callback, *widgets) -> None:
        for widget in widgets:
            try:
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", callback)
            except Exception:
                pass

    def _on_drop_files(self, event) -> None:
        path_objs = self._paths_from_drop_event(event)
        self.input_frame.add_paths(path_objs)
        return event.action

    def _setup_paste_shortcut(self) -> None:
        self.bind_all("<Control-v>", self._on_paste_shortcut, add="+")
        self.bind_all("<Control-V>", self._on_paste_shortcut, add="+")

    def _on_paste_shortcut(self, event=None):
        focus = self.focus_get()
        if self._focus_is_text_input(focus):
            return None

        if focus is not None and focus is not self:
            if not self._is_descendant_of(focus, self.input_frame):
                return None

        if self.input_frame.paste_from_clipboard():
            return "break"
        return None

    @staticmethod
    def _focus_is_text_input(widget) -> bool:
        if widget is None:
            return False
        try:
            widget_class = widget.winfo_class().lower()
        except Exception:
            return False
        return "entry" in widget_class or "text" in widget_class

    def _is_descendant_of(self, widget, parent) -> bool:
        while widget is not None:
            if widget is parent:
                return True
            try:
                parent_name = widget.winfo_parent()
                if not parent_name:
                    return False
                widget = self.nametowidget(parent_name)
            except Exception:
                return False
        return False

    def _paths_from_drop_event(self, event) -> list[Path]:
        if not event.data:
            return []
        try:
            paths = self.tk.splitlist(event.data)
        except Exception:
            paths = [event.data.strip()]
        out = []
        for p in paths:
            p = p.strip()
            if not p:
                continue
            if p.startswith("file://"):
                import urllib.parse, urllib.request
                p = urllib.request.url2pathname(urllib.parse.urlparse(p).path)
            out.append(Path(p))
        return out

    def _on_delete_key(self, event=None):
        if self.input_frame.get_selected_path() is not None:
            return self.input_frame.handle_delete_key(event)
        return None

    # ─── Event queue ─────────────────────────────────────────────────────────
    def _start_queue_polling(self) -> None:
        has_events = False
        while not self.gui_queue.empty():
            try:
                event = self.gui_queue.get_nowait()
            except queue.Empty:
                break
            has_events = True
            # Un'eccezione in un handler non deve mai uccidere il loop di
            # polling (lascerebbe la UI "congelata" sugli aggiornamenti): la
            # si registra e si prosegue con l'evento successivo.
            try:
                self._event_handler.handle(event)
            except Exception:
                logging.getLogger(__name__).exception(
                    "Errore nella gestione dell'evento %r", type(event).__name__
                )
        delay = 100 if has_events else 500
        self.after(delay, self._start_queue_polling)

    def _update_total_cost(self):
        self._event_handler.update_total_cost()

    def _refresh_cost_chart(self):
        self._event_handler.refresh_cost_chart()

    # ─── Options + processing ───────────────────────────────────────────
    def _on_options_change(self):
        if not hasattr(self, "options_panel"):
            return
        self._sync_options_to_config()

    def _sync_options_to_config(self):
        v = self.options_panel.get_values()
        model_changed = self.config.ocr_model_id != v["model"]
        self.config.run_ocr = v["run_ocr"]
        self.config.run_extraction = v["run_extraction"]
        self.config.email_attachments_separate = bool(v["email_attachments_separate"])
        self.config.ocr_model_id = v["model"]
        self.config.extraction_model_id = v["model"]
        self.config.active_schema = v["schema"]
        self.config.rename_files = v["rename_files"]
        self.config.final_error_check = bool(v["final_error_check"])
        self.config.rename_mode = v["rename_mode"]
        self.config.rename_use_batch_context = bool(v["rename_use_batch_context"])
        self.config.output_mode = v["output_mode"]
        self.config.output_formats = v["output_formats"]
        if model_changed:
            save_config(self.config)

    def _on_files_changed(self, paths: list[Path]) -> None:
        has_files = len(paths) > 0
        self.options_panel.set_can_start(has_files)

        # Drop stale tracking data for files no longer in the list.
        current = set(paths)
        for input_path in list(self._converted_mds):
            if input_path not in current:
                self._converted_mds.pop(input_path, None)
        for p in list(self._cost_per_input):
            if p not in current:
                self._cost_per_input.pop(p, None)
        for p in list(self._error_keys):
            if p not in current:
                self.toast_stack.dismiss(self._error_keys[p])
                self._error_keys.pop(p, None)
        self._refresh_cost_chart()

    def _on_input_selection_changed(self, path: Path | None) -> None:
        if path is None:
            self.output_frame.clear_preview()
            return
        md_path = self._converted_mds.get(path)
        if md_path and md_path.exists():
            self.output_frame.show_markdown_file(md_path)
        else:
            self.output_frame.clear_preview(
                "Il Markdown del file selezionato non è ancora disponibile."
            )

    def _open_input_file(self, path: Path, is_clipboard: bool) -> None:
        if is_clipboard:
            self._open_clipboard_editor(path)
            return
        open_with_system(path)

    def _open_clipboard_editor(self, path: Path) -> None:
        dlg = ctk.CTkToplevel(self)
        dlg.title(f"Appunti — {path.name}")
        dlg.geometry("680x440")
        dlg.minsize(460, 300)
        dlg.transient(self)
        try:
            dlg.configure(fg_color=theme.PAPER)
        except Exception:
            pass

        ctk.CTkLabel(
            dlg, text="Contenuto incollato",
            font=theme.font(15, "bold"), text_color=theme.INK,
        ).pack(padx=18, pady=(16, 6), anchor="w")

        textbox = ctk.CTkTextbox(
            dlg, font=theme.font(11, mono=True), wrap="word",
            fg_color=theme.CARD, text_color=theme.INK,
            border_width=1, border_color=theme.RULE,
        )
        textbox.pack(padx=18, pady=(0, 10), fill="both", expand=True)
        try:
            textbox.insert("1.0", path.read_text(encoding="utf-8"))
        except OSError:
            pass

        btn_row = ctk.CTkFrame(dlg, fg_color="transparent")
        btn_row.pack(padx=18, pady=(0, 16), fill="x")
        status = ctk.CTkLabel(btn_row, text="",
                              font=theme.font(11), text_color=theme.INK_3)
        status.pack(side="left")

        def save():
            try:
                path.write_text(textbox.get("1.0", "end-1c"), encoding="utf-8")
                status.configure(text="Salvato")
            except OSError as exc:
                status.configure(text=f"Errore: {exc}")

        theme.amber_button(btn_row, "Salva", width=100, command=save).pack(
            side="right", padx=(8, 0))
        theme.ghost_button(btn_row, "Chiudi", width=100,
                           command=dlg.destroy).pack(side="right")

    def _start_processing(self) -> None:
        pdf_paths = self.input_frame.get_file_paths()
        if not pdf_paths:
            return

        self._sync_options_to_config()

        if not self.config.run_ocr and not self.config.run_extraction:
            msg = "Seleziona almeno un'operazione (OCR o Estrazione strutturata)."
            self.log_frame.append(msg, "ERROR")
            self._show_toast("missing-op", "Operazione mancante", msg, "error")
            return

        from pipeline.processor import IMAGE_EXTENSIONS
        needs_ocr = any(
            p.suffix.lower() in (".pdf",) + IMAGE_EXTENSIONS for p in pdf_paths
        )
        needs_api_key = (needs_ocr and self.config.run_ocr) or self.config.run_extraction
        if not self.config.gemini_api_key and needs_api_key:
            msg = "Chiave API Gemini non configurata. Apri le Impostazioni."
            self.log_frame.append(msg, "ERROR")
            self._show_toast("no-api-key", "Chiave API mancante", msg, "error")
            return

        # Reset batch state
        self._batch_total = len(pdf_paths)
        self._batch_done = 0
        self._base_cost = 0.0
        self._current_ocr_cost = 0.0
        self._converted_mds = {}
        self._cost_per_input = {}
        self.toast_stack.clear()
        self._error_keys = {}
        self._pending_speaker_ids = {}

        self.progress_frame.reset()
        self.progress_frame.set_batch(self._batch_total)
        self.output_frame.clear()
        self.log_frame.clear()
        self.input_frame.reset_copy_buttons()
        self._refresh_cost_chart()
        self._update_total_cost()

        self.input_frame.set_enabled(False)
        self.options_panel.set_running(True)

        self.worker = PipelineWorker(self.config, self.gui_queue)
        self.worker.start(pdf_paths)

        n = len(pdf_paths)
        doc_word = "documento" if n == 1 else "documenti"
        phases = []
        if self.config.run_ocr:
            phases.append(f"OCR [{self.config.ocr_model_id}]")
        if self.config.run_extraction:
            phases.append(f"estrazione [{self.config.active_schema}]")
        self.log_frame.append(
            f"Avvio elaborazione di {n} {doc_word} — {' + '.join(phases)}"
        )

    def _cancel_processing(self) -> None:
        if self.worker:
            self.worker.cancel()
            self.log_frame.append("Interruzione in corso…", "WARNING")

    # ─── Toasts ──────────────────────────────────────────────────────────
    def _show_toast(self, key, title, message, level="error"):
        try:
            self.toast_stack.show(key, title, message, level=level)
        except Exception:
            pass

    # ─── Identificazione interlocutori (post-batch) ──────────────────────
    def _run_speaker_identification(self) -> None:
        """Per ogni file multi-speaker chiede i nomi e riscrive l'.md (in serie)."""
        pending = list(self._pending_speaker_ids.items())
        self._pending_speaker_ids = {}
        self._identify_next_speaker(pending)

    def _identify_next_speaker(self, pending: list) -> None:
        if not pending:
            return
        input_path, segments = pending.pop(0)
        md_path = self._converted_mds.get(input_path)
        if not md_path or not Path(md_path).exists() or not Path(input_path).exists():
            self._identify_next_speaker(pending)  # niente .md o audio: salta
            return

        from gui.frames.speaker_id_window import SpeakerIdentificationWindow
        from ocr.speaker_id import pick_speaker_snippets, rewrite_transcript_in_md

        def on_done(labels):
            if labels:
                try:
                    if rewrite_transcript_in_md(md_path, segments, labels):
                        self.log_frame.append(
                            f"Interlocutori rinominati in {Path(md_path).name}")
                        selected = self.input_frame.get_selected_path()
                        if selected is not None and \
                                self._converted_mds.get(selected) == md_path:
                            self.output_frame.show_markdown_file(md_path)
                except Exception as e:
                    self.log_frame.append(
                        f"Identificazione interlocutori fallita: {e}", "ERROR")
            self._identify_next_speaker(pending)

        SpeakerIdentificationWindow(
            self,
            file_label=Path(input_path).name,
            audio_path=input_path,
            snippets_by_speaker=pick_speaker_snippets(segments),
            on_done=on_done,
        )

    # ─── Settings / dialogs ──────────────────────────────────────────────
    def _open_settings(self) -> None:
        SettingsWindow(self, self.config, self._on_settings_saved)

    def _open_update_dialog(self) -> None:
        from gui.frames.update_dialog import UpdateDialog
        UpdateDialog(self)

    def _open_whatsapp_import(self) -> None:
        from gui.frames.whatsapp_import_window import WhatsAppImportWindow
        WhatsAppImportWindow(
            self, self.config, on_package_ready=self._on_whatsapp_package_ready,
        )

    def _on_whatsapp_package_ready(self, package_path: Path) -> None:
        self.input_frame.add_paths([package_path])
        self.log_frame.append(
            f"Conversazione WhatsApp importata: {package_path.name}"
        )

    def _on_settings_saved(self, config: AppConfig) -> None:
        self.config = config
        self.options_panel.sync_from_config(config)
        save_config(config)
        self.log_frame.append("Impostazioni salvate.")

    def _open_rename_context_dialog(self) -> None:
        dlg = ctk.CTkToplevel(self)
        dlg.title("Contesto utente — Rinomina")
        dlg.geometry("720x380")
        dlg.resizable(True, True)
        dlg.transient(self)
        dlg.grab_set()
        try:
            dlg.configure(fg_color=theme.PAPER)
        except Exception:
            pass

        ctk.CTkLabel(
            dlg, text="Contesto utente aggiuntivo",
            font=theme.font(15, "bold"), text_color=theme.INK,
        ).pack(padx=18, pady=(16, 4), anchor="w")
        ctk.CTkLabel(
            dlg, text=("Questo testo viene passato al modello durante la rinomina, "
                       "in modalità classica e batch-context. Indica come vuoi che "
                       "i nomi vengano costruiti."),
            text_color=theme.INK_3, wraplength=680, justify="left",
            font=theme.font(11),
        ).pack(padx=18, pady=(0, 10), anchor="w")

        enabled_var = ctk.BooleanVar(
            value=bool(getattr(self.config, "rename_use_user_context", False)))
        cb = ctk.CTkCheckBox(
            dlg, text="Abilita contesto utente per la rinomina",
            variable=enabled_var, font=theme.font(11), text_color=theme.INK_2,
            fg_color=theme.AMBER, hover_color=theme.AMBER_DEEP,
            border_color=theme.RULE_STRONG,
        )
        cb.pack(padx=18, pady=(0, 6), anchor="w")

        textbox = ctk.CTkTextbox(
            dlg, height=160, font=theme.font(11, mono=True),
            fg_color=theme.CARD, text_color=theme.INK,
            border_width=1, border_color=theme.RULE,
        )
        textbox.pack(padx=18, pady=(0, 10), fill="both", expand=True)
        textbox.insert("1.0", getattr(self.config, "rename_user_context_text", "") or "")

        def sync_state():
            textbox.configure(state="normal" if enabled_var.get() else "disabled")
        cb.configure(command=sync_state)
        sync_state()

        btn_row = ctk.CTkFrame(dlg, fg_color="transparent")
        btn_row.pack(padx=18, pady=(0, 16), fill="x")

        def on_save():
            self.config.rename_use_user_context = bool(enabled_var.get())
            self.config.rename_user_context_text = textbox.get("1.0", "end").strip()
            save_config(self.config)
            dlg.destroy()

        theme.amber_button(btn_row, "Salva", width=110, command=on_save).pack(
            side="right", padx=(8, 0))
        theme.ghost_button(btn_row, "Chiudi", width=110, command=dlg.destroy).pack(
            side="right")

    # ─── SendTo shortcut (Windows) ───────────────────────────────────────
    def _check_sendto_shortcut(self) -> None:
        from tkinter import messagebox

        if not getattr(sys, "frozen", False):
            return

        sendto_dir = Path(os.path.expandvars(r"%APPDATA%\Microsoft\Windows\SendTo"))
        shortcut_path = sendto_dir / "TurboMDConverter.lnk"

        if shortcut_path.exists():
            if not self.config.asked_sendto:
                self.config.asked_sendto = True
                save_config(self.config)
            return
        if self.config.asked_sendto:
            return

        response = messagebox.askyesno(
            "Integrazione Windows",
            "Aggiungere 'Turbo MD Converter' al menu 'Invia a' di Windows?\n\n"
            "Permette di selezionare file o cartelle, fare clic destro\n"
            "e inviarli direttamente a questa applicazione.",
            parent=self,
        )

        if response:
            exe_path = Path(sys.executable)
            vbs_script = f'''
Set oWS = WScript.CreateObject("WScript.Shell")
sLinkFile = "{shortcut_path}"
Set oLink = oWS.CreateShortcut(sLinkFile)
oLink.TargetPath = "{exe_path}"
oLink.Description = "Invia a Turbo MD Converter"
oLink.Save
'''
            vbs_path = sendto_dir / "temp_create_shortcut.vbs"
            try:
                vbs_path.write_text(vbs_script, encoding="utf-8")
                subprocess.run(
                    ["cscript.exe", "//Nologo", str(vbs_path)],
                    **no_window_kwargs(),
                )
                self.log_frame.append("Collegamento aggiunto al menu 'Invia a'.")
            except Exception as e:
                self.log_frame.append(
                    f"Impossibile creare il collegamento: {e}", "ERROR")
            finally:
                if vbs_path.exists():
                    vbs_path.unlink()

        self.config.asked_sendto = True
        save_config(self.config)
