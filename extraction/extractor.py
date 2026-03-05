"""LangExtract wrapper for structured extraction from legal text."""

import logging
import os

import langextract as lx

from config.settings import AppConfig
from extraction.schemas import SchemaPreset
from utils.cost_tracker import CostTracker

logger = logging.getLogger(__name__)


class LegalExtractor:
    """Wraps langextract for Italian legal document extraction."""

    def __init__(self, config: AppConfig, schema: SchemaPreset,
                 cost_tracker: CostTracker | None = None):
        self.config = config
        self.schema = schema
        self.cost_tracker = cost_tracker

    def extract(self, text: str) -> lx.data.AnnotatedDocument:
        """Run LangExtract on the combined OCR text.

        Args:
            text: Combined OCR text from all pages.

        Returns:
            AnnotatedDocument with all extractions.
        """
        # Ensure the environment variable is set for LangExtract
        os.environ["LANGEXTRACT_API_KEY"] = self.config.langextract_api_key

        logger.info(
            "Inizio estrazione: %d caratteri, schema='%s', passes=%d",
            len(text), self.schema.name, self.config.extraction_passes,
        )

        result = lx.extract(
            text_or_documents=text,
            prompt_description=self.schema.prompt_description,
            examples=self.schema.examples,
            model_id=self.config.extraction_model_id,
            api_key=self.config.langextract_api_key,
            extraction_passes=self.config.extraction_passes,
            max_workers=self.config.max_workers,
            max_char_buffer=self.config.max_char_buffer,
        )

        # Post-processing: deduplicate identical extractions
        if result.extractions:
            result = self._deduplicate(result)

        extraction_count = len(result.extractions) if result.extractions else 0
        logger.info("Estrazione completata: %d entita' trovate", extraction_count)

        # Estimate extraction cost based on text length
        # LangExtract makes multiple internal Gemini calls; we estimate
        # roughly 1 token per 4 chars for input, similar for output
        if self.cost_tracker:
            estimated_input = len(text) // 4 * self.config.extraction_passes
            estimated_output = extraction_count * 50  # rough estimate
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
            # Build a hashable key from the extraction's identity
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
        """Convert AnnotatedDocument to a plain dictionary.

        Returns:
            {
                "text": str,
                "extractions": [
                    {
                        "extraction_class": str,
                        "extraction_text": str,
                        "attributes": dict | None,
                        "start_pos": int | None,
                        "end_pos": int | None,
                    },
                    ...
                ]
            }
        """
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
