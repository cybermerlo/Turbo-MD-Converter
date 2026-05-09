"""Entry point for OCR + LangExtract application."""

import sys
from pathlib import Path

# Add project root to sys.path for local imports
PROJECT_ROOT = Path(__file__).parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import load_config
from gui.startup_splash import StartupSplash
from utils.logging_config import setup_logging


def main():
    setup_logging()
    splash = StartupSplash(PROJECT_ROOT)
    splash.set_status("Caricamento configurazione...")
    config = load_config(project_dir=PROJECT_ROOT)

    # Elabora gli argomenti da riga di comando per i file/cartelle passati (es. dal menu contestuale)
    initial_files = []
    if len(sys.argv) > 1:
        splash.set_status("Lettura file iniziali...")
        from gui.frames.input_frame import SUPPORTED_EXTENSIONS
        for arg in sys.argv[1:]:
            p = Path(arg)
            if p.is_file():
                initial_files.append(p)
            elif p.is_dir():
                for ext in SUPPORTED_EXTENSIONS:
                    initial_files.extend(p.glob(f"*{ext}"))

    splash.set_status("Preparazione interfaccia...")
    from gui.app import TurboMDConverterApp

    try:
        app = TurboMDConverterApp(config, initial_files=initial_files)
    finally:
        splash.close()
    app.mainloop()


if __name__ == "__main__":
    main()
