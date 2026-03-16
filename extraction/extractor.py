"""LangExtract wrapper for structured extraction from legal text."""

import logging
import math
import os
from typing import Callable

import langextract as lx
import langextract.progress as lx_progress

from config.settings import AppConfig
from extraction.schemas import SchemaPreset
from utils.cost_tracker import CostTracker

logger = logging.getLogger(__name__)


class _ProgressInterceptor:
    """Wraps a batch iterator to intercept per-batch progress from LangExtract.

    Replaces the tqdm progress bar that LangExtract creates internally,
    forwarding iteration counts to an external callback.
    """

    def __init__(self, iterable, total_chunks: int, total_chars: int,
                 pass_num: int, total_passes: int,
                 callback: Callable | None = None):
        self._iterable = iterable
        self._total_chunks = total_chunks
        self._total_chars = total_chars
        self._pass_num = pass_num
        self._total_passes = total_passes
        self._callback = callback
        self._chunks_done = 0
        self._chars_processed = 0

    def __iter__(self):
        for batch in self._iterable:
            yield batch
            # Each batch contains N text chunks; count them
            batch_size = len(batch) if hasattr(batch, '__len__') else 1
            self._chunks_done += batch_size
            # Estimate chars processed proportionally
            self._chars_processed = min(
                int(self._total_chars * self._chunks_done / max(self._total_chunks, 1)),
                self._total_chars,
            )
            if self._callback:
                self._callback(
                    chunks_done=self._chunks_done,
                    total_chunks=self._total_chunks,
                    chars_processed=self._chars_processed,
                    total_chars=self._total_chars,
                    pass_num=self._pass_num,
                    total_passes=self._total_passes,
                )

    def set_description(self, desc: str) -> None:
        """No-op: satisfies tqdm API used by langextract."""

    def close(self) -> None:
        """No-op: satisfies tqdm API used by langextract."""


class LegalExtractor:
    """Wraps langextract for Italian legal document extraction."""

    def __init__(self, config: AppConfig, schema: SchemaPreset,
                 cost_tracker: CostTracker | None = None):
        self.config = config
        self.schema = schema
        self.cost_tracker = cost_tracker
        self._progress_callback: Callable | None = None
        self._current_pass = 1
        self._total_passes = 1
        self._total_chunks = 0
        self._total_chars = 0

    def set_progress_callback(self, callback: Callable | None) -> None:
        """Set a callback for extraction progress updates.

        Callback signature: (chunks_done, total_chunks, chars_processed,
                             total_chars, pass_num, total_passes) -> None
        """
        self._progress_callback = callback

    def extract(self, text: str) -> lx.data.AnnotatedDocument:
        """Run LangExtract on the combined OCR text.

        Args:
            text: Combined OCR text from all pages.

        Returns:
            AnnotatedDocument with all extractions.
        """
        # Ensure the environment variable is set for LangExtract
        os.environ["LANGEXTRACT_API_KEY"] = self.config.langextract_api_key

        max_char_buffer = self.config.max_char_buffer
        batch_length = max(self.config.max_workers, 10)
        passes = self.config.extraction_passes

        # Pre-calculate chunking info for progress tracking
        self._total_chunks = math.ceil(len(text) / max_char_buffer) if max_char_buffer > 0 else 1
        self._total_chars = len(text)
        self._total_passes = passes
        self._current_pass = 1

        logger.info(
            "Inizio estrazione: %d caratteri, %d chunk stimati (buffer=%d), "
            "schema='%s', passes=%d, workers=%d, batch_length=%d",
            len(text), self._total_chunks, max_char_buffer,
            self.schema.name, passes, self.config.max_workers, batch_length,
        )

        # Monkey-patch langextract's progress bar factory to intercept progress
        original_create_bar = lx_progress.create_extraction_progress_bar
        extractor_ref = self

        def _patched_progress_bar(iterable, model_info=None, disable=False):
            interceptor = _ProgressInterceptor(
                iterable,
                total_chunks=extractor_ref._total_chunks,
                total_chars=extractor_ref._total_chars,
                pass_num=extractor_ref._current_pass,
                total_passes=extractor_ref._total_passes,
                callback=extractor_ref._progress_callback,
            )
            extractor_ref._current_pass += 1
            return interceptor

        try:
            lx_progress.create_extraction_progress_bar = _patched_progress_bar

            result = lx.extract(
                text_or_documents=text,
                prompt_description=self.schema.prompt_description,
                examples=self.schema.examples,
                model_id=self.config.extraction_model_id,
                api_key=self.config.langextract_api_key,
                extraction_passes=passes,
                max_workers=self.config.max_workers,
                max_char_buffer=max_char_buffer,
                batch_length=batch_length,
                show_progress=True,  # kept True so our interceptor gets called
            )
        finally:
            lx_progress.create_extraction_progress_bar = original_create_bar

        # Post-processing: deduplicate identical extractions
        if result.extractions:
            result = self._deduplicate(result)

        extraction_count = len(result.extractions) if result.extractions else 0
        logger.info("Estrazione completata: %d entita' trovate", extraction_count)

        # Estimate extraction cost based on text length
        if self.cost_tracker:
            estimated_input = len(text) // 4 * passes
            estimated_output = extraction_count * 50
            self.cost_tracker.add_call(
                model_id=self.config.extraction_model_id,
                input_tokens=estimated_input,
                output_tokens=estimated_output,
                phase="extraction",
            )

        return result

    @staticmethod
    def _deduplicate(result: lx.data.AnnotatedDocument) -> lx.data.AnnotatedDocument:
        """Remove duplicate extractions with identical class, text, and attributes."""
        if not result.extractions:
            return result

        seen = set()
        unique = []
        for ext in result.extractions:
            attr_key = tuple(sorted(ext.attributes.items())) if ext.attributes else ()
            key = (ext.extraction_class, ext.extraction_text.strip(), attr_key)
            if key not in seen:
                seen.add(key)
                unique.append(ext)

        removed = len(result.extractions) - len(unique)
        if removed > 0:
            logger.info("Deduplicazione: rimossi %d duplicati su %d estrazioni",
                        removed, len(result.extractions))

        result.extractions = unique
        return result

    @staticmethod
    def result_to_dict(result: lx.data.AnnotatedDocument) -> dict:
        """Convert AnnotatedDocument to a plain dictionary."""
        extractions = []
        if result.extractions:
            for ext in result.extractions:
                entry = {
                    "extraction_class": ext.extraction_class,
                    "extraction_text": ext.extraction_text,
                    "attributes": ext.attributes,
                }
                if ext.char_interval:
                    entry["start_pos"] = ext.char_interval.start_pos
                    entry["end_pos"] = ext.char_interval.end_pos
                else:
                    entry["start_pos"] = None
                    entry["end_pos"] = None
                extractions.append(entry)

        return {
            "text": result.text,
            "extractions": extractions,
        }
