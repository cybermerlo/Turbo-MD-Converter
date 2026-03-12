# -*- coding: utf-8 -*-
"""
Setup cx_Freeze per creare l'eseguibile Windows.
Alternativa a PyInstaller quando bloccato da Device Guard.
"""

import sys
from pathlib import Path
from cx_Freeze import setup, Executable

PROJECT_ROOT = Path(__file__).parent

# Opzioni per il build (cx_Freeze traccia gli import, ma alcuni pacchetti
# usano import dinamici e vanno dichiarati esplicitamente)
build_exe_options = {
    "packages": [
        "customtkinter",
        "customtkinter.windows",
        "langextract",
        "google",
        "google.genai",
        "fitz",  # PyMuPDF
        "PIL",
        "PIL._tkinter_finder",
        "dotenv",
        "tkinterdnd2",
        "config",
        "gui",
        "ocr",
        "extraction",
        "pipeline",
        "utils",
    ],
    "include_files": [],
    "excludes": [],
    "optimize": 0,
}

# Base per nascondere la console (app GUI)
base = "Win32GUI" if sys.platform == "win32" else None
if hasattr(sys, "maxsize") and sys.version_info >= (3, 13):
    # cx_Freeze 8.x: "gui" al posto di "Win32GUI" su Python 3.13+
    base = "gui" if sys.platform == "win32" else None

executables = [
    Executable(
        "main.py",
        base=base,
        target_name="OCR_LangExtract",
        icon=None,
    )
]

setup(
    name="OCR_LangExtract",
    version="1.0",
    description="OCR + LangExtract - Estrazione lingue da PDF",
    options={"build_exe": build_exe_options},
    executables=executables,
)
