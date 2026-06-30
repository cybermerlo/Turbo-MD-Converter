"""Diagnostica read-only dell'app ufficiale WhatsApp Desktop su Windows.

Spike di fattibilità per l'importazione delle chat leggendo il database LOCALE
dell'app ufficiale (nessuna connessione ai server WhatsApp → nessun rischio ban).

Questo script **NON decifra nulla e non modifica nulla**: si limita a fotografare
l'installazione (quale variante, quali file, se la chiave del dispositivo è
leggibile) per capire su cosa costruire il decryptor vero e proprio.

USO (su Windows, dove è installato WhatsApp Desktop e si è fatto almeno un accesso):

    python tools/wa_desktop_probe.py

Poi incolla l'output (è già pronto da copiare, in fondo c'è anche un blocco JSON).
Suggerimento: eseguilo una prima volta normalmente; se segnala che la chiave del
dispositivo (ODUID) richiede privilegi, rieseguilo da un prompt "Amministratore"
per confermare che diventa leggibile.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

# Pattern note dei file dell'archivio messaggi nelle varie generazioni dell'app.
_DB_FILES_WEBVIEW2 = ("genericStorageDB", "nativeSettings.db", "session.db")
_DB_FILES_UWP = ("message.db",)
_INTERESTING_GLOBS = (
    "genericStorageDB*", "message.db*", "nativeSettings.db*", "session.db*",
    "*.db", "*.db-wal", "*.db-shm", "nondb_settings*.dat",
)
_SQLITE_MAGIC = b"SQLite format 3\x00"


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _safe(fn):
    """Esegue un check isolando le eccezioni in un campo 'error'."""
    try:
        return fn()
    except Exception as e:  # noqa: BLE001 - diagnostica: vogliamo continuare sempre
        return {"error": f"{type(e).__name__}: {e}"}


def _file_info(p: Path) -> dict:
    info: dict = {"name": p.name}
    try:
        st = p.stat()
        info["size_bytes"] = st.st_size
        info["modified"] = datetime.fromtimestamp(
            st.st_mtime, timezone.utc
        ).astimezone().isoformat(timespec="seconds")
    except OSError as e:
        info["stat_error"] = str(e)
    # Primi byte: una SQLite in chiaro inizia con "SQLite format 3\0"; se è
    # cifrata (SEE) i primi byte saranno casuali → conferma la cifratura.
    try:
        with p.open("rb") as f:
            head = f.read(16)
        info["header_hex"] = head.hex()
        info["looks_plain_sqlite"] = head == _SQLITE_MAGIC
    except OSError as e:
        info["read_error"] = str(e)
    return info


def find_packages() -> list[Path]:
    """Trova le cartelle pacchetto di WhatsApp Desktop (Microsoft Store)."""
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return []
    pkgroot = Path(local) / "Packages"
    if not pkgroot.is_dir():
        return []
    found = []
    for pat in ("5319275A.WhatsAppDesktop_*", "*WhatsApp*Desktop*", "*WhatsApp*"):
        for d in pkgroot.glob(pat):
            if d.is_dir() and d not in found:
                found.append(d)
    return found


def probe_localstate(pkg: Path) -> dict:
    ls = pkg / "LocalState"
    out: dict = {"localstate_path": str(ls), "exists": ls.is_dir()}
    if not ls.is_dir():
        return out

    present = {p.name for p in ls.iterdir() if p.is_file()}
    if any(n in present for n in _DB_FILES_WEBVIEW2):
        out["variant_guess"] = "webview2 (>= dic 2025)"
    elif any(n in present for n in _DB_FILES_UWP):
        out["variant_guess"] = "uwp/winui (~2023-2025)"
    else:
        out["variant_guess"] = "sconosciuta"

    seen: set[str] = set()
    files: list[dict] = []
    for pat in _INTERESTING_GLOBS:
        for p in ls.glob(pat):
            if p.is_file() and p.name not in seen:
                seen.add(p.name)
                files.append(_file_info(p))
    out["db_files"] = sorted(files, key=lambda d: d["name"])

    transfers = ls / "shared" / "transfers"
    if transfers.is_dir():
        exts: dict[str, int] = {}
        count = 0
        total = 0
        for p in transfers.rglob("*"):
            if p.is_file():
                count += 1
                try:
                    total += p.stat().st_size
                except OSError:
                    pass
                exts[p.suffix.lower() or "(nessuna)"] = (
                    exts.get(p.suffix.lower() or "(nessuna)", 0) + 1
                )
        out["media_transfers"] = {
            "path": str(transfers),
            "file_count": count,
            "total_mb": round(total / (1024 * 1024), 1),
            "by_extension": dict(sorted(exts.items(), key=lambda kv: -kv[1])[:12]),
        }
    else:
        out["media_transfers"] = {"path": str(transfers), "exists": False}
    return out


def probe_oduid() -> dict:
    """La chiave dipende dall'ODUID in HKLM\\SYSTEM\\...\\TPM\\ODUID (RandomSeed).

    Lo leggiamo solo per sapere SE è accessibile (e se serve l'elevazione). Non
    stampiamo il valore: è materiale sensibile per la derivazione della chiave.
    """
    try:
        import winreg
    except ImportError:
        return {"available": False, "reason": "winreg non disponibile (non-Windows)"}
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Services\TPM\ODUID",
        ) as k:
            val, _typ = winreg.QueryValueEx(k, "RandomSeed")
            return {
                "available": True,
                "needs_admin": False,
                "random_seed_len": len(val) if isinstance(val, (bytes, str)) else None,
            }
    except PermissionError:
        return {"available": False, "needs_admin": True,
                "reason": "accesso negato: riprovare da prompt Amministratore"}
    except FileNotFoundError:
        return {"available": False, "needs_admin": None,
                "reason": "chiave/voce assente (forse macchina senza TPM ODUID; "
                          "esiste un fallback UEFI OfflineUniqueIDRandomSeed)"}
    except Exception as e:  # noqa: BLE001
        return {"available": False, "error": f"{type(e).__name__}: {e}"}


def probe_dpapi_ng() -> dict:
    """DPAPI-NG (ncrypt.dll) è usato dal build WebView2 per proteggere lo staticKey."""
    if sys.platform != "win32":
        return {"ncrypt_loadable": False, "reason": "non-Windows"}
    try:
        import ctypes
        ctypes.WinDLL("ncrypt")
        return {"ncrypt_loadable": True}
    except Exception as e:  # noqa: BLE001
        return {"ncrypt_loadable": False, "error": f"{type(e).__name__}: {e}"}


def probe_app_version(packages: list[Path]) -> dict:
    out: dict = {}
    for pkg in packages:
        ver = None
        for manifest in ("AppxManifest.xml", "AppxBundleManifest.xml"):
            mp = pkg / manifest
            if mp.is_file():
                try:
                    import re
                    txt = mp.read_text(encoding="utf-8", errors="replace")
                    m = re.search(r'Version="([\d.]+)"', txt)
                    if m:
                        ver = m.group(1)
                        break
                except OSError:
                    pass
        # Il nome cartella spesso contiene già la versione (…_2.2xxx.x_x64__…)
        out[pkg.name] = {"manifest_version": ver}
    return out


_DB_EXTS = (".db", ".db-wal", ".db-shm", ".sqlite", ".sqlite3")
_DB_NAME_HINTS = (
    "genericstoragedb", "message.db", "nativesettings.db", "msgstore",
    "session.db", "messages", "chat", "storage",
)
_MEDIA_DIR_HINTS = ("transfers", "media", "downloads")


def _is_db_candidate(name: str) -> bool:
    low = name.lower()
    return low.endswith(_DB_EXTS) or any(h in low for h in _DB_NAME_HINTS)


def deep_scan(pkg: Path, max_files: int = 400_000) -> dict:
    """Scansione ricorsiva read-only del pacchetto: individua i DB e i media
    ovunque si trovino in questo build (il layout cambia tra le versioni)."""
    db_candidates: list[dict] = []
    largest: list[tuple[int, str]] = []
    media_dirs: dict[str, int] = {}
    top_summary: dict[str, dict] = {}
    walked = 0
    capped = False

    for root, _dirs, files in os.walk(pkg):
        rootp = Path(root)
        rel = "(root)" if rootp == pkg else str(rootp.relative_to(pkg)).split(os.sep)[0]
        ts = top_summary.setdefault(rel, {"files": 0, "bytes": 0})
        low_dir = rootp.name.lower()
        if any(h in low_dir for h in _MEDIA_DIR_HINTS):
            media_dirs[str(rootp.relative_to(pkg))] = len(files)
        for fn in files:
            walked += 1
            if walked > max_files:
                capped = True
                break
            fp = rootp / fn
            try:
                size = fp.stat().st_size
            except OSError:
                size = -1
            ts["files"] += 1
            if size > 0:
                ts["bytes"] += size
                largest.append((size, str(fp.relative_to(pkg))))
            if _is_db_candidate(fn):
                try:
                    db_candidates.append({**_file_info(fp),
                                          "rel": str(fp.relative_to(pkg))})
                except Exception as e:  # noqa: BLE001
                    db_candidates.append({"rel": fn, "error": str(e)})
        if capped:
            break

    largest.sort(reverse=True)
    return {
        "walked_files": walked,
        "capped": capped,
        "top_level_summary": {
            k: {"files": v["files"], "mb": round(v["bytes"] / 1048576, 1)}
            for k, v in sorted(top_summary.items(), key=lambda kv: -kv[1]["bytes"])
        },
        "db_candidates": db_candidates[:40],
        "largest_files": [
            {"rel": r, "mb": round(s / 1048576, 2)} for s, r in largest[:25]
        ],
        "media_dirs": media_dirs,
    }


def main() -> int:
    report: dict = {
        "generated_at": _now(),
        "platform": sys.platform,
        "python": sys.version.split()[0],
        "arch": _safe(lambda: __import__("platform").machine()),
    }

    if sys.platform != "win32":
        report["note"] = (
            "Questo script va eseguito su Windows, dove è installato WhatsApp "
            "Desktop. Su un altro OS non c'è nulla da diagnosticare."
        )

    packages = _safe(find_packages)
    if isinstance(packages, dict):  # errore
        report["packages_error"] = packages
        packages = []

    report["packages_found"] = [str(p) for p in packages]
    report["localstate"] = [_safe(lambda p=p: probe_localstate(p)) for p in packages]
    report["app_version"] = _safe(lambda: probe_app_version(packages))
    report["oduid"] = _safe(probe_oduid)
    report["dpapi_ng"] = _safe(probe_dpapi_ng)
    report["is_admin"] = _safe(_is_admin)
    # Scansione ricorsiva: in alcuni build il DB messaggi e i media non sono
    # direttamente in LocalState. Cerchiamoli ovunque nel pacchetto.
    report["deep_scan"] = [_safe(lambda p=p: deep_scan(p)) for p in packages]

    # ── Stampa leggibile ────────────────────────────────────────────────────
    print("=" * 64)
    print(" Turbo MD Converter — Diagnostica WhatsApp Desktop (read-only)")
    print("=" * 64)
    print(f"Data: {report['generated_at']}")
    print(f"Sistema: {report['platform']}  Python: {report['python']}  "
          f"Arch: {report.get('arch')}  Admin: {report.get('is_admin')}")
    if not packages:
        print("\n[!] Nessun pacchetto WhatsApp Desktop trovato in %LOCALAPPDATA%\\Packages.")
        print("    Verifica di aver installato l'app *ufficiale* dallo Store e di")
        print("    aver fatto almeno un accesso (così sincronizza i messaggi recenti).")
    for ls in report["localstate"]:
        print("\n--- LocalState ---")
        print(f"  Percorso: {ls.get('localstate_path')}  (exists={ls.get('exists')})")
        print(f"  Variante stimata: {ls.get('variant_guess')}")
        for f in ls.get("db_files", []):
            plain = f.get("looks_plain_sqlite")
            tag = "SQLite IN CHIARO" if plain else "cifrato/non-sqlite" if plain is False else "?"
            print(f"    • {f.get('name'):<22} {f.get('size_bytes','?'):>12} byte  [{tag}]")
        mt = ls.get("media_transfers", {})
        if mt.get("file_count") is not None:
            print(f"  Media (shared/transfers): {mt['file_count']} file, "
                  f"{mt['total_mb']} MB  {mt.get('by_extension')}")
        else:
            print(f"  Media (shared/transfers): assente ({mt.get('path')})")
    for ds in report.get("deep_scan", []):
        if not isinstance(ds, dict) or "error" in ds:
            print(f"\n--- Scansione ricorsiva: {ds} ---")
            continue
        print("\n--- Scansione ricorsiva del pacchetto ---")
        print(f"  File esaminati: {ds.get('walked_files')}"
              f"{' (TRONCATO)' if ds.get('capped') else ''}")
        print(f"  Sottocartelle (file, MB): {ds.get('top_level_summary')}")
        print("  Candidati DB trovati:")
        for c in ds.get("db_candidates", []):
            plain = c.get("looks_plain_sqlite")
            tag = "SQLite IN CHIARO" if plain else "cifrato" if plain is False else "?"
            print(f"    • {c.get('rel'):<50} {c.get('size_bytes','?'):>12} byte  [{tag}]")
        if ds.get("media_dirs"):
            print(f"  Cartelle media (path: n.file): {ds.get('media_dirs')}")
        print("  File più grandi:")
        for lf in ds.get("largest_files", [])[:12]:
            print(f"    • {lf.get('rel'):<50} {lf.get('mb')} MB")

    print("\n--- Chiave dispositivo (ODUID) ---")
    print(f"  {report['oduid']}")
    print("--- DPAPI-NG (ncrypt) ---")
    print(f"  {report['dpapi_ng']}")
    print("--- Versione app ---")
    print(f"  {report['app_version']}")

    print("\n" + "=" * 64)
    print(" COPIA E INCOLLA il blocco JSON qui sotto nella chat:")
    print("=" * 64)
    print("```json")
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    print("```")
    return 0


def _is_admin() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001 - non far morire lo script senza spiegazione
        print("Errore imprevisto nella diagnostica:\n" + traceback.format_exc())
        raise SystemExit(1)
