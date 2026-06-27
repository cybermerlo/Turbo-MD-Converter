"""Piccoli helper di sistema condivisi (subprocess e apertura file).

Centralizza due pattern OS-dipendenti che erano duplicati in più moduli:
- ``no_window_kwargs()``: evita il flash della console su Windows quando l'app
  è freezata (cx_Freeze) ed esegue subprocess.
- ``open_with_system()``: apre un file o una cartella con l'app predefinita del
  sistema (Windows/macOS/Linux).
"""

import subprocess
import sys
from pathlib import Path


def no_window_kwargs() -> dict:
    """kwargs per subprocess che evitano il flash della console su Windows."""
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def open_with_system(path) -> None:
    """Apre ``path`` (file o cartella) con l'applicazione predefinita del sistema.

    No-op se il percorso non esiste. Non solleva: gli errori di apertura non
    devono mai propagarsi fino alla UI.
    """
    p = Path(path)
    if not p.exists():
        return
    try:
        if sys.platform == "win32":
            import os
            os.startfile(str(p))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p)])
    except Exception:
        pass
