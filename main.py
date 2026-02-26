"""Entry point for OCR + LangExtract application."""

import sys
from pathlib import Path

# Add project root to sys.path for local imports
PROJECT_ROOT = Path(__file__).parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import load_config
from gui.app import OCRLangExtractApp
from utils.logging_config import setup_logging


def main():
    setup_logging()
    config = load_config(project_dir=PROJECT_ROOT)
    app = OCRLangExtractApp(config)
    app.mainloop()


if __name__ == "__main__":
    main()
