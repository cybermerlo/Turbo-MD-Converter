"""Formats OCR + extraction results into a Markdown document."""


class MarkdownFormatter:
    """Produces a Markdown representation of one processed document."""

    def format(
        self,
        extractions: list[dict],
        source_filename: str,
        total_pages: int,
        ocr_text: str | None = None,
        cost_info: dict | None = None,
    ) -> str:
        lines: list[str] = []

        lines.append(f"# Analisi Documento: {source_filename}")
        lines.append("")
        lines.append("---")
        lines.append("")

        # Structured extractions section (only when schema is active)
        if extractions:
            lines.append("## Estrazioni Strutturate")
            lines.append("")
            for ext in extractions:
                cls = ext.get("extraction_class", "N/D")
                text = ext.get("extraction_text", "")
                lines.append(f"- **{cls}**: {text}")
                attrs = ext.get("attributes") or {}
                for k, v in attrs.items():
                    if v is not None and str(v).strip():
                        lines.append(f"  - {k}: {v}")
            lines.append("")
            lines.append("---")
            lines.append("")

        # OCR text section
        if ocr_text:
            lines.append("## Testo OCR Originale")
            lines.append("")
            lines.append(ocr_text)
            lines.append("")

        return "\n".join(lines)
