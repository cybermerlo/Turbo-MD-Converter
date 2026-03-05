# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file per creare l'eseguibile Windows.
"""

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

# Percorso del progetto (SPECPATH è definito da PyInstaller)
try:
    PROJECT_ROOT = Path(SPECPATH)
except NameError:
    # Fallback se SPECPATH non è definito
    PROJECT_ROOT = Path(__file__).parent if '__file__' in globals() else Path.cwd()

a = Analysis(
    ['main.py'],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=[
        'customtkinter',
        'customtkinter.windows',
        'customtkinter.windows.ctk_tk',
        'customtkinter.windows.ctk_frame',
        'PIL._tkinter_finder',
        'google.genai',
        'fitz',  # PyMuPDF
        'dotenv',
    ] + collect_submodules('langextract'),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='OCR_LangExtract',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # Nasconde la console (GUI app)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # Puoi aggiungere un'icona .ico qui se ne hai una
)
