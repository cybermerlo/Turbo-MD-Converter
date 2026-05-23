"""Plain-text extraction for document formats that need no OCR."""

import re
from pathlib import Path


def extract_docx_text(file_path: Path) -> str:
    import docx

    doc = docx.Document(file_path)
    return "\n".join(p.text for p in doc.paragraphs if p.text)


def extract_html_text(file_path: Path) -> str:
    from bs4 import BeautifulSoup

    html_content = file_path.read_text(encoding="utf-8", errors="replace")
    parts: list[str] = []

    saved_url_match = re.search(
        r'<!--\s*saved from url=\(\d+\)(.*?)\s*-->',
        html_content,
    )
    if saved_url_match:
        parts.append(f"Source URL: {saved_url_match.group(1).strip()}")

    soup = BeautifulSoup(html_content, "html.parser")

    if soup.title and soup.title.string:
        parts.append(f"Title: {soup.title.string.strip()}")

    for meta_name in ("description", "author", "keywords"):
        meta_tag = soup.find("meta", attrs={"name": lambda x: x and x.lower() == meta_name})
        if meta_tag and meta_tag.get("content"):
            parts.append(f"{meta_name.capitalize()}: {meta_tag.get('content').strip()}")

    canonical = soup.find("link", rel="canonical")
    if canonical and canonical.get("href") and not saved_url_match:
        parts.append(f"Canonical URL: {canonical.get('href').strip()}")

    if parts:
        parts.append("\n--- TESTO DEL SITO ---")

    parts.append(soup.get_text(separator="\n", strip=True))
    return "\n".join(parts)


def extract_rtf_text(file_path: Path) -> str:
    from striprtf.striprtf import rtf_to_text

    rtf_content = file_path.read_text(encoding="utf-8", errors="replace")
    return rtf_to_text(rtf_content)
