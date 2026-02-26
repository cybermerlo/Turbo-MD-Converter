"""Main application window."""

import json
import queue
from pathlib import Path

import customtkinter as ctk
from tkinterdnd2 import DND_FILES, TkinterDnD

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
    ExtractionStartEvent,
    LogEvent,
    OCRProgressEvent,
    OutputWrittenEvent,
    PipelineCompleteEvent,
    PipelineEvent,
)
from pipeline.worker import PipelineWorker


class OCRLangExtractApp(ctk.CTk, TkinterDnD.DnDWrapper):
    """Main application window."""

    def __init__(self, config: AppConfig):
        super().__init__()
        self.TkdndVersion = TkinterDnD._require(self)

        self.title("OCR + LangExtract - Analisi Documenti Legali")
        self.geometry("1100x750")
        self.minsize(900, 600)
        ctk.set_appearance_mode("system")
        ctk.set_default_color_theme("blue")

        self.config = config
        self.gui_queue: queue.Queue[PipelineEvent] = queue.Queue()
        self.worker: PipelineWorker | None = None

        self._build_layout()
        self._setup_drag_drop()
        self._start_queue_polling()

    def _build_layout(self) -> None:
        """Construct the main UI layout."""
        # Top bar
        top_bar = ctk.CTkFrame(self, height=50, fg_color="transparent")
        top_bar.pack(padx=10, pady=(10, 0), fill="x")
        top_bar.pack_propagate(False)

        ctk.CTkLabel(
            top_bar,
            text="OCR + LangExtract",
            font=ctk.CTkFont(size=20, weight="bold"),
        ).pack(side="left")

        ctk.CTkButton(
            top_bar, text="Impostazioni", width=110,
            command=self._open_settings,
        ).pack(side="right")

        # Main content: two columns
        content = ctk.CTkFrame(self, fg_color="transparent")
        content.pack(padx=10, pady=10, fill="both", expand=True)
        content.grid_columnconfigure(0, weight=1, minsize=300)
        content.grid_columnconfigure(1, weight=2, minsize=500)
        content.grid_rowconfigure(0, weight=1)

        # LEFT column
        left = ctk.CTkFrame(content, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        left.grid_rowconfigure(0, weight=1)
        left.grid_rowconfigure(1, weight=0)
        left.grid_rowconfigure(2, weight=0)

        self.input_frame = InputFrame(left, on_files_changed=self._on_files_changed)
        self.input_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 5))

        # Output format
        self.output_frame_options = ctk.CTkFrame(left)
        self.output_frame_options.grid(row=1, column=0, sticky="ew", pady=5)

        format_row = ctk.CTkFrame(self.output_frame_options, fg_color="transparent")
        format_row.pack(padx=10, pady=5, fill="x")

        ctk.CTkLabel(format_row, text="Formato:", font=ctk.CTkFont(weight="bold")).pack(
            side="left", padx=(0, 10)
        )
        self.md_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(format_row, text="Markdown", variable=self.md_var).pack(
            side="left", padx=(0, 10)
        )
        self.json_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(format_row, text="JSON", variable=self.json_var).pack(
            side="left"
        )

        # Action buttons
        btn_frame = ctk.CTkFrame(left)
        btn_frame.grid(row=2, column=0, sticky="ew", pady=(5, 0))

        self.start_btn = ctk.CTkButton(
            btn_frame, text="Avvia Elaborazione",
            command=self._start_processing,
            font=ctk.CTkFont(size=14, weight="bold"),
            height=40,
            state="disabled",
        )
        self.start_btn.pack(padx=10, pady=10, fill="x")

        self.cancel_btn = ctk.CTkButton(
            btn_frame, text="Annulla",
            command=self._cancel_processing,
            fg_color="firebrick", hover_color="darkred",
            state="disabled",
        )
        self.cancel_btn.pack(padx=10, pady=(0, 10), fill="x")

        # RIGHT column
        right = ctk.CTkFrame(content, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        right.grid_rowconfigure(0, weight=0)
        right.grid_rowconfigure(1, weight=1)
        right.grid_rowconfigure(2, weight=0)

        self.progress_frame = ProgressFrame(right)
        self.progress_frame.grid(row=0, column=0, sticky="ew", pady=(0, 5))

        self.output_frame = OutputFrame(right)
        self.output_frame.grid(row=1, column=0, sticky="nsew", pady=5)

        self.log_frame = LogFrame(right)
        self.log_frame.grid(row=2, column=0, sticky="ew", pady=(5, 0))

        right.grid_columnconfigure(0, weight=1)

    def _setup_drag_drop(self) -> None:
        """Register the PDF input area as drag & drop target for files."""
        self.input_frame.drop_target_register(DND_FILES)
        self.input_frame.dnd_bind("<<Drop>>", self._on_drop_files)

    def _on_drop_files(self, event) -> None:
        """Handle files dropped on the input frame (only PDFs are added)."""
        if not event.data:
            return
        try:
            raw = event.data.strip().strip("{}")
            paths = self.tk.splitlist(raw) if raw else []
        except Exception:
            paths = [event.data.replace("{", "").replace("}", "").strip()]
        path_objs = [Path(p) for p in paths if p]
        self.input_frame.add_paths(path_objs)
        return event.action

    def _start_queue_polling(self) -> None:
        """Poll the event queue every 100ms."""
        try:
            while True:
                event = self.gui_queue.get_nowait()
                self._handle_event(event)
        except queue.Empty:
            pass
        self.after(100, self._start_queue_polling)

    def _handle_event(self, event: PipelineEvent) -> None:
        """Route events to appropriate frame updates."""
        if isinstance(event, OCRProgressEvent):
            self.progress_frame.update_ocr(
                event.page_num, event.total_pages, event.success,
            )
            # Update cost
            total_tokens = event.input_tokens + event.output_tokens
            self.progress_frame.update_cost(total_tokens, event.page_cost)

        elif isinstance(event, ExtractionStartEvent):
            self.progress_frame.update_extraction_start(
                event.total_text_length, event.schema_name,
            )

        elif isinstance(event, ExtractionCompleteEvent):
            self.progress_frame.update_extraction_complete(event.extraction_count)

        elif isinstance(event, OutputWrittenEvent):
            if event.file_paths:
                self.output_frame.set_output_dir(event.file_paths[0].parent)
                # Load and display the files
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

        elif isinstance(event, BatchCompleteEvent):
            self._on_batch_complete(event)

        elif isinstance(event, ErrorEvent):
            self.log_frame.append(event.error_message, "ERROR")

        elif isinstance(event, LogEvent):
            self.log_frame.append(event.message, event.level)

    def _on_files_changed(self, paths: list[Path]) -> None:
        """Called when the file selection changes."""
        has_files = len(paths) > 0
        self.start_btn.configure(state="normal" if has_files else "disabled")

    def _start_processing(self) -> None:
        """Start the pipeline worker."""
        pdf_paths = self.input_frame.get_pdf_paths()
        if not pdf_paths:
            return

        if not self.config.gemini_api_key:
            self.log_frame.append(
                "Chiave API Gemini non configurata. Apri Impostazioni.", "ERROR"
            )
            return

        # Update output formats from checkboxes
        formats = []
        if self.md_var.get():
            formats.append("markdown")
        if self.json_var.get():
            formats.append("json")
        if not formats:
            self.log_frame.append("Seleziona almeno un formato di output.", "WARNING")
            return
        self.config.output_formats = formats

        # Reset UI
        self.progress_frame.reset()
        self.output_frame.clear()
        self.log_frame.clear()

        # Disable controls
        self.input_frame.set_enabled(False)
        self.start_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")

        # Start worker
        self.worker = PipelineWorker(self.config, self.gui_queue)
        self.worker.start(pdf_paths)

        self.log_frame.append(f"Avviata elaborazione di {len(pdf_paths)} documenti")

    def _cancel_processing(self) -> None:
        """Cancel the running pipeline."""
        if self.worker:
            self.worker.cancel()
            self.log_frame.append("Annullamento in corso...", "WARNING")

    def _on_batch_complete(self, event: BatchCompleteEvent) -> None:
        """Handle batch completion."""
        self.input_frame.set_enabled(True)
        self.start_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")

        self.log_frame.append(
            f"Batch completato: {event.successful}/{event.total_pdfs} riusciti, "
            f"{event.failed} falliti"
        )

    def _open_settings(self) -> None:
        """Open the settings dialog."""
        SettingsWindow(self, self.config, self._on_settings_saved)

    def _on_settings_saved(self, config: AppConfig) -> None:
        """Called when settings are saved."""
        self.config = config
        save_config(config)
        self.log_frame.append("Impostazioni salvate")
