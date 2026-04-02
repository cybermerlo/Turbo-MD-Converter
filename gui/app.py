import json
import queue
import tkinter as tk
from pathlib import Path

import customtkinter as ctk
from tkinterdnd2 import DND_FILES, TkinterDnD

from config.defaults import AVAILABLE_OCR_MODELS, SCHEMA_PRESET_NAMES

_RENAME_MODE_LABELS = {"md": "Solo MD", "pdf": "Solo PDF", "both": "Entrambi"}
_RENAME_LABEL_TO_MODE = {v: k for k, v in _RENAME_MODE_LABELS.items()}
from config.settings import AppConfig, load_config, save_config
from gui.frames.input_frame import InputFrame
from gui.frames.log_frame import LogFrame
from gui.frames.output_frame import OutputFrame
from gui.frames.progress_frame import ProgressFrame
from gui.frames.settings_frame import SettingsWindow
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

_FONT_BOLD = ("", 13, "bold")


def _section_label(parent, text: str) -> ctk.CTkLabel:
    """Small uppercase section header."""
    return ctk.CTkLabel(
        parent, text=text.upper(),
        font=ctk.CTkFont(size=10, weight="bold"),
        text_color="gray60",
    )


class OCRLangExtractApp(ctk.CTk, TkinterDnD.DnDWrapper):
    """Main application window."""

    def __init__(self, config: AppConfig, initial_files: list[Path] | None = None):
        super().__init__()
        self.TkdndVersion = TkinterDnD._require(self)

        self.title("OCR + LangExtract")
        self.geometry("1140x780")
        self.minsize(960, 620)
        ctk.set_appearance_mode("system")
        ctk.set_default_color_theme("blue")

        self.config = config
        self.gui_queue: queue.Queue[PipelineEvent] = queue.Queue()
        self.worker: PipelineWorker | None = None

        self._build_layout()
        self._setup_drag_drop()
        self._start_queue_polling()

        if initial_files:
            self.after(100, lambda: self.input_frame.add_paths(initial_files))

        self.after(500, self._check_sendto_shortcut)

    # ─── Layout ──────────────────────────────────────────────────────────────

    def _build_layout(self) -> None:
        """Construct the main UI layout."""
        # ── Top bar ──────────────────────────────────────────────────────────
        top_bar = ctk.CTkFrame(self, height=52, fg_color="transparent")
        top_bar.pack(padx=14, pady=(12, 0), fill="x")
        top_bar.pack_propagate(False)

        ctk.CTkLabel(
            top_bar,
            text="OCR + LangExtract",
            font=ctk.CTkFont(size=20, weight="bold"),
        ).pack(side="left")

        ctk.CTkButton(
            top_bar, text="Impostazioni", width=110,
            command=self._open_settings,
        ).pack(side="right", pady=8)

        # ── Two-column content ────────────────────────────────────────────────
        content = ctk.CTkFrame(self, fg_color="transparent")
        content.pack(padx=14, pady=(8, 12), fill="both", expand=True)
        content.grid_columnconfigure(0, weight=3, minsize=300)
        content.grid_columnconfigure(1, weight=5, minsize=520)
        content.grid_rowconfigure(0, weight=1)

        # LEFT column
        left = ctk.CTkFrame(content, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        left.grid_rowconfigure(0, weight=1)   # file list expands
        left.grid_rowconfigure(1, weight=0)   # options card
        left.grid_rowconfigure(2, weight=0)   # action buttons

        self.input_frame = InputFrame(left, on_files_changed=self._on_files_changed)
        self.input_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 6))
        left.grid_columnconfigure(0, weight=1)

        self._build_options_card(left)
        self._build_action_buttons(left)

        # RIGHT column
        right = ctk.CTkFrame(content, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        right.grid_rowconfigure(0, weight=0)
        right.grid_rowconfigure(1, weight=1)
        right.grid_rowconfigure(2, weight=0)
        right.grid_columnconfigure(0, weight=1)

        self.progress_frame = ProgressFrame(right)
        self.progress_frame.grid(row=0, column=0, sticky="ew", pady=(0, 6))

        self.output_frame = OutputFrame(right)
        self.output_frame.grid(row=1, column=0, sticky="nsew", pady=(0, 6))

        self.log_frame = LogFrame(right)
        self.log_frame.grid(row=2, column=0, sticky="ew")

        # Apply initial greyed states
        self._on_phases_changed()
        self._on_rename_changed()

    def _build_options_card(self, parent) -> None:
        """Build the compact options card below the file list."""
        card = ctk.CTkFrame(parent)
        card.grid(row=1, column=0, sticky="ew", pady=(0, 6))

        _section_label(card, "Operazioni").pack(padx=12, pady=(10, 4), anchor="w")

        # ── Modello AI (shared by all features) ──────────────────────────────
        model_row = ctk.CTkFrame(card, fg_color="transparent")
        model_row.pack(padx=12, pady=(0, 6), fill="x")

        ctk.CTkLabel(model_row, text="Modello AI:").pack(side="left", padx=(0, 8))
        self.model_var = ctk.StringVar(
            value=self.config.ocr_model_id
            if self.config.ocr_model_id in AVAILABLE_OCR_MODELS
            else AVAILABLE_OCR_MODELS[0]
        )
        self.model_menu = ctk.CTkOptionMenu(
            model_row, values=AVAILABLE_OCR_MODELS,
            variable=self.model_var, width=220,
        )
        self.model_menu.pack(side="right")

        # ── Divider ───────────────────────────────────────────────────────────
        ctk.CTkFrame(card, height=1, fg_color="gray30").pack(padx=12, pady=(0, 6), fill="x")

        # ── OCR ───────────────────────────────────────────────────────────────
        ocr_row = ctk.CTkFrame(card, fg_color="transparent")
        ocr_row.pack(padx=12, pady=2, fill="x")

        self.run_ocr_var = ctk.BooleanVar(value=self.config.run_ocr)
        self.run_ocr_cb = ctk.CTkCheckBox(
            ocr_row, text="OCR — estrai testo",
            variable=self.run_ocr_var,
            command=self._on_phases_changed,
        )
        self.run_ocr_cb.pack(side="left")

        # ── Estrazione strutturata ────────────────────────────────────────────
        ext_row = ctk.CTkFrame(card, fg_color="transparent")
        ext_row.pack(padx=12, pady=2, fill="x")

        self.run_extraction_var = ctk.BooleanVar(value=self.config.run_extraction)
        self.run_extraction_cb = ctk.CTkCheckBox(
            ext_row, text="Estrazione strutturata",
            variable=self.run_extraction_var,
            command=self._on_phases_changed,
        )
        self.run_extraction_cb.pack(side="left")

        self.schema_var = ctk.StringVar(value=self.config.active_schema)
        self.schema_menu = ctk.CTkOptionMenu(
            ext_row, values=SCHEMA_PRESET_NAMES,
            variable=self.schema_var, width=140,
        )
        self.schema_menu.pack(side="right")

        # ── Rinomina ──────────────────────────────────────────────────────────
        rename_row = ctk.CTkFrame(card, fg_color="transparent")
        rename_row.pack(padx=12, pady=2, fill="x")

        self.rename_files_var = ctk.BooleanVar(value=self.config.rename_files)
        self.rename_cb = ctk.CTkCheckBox(
            rename_row, text="Rinomina file automaticamente",
            variable=self.rename_files_var,
            command=self._on_rename_changed,
        )
        self.rename_cb.pack(side="left")

        self.rename_mode_var = ctk.StringVar(
            value=_RENAME_MODE_LABELS.get(self.config.rename_mode, "Entrambi")
        )
        self.rename_mode_menu = ctk.CTkOptionMenu(
            rename_row, values=list(_RENAME_MODE_LABELS.values()),
            variable=self.rename_mode_var, width=100,
        )
        self.rename_mode_menu.pack(side="right")

        # ── Divider ───────────────────────────────────────────────────────────
        ctk.CTkFrame(card, height=1, fg_color="gray30").pack(padx=12, pady=(8, 4), fill="x")

        # ── Output mode ───────────────────────────────────────────────────────
        _section_label(card, "Destinazione output").pack(padx=12, pady=(4, 2), anchor="w")

        self.output_mode_var = ctk.StringVar(value=self.config.output_mode)

        modes = [
            ("accanto",       "Accanto al file originale"),
            ("sottocartella", f'Sottocartella "{self.config.output_subfolder_name}"'),
            ("cartella",      "Cartella specifica…"),
        ]
        for value, label in modes:
            ctk.CTkRadioButton(
                card, text=label,
                variable=self.output_mode_var, value=value,
                command=self._on_output_mode_changed,
            ).pack(padx=20, pady=1, anchor="w")

        # Row shown only in "cartella" mode
        self._cartella_row = ctk.CTkFrame(card, fg_color="transparent")
        self._cartella_row.pack(padx=12, pady=(2, 0), fill="x")

        self._cartella_label = ctk.CTkLabel(
            self._cartella_row,
            text=self._short_dir_label(self.config.output_directory),
            font=ctk.CTkFont(size=11),
            text_color="gray50",
        )
        self._cartella_label.pack(side="left", fill="x", expand=True)

        ctk.CTkButton(
            self._cartella_row, text="Scegli…", width=70,
            command=self._pick_output_folder,
        ).pack(side="right")

        ctk.CTkFrame(card, height=6, fg_color="transparent").pack()

        self._on_output_mode_changed()

    def _build_action_buttons(self, parent) -> None:
        """Build start/cancel buttons."""
        btn_frame = ctk.CTkFrame(parent, fg_color="transparent")
        btn_frame.grid(row=2, column=0, sticky="ew")

        self.start_btn = ctk.CTkButton(
            btn_frame,
            text="Elabora documenti",
            command=self._start_processing,
            font=ctk.CTkFont(size=14, weight="bold"),
            height=42,
            state="disabled",
        )
        self.start_btn.pack(fill="x", pady=(0, 4))

        self.cancel_btn = ctk.CTkButton(
            btn_frame,
            text="Interrompi",
            command=self._cancel_processing,
            fg_color="firebrick",
            hover_color="darkred",
            height=34,
            state="disabled",
        )
        self.cancel_btn.pack(fill="x")

    # ─── Drag & drop ─────────────────────────────────────────────────────────

    def _setup_drag_drop(self) -> None:
        self.input_frame.drop_target_register(DND_FILES)
        self.input_frame.dnd_bind("<<Drop>>", self._on_drop_files)

    def _on_drop_files(self, event) -> None:
        if not event.data:
            return
        try:
            paths = self.tk.splitlist(event.data)
        except Exception:
            paths = [event.data.strip()]

        path_objs = []
        for p in paths:
            p = p.strip()
            if not p:
                continue
            if p.startswith("file://"):
                import urllib.parse
                import urllib.request
                p = urllib.request.url2pathname(urllib.parse.urlparse(p).path)
            path_objs.append(Path(p))

        self.input_frame.add_paths(path_objs)
        return event.action

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
        """Route pipeline events to the appropriate UI components."""
        if isinstance(event, OCRProgressEvent):
            self.progress_frame.update_ocr(
                event.page_num, event.total_pages, event.success,
            )
            total_tokens = event.input_tokens + event.output_tokens
            self.progress_frame.update_cost(total_tokens, event.page_cost)

        elif isinstance(event, ExtractionStartEvent):
            self.progress_frame.update_extraction_start(
                event.total_text_length, event.schema_name,
            )

        elif isinstance(event, ExtractionProgressEvent):
            self.progress_frame.update_extraction_progress(
                event.chunks_done, event.total_chunks,
                event.chars_processed, event.total_chars,
                event.pass_num, event.total_passes,
            )

        elif isinstance(event, ExtractionCompleteEvent):
            self.progress_frame.update_extraction_complete(event.extraction_count)

        elif isinstance(event, PageNativeTextEvent):
            self.log_frame.append(
                f"Pag. {event.page_num + 1}/{event.total_pages}: "
                f"testo nativo ({event.char_count:,} car.) — OCR saltato",
                "INFO",
            )

        elif isinstance(event, PageSkippedEvent):
            msg = (
                f"Pagina {event.page_num + 1}/{event.total_pages} senza testo\n"
                f"Motivo: {event.reason}"
            )
            self.log_frame.append(msg, "WARNING")
            self.after(0, lambda m=msg: tk.messagebox.showwarning(
                title="Pagina senza testo", message=m,
            ))

        elif isinstance(event, OutputWrittenEvent):
            if event.file_paths:
                self.output_frame.set_output_dir(event.file_paths[0].parent)
                for fp in event.file_paths:
                    try:
                        content = fp.read_text(encoding="utf-8")
                        if fp.suffix == ".md":
                            self.output_frame.show_markdown(content)
                        elif fp.suffix == ".json":
                            self.output_frame.show_json(content)
                    except OSError:
                        pass

        elif isinstance(event, PipelineCompleteEvent):
            if event.success:
                cost = event.cost_info.get("total", {})
                total_tok = cost.get("input_tokens", 0) + cost.get("output_tokens", 0)
                self.progress_frame.update_cost(total_tok, cost.get("cost_usd", 0))
                self.progress_frame.update_cost_breakdown(event.cost_info)

        elif isinstance(event, BatchCompleteEvent):
            self._on_batch_complete(event)

        elif isinstance(event, FileRenamedEvent):
            self.log_frame.append(
                f"Rinominato ({event.file_type.upper()}): "
                f"{event.original_path.name} → {event.new_path.name}"
            )

        elif isinstance(event, ErrorEvent):
            self.log_frame.append(event.error_message, "ERROR")

        elif isinstance(event, LogEvent):
            self.log_frame.append(event.message, event.level)

    # ─── Processing ──────────────────────────────────────────────────────────

    def _on_files_changed(self, paths: list[Path]) -> None:
        has_files = len(paths) > 0
        self.start_btn.configure(state="normal" if has_files else "disabled")

    def _start_processing(self) -> None:
        pdf_paths = self.input_frame.get_file_paths()
        if not pdf_paths:
            return

        run_ocr = self.run_ocr_var.get()
        run_extraction = self.run_extraction_var.get()

        if not run_ocr and not run_extraction:
            self.log_frame.append(
                "Seleziona almeno un'operazione (OCR o Estrazione strutturata).", "ERROR"
            )
            return

        from pipeline.processor import IMAGE_EXTENSIONS
        needs_ocr = any(
            p.suffix.lower() in (".pdf",) + IMAGE_EXTENSIONS for p in pdf_paths
        )
        needs_api_key = (needs_ocr and run_ocr) or run_extraction
        if not self.config.gemini_api_key and needs_api_key:
            self.log_frame.append(
                "Chiave API Gemini non configurata. Aprire le Impostazioni.", "ERROR"
            )
            return

        # Sync config from UI
        self.config.run_ocr = run_ocr
        self.config.run_extraction = run_extraction
        self.config.ocr_model_id = self.model_var.get()
        self.config.extraction_model_id = self.model_var.get()
        self.config.active_schema = self.schema_var.get()
        self.config.rename_files = self.rename_files_var.get()
        self.config.rename_mode = _RENAME_LABEL_TO_MODE.get(self.rename_mode_var.get(), "both")
        self.config.output_mode = self.output_mode_var.get()
        self.config.output_formats = ["markdown"]

        # Reset UI
        self.progress_frame.reset()
        self.output_frame.clear()
        self.log_frame.clear()

        self.input_frame.set_enabled(False)
        self.start_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")

        self.worker = PipelineWorker(self.config, self.gui_queue)
        self.worker.start(pdf_paths)

        n = len(pdf_paths)
        doc_word = "documento" if n == 1 else "documenti"
        phases = []
        if run_ocr:
            phases.append(f"OCR [{self.config.ocr_model_id}]")
        if run_extraction:
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
        self.start_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")

        ok = event.successful
        fail = event.failed
        total = event.total_pdfs
        if fail == 0:
            self.log_frame.append(f"Completato — {ok}/{total} documenti elaborati con successo.")
        else:
            self.log_frame.append(
                f"Completato — {ok} riusciti, {fail} errori su {total} documenti.", "WARNING"
            )

    # ─── Settings ────────────────────────────────────────────────────────────

    def _open_settings(self) -> None:
        SettingsWindow(self, self.config, self._on_settings_saved)

    def _on_settings_saved(self, config: AppConfig) -> None:
        self.config = config
        self.run_ocr_var.set(config.run_ocr)
        self.run_extraction_var.set(config.run_extraction)
        self.model_var.set(config.ocr_model_id)
        self.schema_var.set(config.active_schema)
        self.rename_files_var.set(config.rename_files)
        self.rename_mode_var.set(_RENAME_MODE_LABELS.get(config.rename_mode, "Entrambi"))
        self.output_mode_var.set(config.output_mode)
        self._cartella_label.configure(text=self._short_dir_label(config.output_directory))
        self._on_output_mode_changed()
        self._on_rename_changed()
        self._on_phases_changed()
        save_config(config)
        self.log_frame.append("Impostazioni salvate.")

    # ─── UI state helpers ────────────────────────────────────────────────────

    def _on_phases_changed(self) -> None:
        """Enable/disable model and schema dropdowns based on active features."""
        ocr_on = self.run_ocr_var.get()
        ext_on = self.run_extraction_var.get()
        rename_on = self.rename_files_var.get()
        model_state = "normal" if (ocr_on or ext_on or rename_on) else "disabled"
        self.model_menu.configure(state=model_state)
        self.schema_menu.configure(state="normal" if ext_on else "disabled")

    def _on_rename_changed(self) -> None:
        """Enable/disable rename mode dropdown."""
        state = "normal" if self.rename_files_var.get() else "disabled"
        self.rename_mode_menu.configure(state=state)
        self._on_phases_changed()

    def _on_output_mode_changed(self) -> None:
        """Show/hide the folder-picker row based on the selected output mode."""
        mode = self.output_mode_var.get()
        if mode == "cartella":
            self._cartella_row.pack(padx=12, pady=(2, 0), fill="x")
        else:
            self._cartella_row.pack_forget()

    def _pick_output_folder(self) -> None:
        from tkinter import filedialog
        folder = filedialog.askdirectory(title="Seleziona cartella di output")
        if folder:
            self.config.output_directory = folder
            self._cartella_label.configure(text=self._short_dir_label(folder))

    @staticmethod
    def _short_dir_label(path: str, maxlen: int = 40) -> str:
        if not path:
            return "Nessuna cartella selezionata"
        p = path.replace("\\", "/")
        return f"…{p[-(maxlen-1):]}" if len(p) > maxlen else p

    # ─── SendTo shortcut ─────────────────────────────────────────────────────

    def _check_sendto_shortcut(self) -> None:
        import sys
        import os
        import subprocess
        from tkinter import messagebox

        if not getattr(sys, "frozen", False):
            return

        sendto_dir = Path(os.path.expandvars(r"%APPDATA%\Microsoft\Windows\SendTo"))
        shortcut_path = sendto_dir / "OCR+Langextract.lnk"

        if shortcut_path.exists():
            if not self.config.asked_sendto:
                self.config.asked_sendto = True
                save_config(self.config)
            return

        if self.config.asked_sendto:
            return

        response = messagebox.askyesno(
            "Integrazione Windows",
            "Aggiungere 'OCR+Langextract' al menu 'Invia a' di Windows?\n\n"
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
oLink.Description = "Invia a OCR+Langextract"
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
                messagebox.showinfo(
                    "Successo",
                    "Collegamento aggiunto con successo al menu 'Invia a'.",
                    parent=self,
                )
            except Exception as e:
                self.log_frame.append(
                    f"Impossibile creare il collegamento: {e}", "ERROR"
                )
            finally:
                if vbs_path.exists():
                    vbs_path.unlink()

        self.config.asked_sendto = True
        save_config(self.config)
