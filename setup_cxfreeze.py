# -*- coding: utf-8 -*-
"""
Setup cx_Freeze – genera la cartella build/ con l'eseguibile Windows.
Chiamato da build_installer.py; puoi anche eseguirlo direttamente:

    python setup_cxfreeze.py build
"""

import sys
from pathlib import Path
from cx_Freeze import setup, Executable

# Importa metadati centralizzati (aggiornati da build_installer.py)
from version import APP_NAME, APP_EXE_NAME, APP_PUBLISHER, VERSION

sys.setrecursionlimit(5000)

PROJECT_ROOT = Path(__file__).parent
ICON_PATH    = PROJECT_ROOT / "logo.ico"

# ffmpeg (da imageio-ffmpeg) per rimuovere la traccia audio dai video prima di
# inviarli a Gemini. Impacchettiamo il binario in ffmpeg/ffmpeg.exe accanto
# all'eseguibile; utils/ffmpeg_tools.py lo cerca proprio lì nel build freezato.
try:
    import imageio_ffmpeg
    _ffmpeg_src = imageio_ffmpeg.get_ffmpeg_exe()
    ffmpeg_include_files = [(_ffmpeg_src, "ffmpeg/ffmpeg.exe")]
except Exception as _e:  # binario assente: il video describer degraderà a runtime
    print(f"[setup] Attenzione: ffmpeg non impacchettato ({_e})")
    ffmpeg_include_files = []

# ── Pacchetti con import dinamici che cx_Freeze non traccia da solo ──────────
build_exe_options = {
    "packages": [
        "customtkinter",
        "customtkinter.windows",
        "langextract",
        "google",
        "google.genai",
        "opentelemetry",
        "opentelemetry.context",
        "fitz",          # PyMuPDF
        "PIL",
        "PIL._tkinter_finder",
        "dotenv",
        "tkinterdnd2",
        "elevenlabs",
        "Cryptodome",       # usato da py7zr per gli archivi .7z
        "cryptography",     # decifratura WhatsApp Desktop (AES) + transitive
        "google.protobuf",  # transitiva di google-genai / langextract
        "sqlite3",
        # moduli dell'app
        "config",
        "gui",
        "ocr",
        "extraction",
        "pipeline",
        "output",
        "utils",
        "whatsapp",
        # Lettore IndexedDB vendorizzato (import differito + relativi: lo
        # elenchiamo esplicitamente così cx_Freeze lo impacchetta sicuramente).
        "whatsapp._vendor",
        "whatsapp._vendor.ccl_chromium_reader",
        "whatsapp._vendor.ccl_chromium_reader.serialization_formats",
        "whatsapp._vendor.ccl_chromium_reader.storage_formats",
    ],
    # Include esplicito per import dinamico usato da opentelemetry context loader.
    "includes": [
        "opentelemetry.context.contextvars_context",
    ],
    "include_files": [
        # Icone / loghi
        (str(ICON_PATH), "logo.ico"),
        (str(PROJECT_ROOT / "logo.png"), "logo.png"),
    ] + ffmpeg_include_files,
    "excludes": [
        "test", "unittest", "email.test",
        "tkinter.test",
    ],
    "optimize": 1,
    # Includi tutti i subpackage automaticamente
    "include_msvcr": True,
}

# ── Base: nasconde la console per le app GUI ──────────────────────────────────
if sys.platform == "win32":
    # cx_Freeze 8.x su Python 3.13+ usa "gui"; versioni precedenti usano "Win32GUI"
    base = "gui" if sys.version_info >= (3, 13) else "Win32GUI"
else:
    base = None

executables = [
    Executable(
        script="main.py",
        base=base,
        target_name=f"{APP_EXE_NAME}.exe",
        icon=str(ICON_PATH) if ICON_PATH.exists() else None,
        copyright=f"© {VERSION[:4]} {APP_PUBLISHER}",
    )
]

setup(
    name=APP_NAME,
    version=VERSION,
    description=f"{APP_NAME} – Conversione OCR e estrazione da documenti",
    author=APP_PUBLISHER,
    options={"build_exe": build_exe_options},
    executables=executables,
)
