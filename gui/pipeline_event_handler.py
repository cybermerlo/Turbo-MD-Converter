"""Maps pipeline events from the worker queue to GUI updates."""

from __future__ import annotations

from typing import TYPE_CHECKING

from config.settings import save_config
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

if TYPE_CHECKING:
    from gui.app import TurboMDConverterApp


class PipelineEventHandler:
    """Dispatches pipeline events to the appropriate UI frames."""

    def __init__(self, app: TurboMDConverterApp) -> None:
        self.app = app

    def handle(self, event: PipelineEvent) -> None:
        if isinstance(event, OCRProgressEvent):
            self._on_ocr_progress(event)
        elif isinstance(event, (ExtractionStartEvent, ExtractionProgressEvent,
                                ExtractionCompleteEvent)):
            pass
        elif isinstance(event, PageNativeTextEvent):
            self._on_page_native_text(event)
        elif isinstance(event, PageSkippedEvent):
            self._on_page_skipped(event)
        elif isinstance(event, OutputWrittenEvent):
            self._on_output_written(event)
        elif isinstance(event, PipelineCompleteEvent):
            self._on_pipeline_complete(event)
        elif isinstance(event, BatchCompleteEvent):
            self.on_batch_complete(event)
        elif isinstance(event, FileRenamedEvent):
            self._on_file_renamed(event)
        elif isinstance(event, ErrorEvent):
            self._on_error(event)
        elif isinstance(event, LogEvent):
            self.app.log_frame.append(event.message, event.level)

    def update_total_cost(self) -> None:
        total = self.app._base_cost + self.app._current_ocr_cost
        self.app.topbar_cost_lbl.configure(text=f"${total:.4f}")
        self.app.progress_frame.update_cost(total)

    def refresh_cost_chart(self) -> None:
        rows = []
        for p, status, _cost in self.app.input_frame.get_rows():
            actual = self.app._cost_per_input.get(p, 0.0)
            rows.append((p.name, status, actual))
        self.app.options_panel.update_cost_rows(rows)

    def on_batch_complete(self, event: BatchCompleteEvent) -> None:
        app = self.app
        app.input_frame.set_enabled(True)
        app.options_panel.set_running(False)
        app.options_panel.set_can_start(bool(app.input_frame.get_file_paths()))

        ok = event.successful
        fail = event.failed
        total = event.total_pdfs
        app.progress_frame.mark_complete(ok, total, app._base_cost, failed=fail)
        if app._converted_mds:
            app.output_frame.set_all_mds(list(app._converted_mds.values()))

        if fail == 0:
            app.log_frame.append(
                f"Completato — {ok}/{total} documenti elaborati con successo."
            )
        else:
            app.log_frame.append(
                f"Completato — {ok} riusciti, {fail} errori su {total} documenti.",
                "WARNING",
            )
        self.reset_cartella_after_batch()

    def reset_cartella_after_batch(self) -> None:
        if not self.app.config.reset_cartella_if_one_shot():
            return
        self.app.options_panel.sync_from_config(self.app.config)
        try:
            save_config(self.app.config)
        except OSError:
            pass
        self.app.log_frame.append(
            "Destinazione output ripristinata: accanto al file originale."
        )

    def _on_ocr_progress(self, event: OCRProgressEvent) -> None:
        if event.page_num == 0:
            self.app._current_ocr_cost = event.page_cost
        else:
            self.app._current_ocr_cost += event.page_cost
        self.update_total_cost()

    def _on_page_native_text(self, event: PageNativeTextEvent) -> None:
        self.app.log_frame.append(
            f"Pag. {event.page_num + 1}/{event.total_pages}: "
            f"testo nativo ({event.char_count:,} car.) — OCR saltato",
            "INFO",
        )

    def _on_page_skipped(self, event: PageSkippedEvent) -> None:
        msg = (
            f"Pagina {event.page_num + 1}/{event.total_pages} senza testo. "
            f"Motivo: {event.reason}"
        )
        self.app.log_frame.append(msg, "WARNING")
        self.app._show_toast(
            key=f"skip-{event.page_num}",
            title="Pagina senza testo",
            message=msg,
            level="warning",
        )

    def _on_output_written(self, event: OutputWrittenEvent) -> None:
        if not event.file_paths:
            return
        self.app.output_frame.set_output_dir(event.file_paths[0].parent)
        for fp in event.file_paths:
            try:
                if fp.suffix == ".md":
                    if self.app.input_frame.get_selected_path() is None:
                        self.app.output_frame.show_markdown_file(fp)
            except OSError:
                pass

    def _on_pipeline_complete(self, event: PipelineCompleteEvent) -> None:
        file_cost = event.cost_info.get("total", {}).get("cost_usd", 0.0)
        self.app._base_cost += file_cost
        self.app._current_ocr_cost = 0.0
        self.app._batch_done += 1

        self.app.progress_frame.update_files(
            self.app._batch_done, self.app._batch_total, self.app._base_cost,
        )
        self.update_total_cost()

        if event.pdf_path:
            self.app._cost_per_input[event.pdf_path] = file_cost
            self.app.input_frame.set_cost_for_file(event.pdf_path, file_cost)
            if event.success:
                self.app.input_frame.set_status_for_file(event.pdf_path, "ok")
                md_files = [f for f in event.output_files if f.suffix == ".md"]
                if md_files:
                    self.app._converted_mds[event.pdf_path] = md_files[0]
                    self.app.input_frame.set_md_for_file(
                        event.pdf_path, md_files[0],
                    )
                    if self.app.input_frame.get_selected_path() == event.pdf_path:
                        self.app.output_frame.show_markdown_file(md_files[0])
            else:
                self.app.input_frame.set_status_for_file(event.pdf_path, "err")
        self.refresh_cost_chart()

    def _on_file_renamed(self, event: FileRenamedEvent) -> None:
        app = self.app
        app.log_frame.append(
            f"Rinominato ({event.file_type.upper()}): "
            f"{event.original_path.name} → {event.new_path.name}"
        )
        if event.file_type == "md" and event.original_path and event.new_path:
            for input_path, md_path in list(app._converted_mds.items()):
                if md_path == event.original_path:
                    app._converted_mds[input_path] = event.new_path
                    app.input_frame.set_md_for_file(input_path, event.new_path)
                    if app.input_frame.get_selected_path() == input_path:
                        app.output_frame.show_markdown_file(event.new_path)
                    break
        elif event.file_type == "pdf" and event.original_path and event.new_path:
            md_path = app._converted_mds.pop(event.original_path, None)
            if md_path:
                app._converted_mds[event.new_path] = md_path
            cost = app._cost_per_input.pop(event.original_path, 0.0)
            app._cost_per_input[event.new_path] = cost
            was_selected = app.input_frame.get_selected_path() == event.original_path
            app.input_frame.replace_path(event.original_path, event.new_path)
            if md_path:
                app.input_frame.set_md_for_file(event.new_path, md_path)
                if was_selected:
                    app.output_frame.show_markdown_file(md_path)
            if cost:
                app.input_frame.set_cost_for_file(event.new_path, cost)
            self.refresh_cost_chart()

    def _on_error(self, event: ErrorEvent) -> None:
        self.app.log_frame.append(event.error_message, "ERROR")
        target = getattr(event, "pdf_path", None)
        if target:
            self.app.input_frame.set_status_for_file(target, "err")
        self.app._show_toast(
            key=f"err-{target}" if target else "err-general",
            title="Errore di elaborazione",
            message=event.error_message,
            level="error",
        )
