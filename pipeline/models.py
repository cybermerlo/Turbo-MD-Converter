"""Shared pipeline data models."""

from dataclasses import dataclass, field


@dataclass
class EmailAttachmentDocument:
    index: int
    filename: str
    text: str
    extractions: list[dict] = field(default_factory=list)
