#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
build_installer.py – Script master per generare l'installer di Turbo MD Converter.

Esecuzione:
    python build_installer.py            # build completa (cx_Freeze + Inno Setup)
    python build_installer.py --version-only   # aggiorna solo version.py e build_info.json
    python build_installer.py --iss-only       # solo Inno Setup (riusa build esistente)

Il sistema di versioning usa il formato  ANNO.MESE.GIORNO.N
dove N si incrementa automaticamente ad ogni build dello stesso giorno.
"""

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path
from textwrap import dedent

# ── Percorsi ──────────────────────────────────────────────────────────────────
ROOT          = Path(__file__).parent.resolve()
BUILD_INFO    = ROOT / "build_info.json"
VERSION_PY    = ROOT / "version.py"
INSTALLER_DIR = ROOT / "installer"
VERSION_ISS   = INSTALLER_DIR / "version.iss"
ISS_SCRIPT    = INSTALLER_DIR / "turbomd.iss"
OUTPUT_DIR    = INSTALLER_DIR / "output"

# ── Dati applicazione (sincronizzati con version.py) ─────────────────────────
APP_NAME      = "Turbo MD Converter"
APP_EXE_NAME  = "TurboMDConverter"
APP_PUBLISHER = "Studio Legale"    # ← personalizza
APP_URL       = ""                 # ← opzionale

# ── Percorsi tipici di Inno Setup su Windows ─────────────────────────────────
INNO_CANDIDATES = [
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe",
    r"C:\Program Files (x86)\Inno Setup 5\ISCC.exe",
    r"C:\Program Files\Inno Setup 5\ISCC.exe",
]


# ═════════════════════════════════════════════════════════════════════════════
#  1. VERSIONING
# ═════════════════════════════════════════════════════════════════════════════

def _load_build_info() -> dict:
    if BUILD_INFO.exists():
        try:
            return json.loads(BUILD_INFO.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"date": "", "build_num": 0}


def _write_version_file(version: str, build_date: str, build_num: int) -> None:
    """Scrive version.py con la versione fornita."""
    try:
        year_s, month_s, day_s, _ = version.split(".")
        year, month, day = int(year_s), int(month_s), int(day_s)
    except (ValueError, AttributeError):
        print(f"[version] Formato versione non valido: {version}")
        sys.exit(1)

    version_py_content = dedent(f"""\
        # -*- coding: utf-8 -*-
        \"\"\"
        Versione centralizzata dell'applicazione.
        Aggiornato automaticamente da build_installer.py – NON modificare manualmente VERSION.
        \"\"\"

        APP_NAME        = "{APP_NAME}"
        APP_EXE_NAME    = "{APP_EXE_NAME}"
        APP_PUBLISHER   = "{APP_PUBLISHER}"
        APP_URL         = "{APP_URL}"

        # Formato: ANNO.MESE.GIORNO.NUMEROBUILD  (es. 2026.04.02.3)
        VERSION         = "{version}"
        BUILD_DATE      = "{build_date}"
        BUILD_NUM       = {build_num}

        # Tupla per cx_Freeze / metadata exe
        VERSION_TUPLE   = ({year}, {month}, {day}, {build_num})
    """)
    VERSION_PY.write_text(version_py_content, encoding="utf-8")


def bump_version() -> str:
    """Calcola la nuova versione e aggiorna build_info.json + version.py.

    Formato: YYYY.MM.DD.N  (N si azzera ogni nuovo giorno)
    Returns: stringa versione, es. "2026.04.02.3"
    """
    today        = date.today()
    today_str    = today.strftime("%Y-%m-%d")
    today_dotted = today.strftime("%Y.%m.%d")

    info = _load_build_info()
    if info.get("date") == today_str:
        build_num = info["build_num"] + 1
    else:
        build_num = 1

    version = f"{today_dotted}.{build_num}"

    # Aggiorna build_info.json
    BUILD_INFO.write_text(
        json.dumps({"date": today_str, "build_num": build_num}, indent=2),
        encoding="utf-8",
    )

    _write_version_file(version=version, build_date=today_str, build_num=build_num)

    print(f"[version]  {version}  (build #{build_num} del {today_str})")
    return version


def use_explicit_version(version: str) -> str:
    """Usa una versione esplicita (es. da tag Git) senza calcolo incrementale."""
    if not re.fullmatch(r"\d{4}\.\d{2}\.\d{2}\.\d+", version):
        print(
            f"[version] Formato non valido '{version}'. Atteso: YYYY.MM.DD.N "
            f"(es. 2026.04.10.2)"
        )
        sys.exit(1)

    year_s, month_s, day_s, build_s = version.split(".")
    build_date = f"{year_s}-{month_s}-{day_s}"
    build_num = int(build_s)
    _write_version_file(version=version, build_date=build_date, build_num=build_num)
    print(f"[version]  {version}  (forzata da input)")
    return version


# ═════════════════════════════════════════════════════════════════════════════
#  2. CX_FREEZE
# ═════════════════════════════════════════════════════════════════════════════

def run_cxfreeze() -> Path:
    """Esegue cx_Freeze e ritorna il percorso della cartella di build."""
    print("\n[cx_Freeze] Avvio build eseguibile…")

    result = subprocess.run(
        [sys.executable, "setup_cxfreeze.py", "build"],
        cwd=ROOT,
        check=False,
    )
    if result.returncode != 0:
        print("[cx_Freeze] ✗ Build fallita.")
        sys.exit(result.returncode)

    # La cartella si chiama tipo  build/exe.win-amd64-3.14/
    build_root = ROOT / "build"
    matches = sorted(build_root.glob("exe.*"))
    if not matches:
        print("[cx_Freeze] ✗ Cartella build non trovata in:", build_root)
        sys.exit(1)

    build_dir = matches[-1]          # prende la più recente se ce ne sono più
    print(f"[cx_Freeze] ✓ Build completata: {build_dir}")
    return build_dir


def find_build_dir() -> Path:
    """Trova la cartella di build cx_Freeze esistente (per --iss-only)."""
    build_root = ROOT / "build"
    matches = sorted(build_root.glob("exe.*"))
    if not matches:
        print("[build]  ✗ Nessuna cartella build trovata. Esegui prima senza --iss-only.")
        sys.exit(1)
    return matches[-1]


# ═════════════════════════════════════════════════════════════════════════════
#  3. INNO SETUP
# ═════════════════════════════════════════════════════════════════════════════

def find_iscc() -> Path:
    """Trova l'eseguibile ISCC.exe di Inno Setup."""
    # Controlla le posizioni standard
    for candidate in INNO_CANDIDATES:
        if Path(candidate).exists():
            return Path(candidate)

    # Prova con shutil.which (se ISCC è nel PATH)
    found = shutil.which("ISCC")
    if found:
        return Path(found)

    print(
        "[Inno Setup] ✗ ISCC.exe non trovato.\n"
        "  Scarica Inno Setup da https://jrsoftware.org/isinfo.php\n"
        "  oppure aggiungi la sua cartella al PATH di sistema."
    )
    sys.exit(1)


