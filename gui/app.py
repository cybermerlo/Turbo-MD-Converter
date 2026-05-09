"""Turbo MD Converter — main window (paper + amber redesign)."""

from __future__ import annotations
import os
import queue
import subprocess
import sys
import tkinter as tk
from pathlib import Path

import customtkinter as ctk
from tkinterdnd2 import DND_FILES, TkinterDnD

from config.settings import AppConfig, save_config
from gui import theme
from gui.frames.input_frame import InputFrame
from gui.frames.log_frame import LogFrame
from gui.frames.output_frame import OutputFrame
from gui.frames.progress_frame import ProgressFrame
from gui.frames.settings_frame import SettingsWindow
from gui.options_panel import OptionsPanel
from gui.toast import ToastStack
from pipeline.events import (
    BatchCompleteEvent,
    ErrorEvent,
    ExtractionCompleteEvent,
    ExtractionProgressEvent,
    ExtractionStartEvent,
    FileRenamedEvent,
    LogEvent,
    OCRProgressEvent,
    OutputWrittenEvent,
    PageNativeTextEvent,
    PageSkippedEvent,
    PipelineCompleteEvent,
    PipelineEvent,
)
from pipeline.worker import PipelineWorker
from version import VERSION


class TurboMDConverterApp(ctk.CTk, TkinterDnD.DnDWrapper):
    """Main application window — 3-column paper layout."""

    def __init__(self, config: AppConfig, initial_files: list[Path] | None = None):
        super().__init__()
        self.TkdndVersion = TkinterDnD._require(self)

        # Theme must be set BEFORE any widgets are created
        theme.install_theme()

        self.title("Turbo MD Converter")
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

        self._build_layout()
        self._setup_drag_drop()
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
            logo_path = Path(__file__).parent.parent / "logo.png"
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
        self.bind("<Configure>", lambda _e: self._reposition_toast_stack())

    def _reposition_toast_stack(self):
        if not hasattr(self, "toast_stack"):
            return
        # Anchor to bottom-right of the canvas (col 1) area, above the log drawer
        try:
            self.update_idletasks()
            w = 360
            self.toast_stack.place(
                in_=self,
                relx=1.0, rely=1.0,
                anchor="se",
                x=-360, y=-72,
                width=w,
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
        try:
            while True:
                event = self.gui_queue.get_nowait()
                self._handle_event(event)
        except queue.Empty:
            pass
        self.after(100, self._start_queue_polling)

    def _handle_event(self, event: PipelineEvent) -> None:
        if isinstance(event, OCRProgressEvent):
            if event.page_num == 0:
                self._current_ocr_cost = event.page_cost
            else:
                self._current_ocr_cost += event.page_cost
            self._update_total_cost()

        elif isinstance(event, (ExtractionStartEvent, ExtractionProgressEvent,
                                ExtractionCompleteEvent)):
            pass  # no UI update needed

        elif isinstance(event, PageNativeTextEvent):
            self.log_frame.append(
                f"Pag. {event.page_num + 1}/{event.total_pages}: "
                f"testo nativo ({event.char_count:,} car.) — OCR saltato",
                "INFO",
            )

        elif isinstance(event, PageSkippedEvent):
            msg = (f"Pagina {event.page_num + 1}/{event.total_pages} senza testo. "
                   f"Motivo: {event.reason}")
            self.log_frame.append(msg, "WARNING")
            self._show_toast(
                key=f"skip-{event.page_num}",
                title="Pagina senza testo", message=msg, level="warning",
            )

        elif isinstance(event, OutputWrittenEvent):
            if event.file_paths:
                self.output_frame.set_output_dir(event.file_paths[0].parent)
                for fp in event.file_paths:
                    try:
                        if fp.suffix == ".md":
                            if self.input_frame.get_selected_path() is None:
                                self.output_frame.show_markdown_file(fp)
                        elif fp.suffix == ".json":
                            content = fp.read_text(encoding="utf-8")
                            self.output_frame.show_json(content)
                    except OSError:
                        pass

        elif isinstance(event, PipelineCompleteEvent):
            file_cost = event.cost_info.get("total", {}).get("cost_usd", 0.0)
            self._base_cost += file_cost
            self._current_ocr_cost = 0.0
            self._batch_done += 1

            self.progress_frame.update_files(self._batch_done, self._batch_total,
                                             self._base_cost)
            self._update_total_cost()

            if event.pdf_path:
                self._cost_per_input[event.pdf_path] = file_cost
                self.input_frame.set_cost_for_file(event.pdf_path, file_cost)
                if event.success:
                    self.input_frame.set_status_for_file(event.pdf_path, "ok")
                    md_files = [f for f in event.output_files if f.suffix == ".md"]
                    if md_files:
                        self._converted_mds[event.pdf_path] = md_files[0]
                        self.input_frame.set_md_for_file(event.pdf_path, md_files[0])
                        if self.input_frame.get_selected_path() == event.pdf_path:
                            self.output_frame.show_markdown_file(md_files[0])
                else:
                    self.input_frame.set_status_for_file(event.pdf_path, "err")
            self._refresh_cost_chart()

        elif isinstance(event, BatchCompleteEvent):
            self._on_batch_complete(event)

        elif isinstance(event, FileRenamedEvent):
            self.log_frame.append(
                f"Rinominato ({event.file_type.upper()}): "
                f"{event.original_path.name} → {event.new_path.name}"
            )
            if event.file_type == "md" and event.original_path and event.new_path:
                for input_path, md_path in list(self._converted_mds.items()):
                    if md_path == event.original_path:
                        self._converted_mds[input_path] = event.new_path
                        self.input_frame.set_md_for_file(input_path, event.new_path)
                        if self.input_frame.get_selected_path() == input_path:
                            self.output_frame.show_markdown_file(event.new_path)
                        break
            elif event.file_type == "pdf" and event.original_path and event.new_path:
                md_path = self._converted_mds.pop(event.original_path, None)
                if md_path:
                    self._converted_mds[event.new_path] = md_path
                cost = self._cost_per_input.pop(event.original_path, 0.0)
                self._cost_per_input[event.new_path] = cost
                was_selected = self.input_frame.get_selected_path() == event.original_path
                self.input_frame.replace_path(event.original_path, event.new_path)
                if md_path:
                    self.input_frame.set_md_for_file(event.new_path, md_path)
                    if was_selected:
                        self.output_frame.show_markdown_file(md_path)
                if cost:
                    self.input_frame.set_cost_for_file(event.new_path, cost)
                self._refresh_cost_chart()

        elif isinstance(event, ErrorEvent):
            self.log_frame.append(event.error_message, "ERROR")
            target = getattr(event, "pdf_path", None)
            if target:
                self.input_frame.set_status_for_file(target, "err")
            self._show_toast(
                key=f"err-{target}" if target else "err-general",
                title="Errore di elaborazione",
                message=event.error_message,
                level="error",
            )

        elif isinstance(event, LogEvent):
            self.log_frame.append(event.message, event.level)

    # ─── Cost helpers ────────────────────────────────────────────────────
    def _update_total_cost(self):
        total = self._base_cost + self._current_ocr_cost
        self.topbar_cost_lbl.configure(text=f"${total:.4f}")
        self.progress_frame.update_cost(total)

    def _refresh_cost_chart(self):
        rows = []
        for p, status, _cost in self.input_frame.get_rows():
            actual = self._cost_per_input.get(p, 0.0)
            rows.append((p.name, status, actual))
        self.options_panel.update_cost_rows(rows)

    # ─── Options + processing ───────────────────────────────────────────
    def _on_options_change(self):
        if not hasattr(self, "options_panel"):
            return
        self._sync_options_to_config()

    def _sync_options_to_config(self):
        v = self.options_panel.get_values()
        self.config.run_ocr = v["run_ocr"]
        self.config.run_extraction = v["run_extraction"]
        self.config.ocr_model_id = v["model"]
        self.config.extraction_model_id = v["model"]
        self.config.active_schema = v["schema"]
        self.config.rename_files = v["rename_files"]
        self.config.rename_mode = v["rename_mode"]
        self.config.rename_use_batch_context = bool(v["rename_use_batch_context"])
        self.config.output_mode = v["output_mode"]
        self.config.output_formats = ["markdown"]

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
                self.toast_stack._on_toast_closed(self._error_keys[p])
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
        if not path.exists():
            return
        if sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])

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

    def _on_batch_complete(self, event: BatchCompleteEvent) -> None:
        self.input_frame.set_enabled(True)
        self.options_panel.set_running(False)
        self.options_panel.set_can_start(bool(self.input_frame.get_file_paths()))

        ok = event.successful
        fail = event.failed
        total = event.total_pdfs
        self.progress_frame.mark_complete(ok, total, self._base_cost, failed=fail)
        if self._converted_mds:
            self.output_frame.set_all_mds(list(self._converted_mds.values()))

        if fail == 0:
            self.log_frame.append(f"Completato — {ok}/{total} documenti elaborati con successo.")
        else:
            self.log_frame.append(
                f"Completato — {ok} riusciti, {fail} errori su {total} documenti.", "WARNING")
        self._reset_specific_output_mode_after_batch()

    def _reset_specific_output_mode_after_batch(self) -> None:
        if self.config.output_mode != "cartella":
            return
        self.config.output_mode = "accanto"
        self.options_panel.sync_from_config(self.config)
        try:
            save_config(self.config)
        except OSError:
            pass
        self.log_frame.append(
            "Destinazione output ripristinata: accanto al file originale."
        )

    # ─── Toasts ──────────────────────────────────────────────────────────
    def _show_toast(self, key, title, message, level="error"):
        try:
            self.toast_stack.show(key, title, message, level=level)
        except Exception:
            pass

    # ─── Settings / dialogs ──────────────────────────────────────────────
    def _open_settings(self) -> None:
        SettingsWindow(self, self.config, self._on_settings_saved)

    def _open_update_dialog(self) -> None:
        from gui.frames.update_dialog import UpdateDialog
        UpdateDialog(self)

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
                    creationflags=subprocess.CREATE_NO_WINDOW,
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
