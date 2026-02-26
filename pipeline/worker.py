"""Threading wrapper for running pipeline in background."""

import queue
import threading
from pathlib import Path

from config.settings import AppConfig
from pipeline.events import PipelineEvent, LogEvent, ErrorEvent
from pipeline.processor import DocumentProcessor


class PipelineWorker:
    """Runs DocumentProcessor in a background thread."""

    def __init__(self, config: AppConfig, gui_queue: queue.Queue):
        self.config = config
        self.gui_queue = gui_queue
        self.cancel_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, pdf_paths: list[Path]) -> None:
        """Start processing in a daemon thread.

        All PipelineEvents are put into gui_queue for the GUI to poll.
        """
        if self.is_running():
            return

        self.cancel_event.clear()

        def event_callback(event: PipelineEvent):
            self.gui_queue.put(event)

        def run():
            try:
                processor = DocumentProcessor(self.config, event_callback)
                processor.process_batch(pdf_paths, self.cancel_event)
            except Exception as e:
                self.gui_queue.put(ErrorEvent(
                    error_message=f"Errore critico pipeline: {e}",
                    recoverable=False,
                ))
                self.gui_queue.put(LogEvent(
                    message=f"Pipeline terminata con errore: {e}",
                    level="ERROR",
                ))

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        """Signal the worker to stop after the current page."""
        self.cancel_event.set()

    def is_running(self) -> bool:
        """Check if the worker thread is alive."""
        return self._thread is not None and self._thread.is_alive()
