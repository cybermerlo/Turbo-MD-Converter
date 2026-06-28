"""Application-wide logging setup."""

import logging
import sys
from pathlib import Path


def setup_logging(log_file: Path | None = None, level: int = logging.INFO) -> None:
    """Configure logging with console and optional file output."""
    # La console Windows (cp1252) non sa codificare emoji/frecce/accenti rari: i
    # nomi chat WhatsApp ne sono pieni. Senza questo, un log con quei caratteri
    # solleva UnicodeEncodeError nell'handler. UTF-8 + backslashreplace = niente crash.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except Exception:
            pass

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Clear existing handlers
    root_logger.handlers.clear()

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(formatter)
    root_logger.addHandler(console)

    # File handler (optional)
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