def write_version_iss(version: str, build_dir: Path) -> None:
    """Genera installer/version.iss con le #define usate dal turbomd.iss."""
    today_year = version[:4]
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    content = dedent(f"""\
        ; Generato automaticamente da build_installer.py – NON modificare manualmente
        #define AppName      "{APP_NAME}"
        #define AppExeName   "{APP_EXE_NAME}.exe"
        #define AppVersion   "{version}"
        #define AppPublisher "{APP_PUBLISHER}"
        #define AppURL       "{APP_URL}"
        #define AppYear      "{today_year}"
        #define BuildDir     "{build_dir}"
    """)
    VERSION_ISS.write_text(content, encoding="utf-8")
    print(f"[Inno Setup] version.iss scritto → {VERSION_ISS}")


def run_inno_setup() -> Path:
    """Compila lo script Inno Setup e ritorna il percorso dell'installer generato."""
    iscc = find_iscc()
    print(f"\n[Inno Setup] Compilazione con {iscc} …")

    result = subprocess.run(
        [str(iscc), str(ISS_SCRIPT)],
        cwd=INSTALLER_DIR,
        check=False,
    )
    if result.returncode != 0:
        print("[Inno Setup] ✗ Compilazione fallita.")
        sys.exit(result.returncode)

    # Trova il file .exe appena creato nella cartella output
    installers = sorted(OUTPUT_DIR.glob("*.exe"), key=lambda p: p.stat().st_mtime)
    if not installers:
        print("[Inno Setup] ✗ Nessun installer trovato in:", OUTPUT_DIR)
        sys.exit(1)

    installer = installers[-1]
    print(f"[Inno Setup] ✓ Installer generato: {installer}")
    return installer


# ═════════════════════════════════════════════════════════════════════════════
#  4. MAIN
# ═════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Build script per Turbo MD Converter"
    )
    parser.add_argument(
        "--version-only",
        action="store_true",
        help="Aggiorna solo version.py e build_info.json, senza compilare",
    )
    parser.add_argument(
        "--iss-only",
        action="store_true",
        help="Salta cx_Freeze, usa la build esistente e genera solo l'installer",
    )
    parser.add_argument(
        "--version",
        type=str,
        default="",
        help="Versione esplicita da usare (formato YYYY.MM.DD.N), tipicamente da tag",
    )
    args = parser.parse_args()

    print("=" * 60)
    print(f"  Build  {APP_NAME}")
    print("=" * 60)

    # Step 1: versione
    version = use_explicit_version(args.version) if args.version else bump_version()

    if args.version_only:
        print("\n[build]  Fatto (solo versione aggiornata).")
        return

    # Step 2: eseguibile
    if args.iss_only:
        build_dir = find_build_dir()
        print(f"[build]  Uso build esistente: {build_dir}")
    else:
        build_dir = run_cxfreeze()

    # Step 3: genera version.iss e compila installer
    write_version_iss(version, build_dir)
    installer = run_inno_setup()

    # Riepilogo finale
    size_mb = installer.stat().st_size / (1024 * 1024)
    print()
    print("=" * 60)
    print(f"  ✓  Installer pronto!")
    print(f"     {installer}")
    print(f"     Versione : {version}")
    print(f"     Dimensione: {size_mb:.1f} MB")
    print("=" * 60)


if __name__ == "__main__":
    main()
