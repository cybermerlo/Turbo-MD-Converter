"""Formats OCR + extraction results into a JSON document."""

import json


class JsonFormatter:
    """Produces a JSON representation of one processed document."""

    def format(
        self,
        extractions: list[dict],
        source_filename: str,
        total_pages: int,
        ocr_text: str | None = None,
        cost_info: dict | None = None,
    ) -> str:
        payload = {
            "source_filename": source_filename,
            "total_pages": total_pages,
            "extractions": extractions,
        }

        if ocr_text is not None:
            payload["ocr_text"] = ocr_text
        if cost_info is not None:
            payload["cost_info"] = cost_info

        return json.dumps(payload, ensure_ascii=False, indent=2)
