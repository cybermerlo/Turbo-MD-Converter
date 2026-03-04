"""Event dataclasses for pipeline-to-GUI communication."""

import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PipelineEvent:
    """Base event for pipeline communication."""
    timestamp: float = field(default_factory=time.time)


@dataclass
class OCRProgressEvent(PipelineEvent):
    """Emitted after each page OCR completes."""
    page_num: int = 0
    total_pages: int = 0
    success: bool = True
    page_text_preview: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    page_cost: float = 0.0


@dataclass
class ExtractionStartEvent(PipelineEvent):
    """Emitted when extraction phase begins."""
    total_text_length: int = 0
    schema_name: str = ""


@dataclass
class ExtractionCompleteEvent(PipelineEvent):
    """Emitted when extraction phase completes."""
    extraction_count: int = 0


@dataclass
class OutputWrittenEvent(PipelineEvent):
    """Emitted when output files are written."""
    file_paths: list[Path] = field(default_factory=list)


@dataclass
class ErrorEvent(PipelineEvent):
    """Emitted on errors."""
    error_message: str = ""
    page_num: int | None = None
    recoverable: bool = True


@dataclass
class PipelineCompleteEvent(PipelineEvent):
    """Emitted when entire pipeline finishes for one PDF."""
    pdf_path: Path | None = None
    success: bool = True
    output_files: list[Path] = field(default_factory=list)
    cost_info: dict = field(default_factory=dict)


@dataclass
class BatchCompleteEvent(PipelineEvent):
    """Emitted when all PDFs in a batch are processed."""
    total_pdfs: int = 0
    successful: int = 0
    failed: int = 0
    total_cost: dict = field(default_factory=dict)


@dataclass
class LogEvent(PipelineEvent):
    """Generic log message event."""
    message: str = ""
    level: str = "INFO"


@dataclass
class PageSkippedEvent(PipelineEvent):
    """Emitted when a page OCR produces no text (e.g. RECITATION block)."""
    page_num: int = 0
    total_pages: int = 0
    reason: str = ""
