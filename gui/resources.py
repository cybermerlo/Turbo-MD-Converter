"""Resource path helpers that work both from source and frozen builds."""

from __future__ import annotations

import sys
from pathlib import Path


def app_base_dir() -> Path:
    """Return the directory where bundled runtime assets are expected."""
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS).resolve()  # type: ignore[attr-defined]
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def resource_path(name: str) -> Path:
    """Resolve a bundled resource such as logo.png or logo.ico."""
    candidates = [
        app_base_dir() / name,
        Path.cwd() / name,
        Path(__file__).resolve().parents[1] / name,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def app_capture_dir() -> Path:
    """Cartella visibile per input/output 'sintetici' (es. appunti incollati).

    Questi input non hanno una cartella sorgente naturale: con output mode
    "accanto" finirebbero in %TEMP%. Li raccogliamo in una sottocartella di
    Download (o Documenti, o Home) così l'utente li ritrova facilmente.
    """
    base = Path.home() / "Downloads"
    if not base.exists():
        base = Path.home() / "Documents"
    if not base.exists():
        base = Path.home()
    out = base / "Turbo MD Converter"
    out.mkdir(parents=True, exist_ok=True)
    return out
