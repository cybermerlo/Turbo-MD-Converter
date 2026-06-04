"""Writes formatted output files next to the source document (or to a fixed directory)."""

from pathlib import Path


class OutputWriter:
    """Writes output files for one document."""

    def __init__(self, output_dir: Path | None = None):
        self._output_dir = output_dir

    def _target_dir(self, pdf_path: Path) -> Path:
        if self._output_dir is not None:
            return self._output_dir
        return pdf_path.parent

    def write(
        self,
        pdf_path: Path,
        markdown: str | None = None,
        json_content: str | None = None,
        output_stem: str | None = None,
    ) -> list[Path]:
        written: list[Path] = []
        target = self._target_dir(pdf_path)
        target.mkdir(parents=True, exist_ok=True)
        stem = output_stem or pdf_path.stem

        if markdown is not None:
            md_path = target / f"{stem}.md"
            md_path.write_text(markdown, encoding="utf-8")
            written.append(md_path)

        if json_content is not None:
            json_path = target / f"{stem}.json"
            json_path.write_text(json_content, encoding="utf-8")
            written.append(json_path)

        return written
