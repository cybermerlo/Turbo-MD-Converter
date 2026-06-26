"""GitHub release checker and installer downloader."""

import json
import os
import sys
import threading
import urllib.request
from pathlib import Path
from typing import Callable

GITHUB_OWNER = "cybermerlo"
GITHUB_REPO = "Turbo-MD-Converter"
_API_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
_TIMEOUT = 15  # seconds


def _version_tuple(v: str) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in v.lstrip("v").split("."))
    except Exception:
        return (0,)


def is_newer(latest: str, current: str) -> bool:
    a, b = _version_tuple(latest), _version_tuple(current)
    # Pareggia la lunghezza prima del confronto: senza questo "2026.6.9" non
    # risulterebbe mai più recente di "2026.6.9.0" e, peggio, "2026.6.9.1" non
    # batterebbe "2026.6.9" (la tupla più corta vince a parità di prefisso solo
    # se più lunga). Schema versioni a 4 segmenti → confronto deve essere uniforme.
    n = max(len(a), len(b))
    a += (0,) * (n - len(a))
    b += (0,) * (n - len(b))
    return a > b


def get_latest_release() -> dict:
    """Fetch latest release info from GitHub API.

    Returns dict with keys:
        version (str), download_url (str | None),
        asset_name (str | None), release_notes (str), html_url (str)

    Raises RuntimeError on network/API error.
    """
    req = urllib.request.Request(
        _API_URL,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "TurboMDConverter"},
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise RuntimeError(
                "Nessuna release trovata su GitHub.\n"
                "Il repository potrebbe non avere ancora release pubblicate."
            ) from e
        raise RuntimeError(f"Errore API GitHub (HTTP {e.code}): {e.reason}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Errore di rete: {e.reason}") from e
    except Exception as e:
        raise RuntimeError(str(e)) from e

    tag = data.get("tag_name", "")
    version = tag.lstrip("v")
    notes = (data.get("body") or "").strip()
    html_url = data.get("html_url", "")

    # Find .exe installer asset (use .get: una risposta API malformata ma 200
    # non deve far crashare il controllo aggiornamenti con un KeyError).
    assets = data.get("assets", [])
    installer = next(
        (a for a in assets if a.get("name", "").lower().endswith(".exe")), None
    )

    return {
        "version": version,
        "download_url": installer.get("browser_download_url") if installer else None,
        "asset_name": installer.get("name") if installer else None,
        "asset_size": installer.get("size", 0) if installer else 0,
        "release_notes": notes,
        "html_url": html_url,
    }


def download_installer(
    url: str,
    dest: Path,
    progress_cb: Callable[[float], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> None:
    """Download installer to dest, calling progress_cb(0..1) during download.

    Raises RuntimeError on failure.
    """
    req = urllib.request.Request(
        url, headers={"User-Agent": "TurboMDConverter"}
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            chunk = 65536
            with dest.open("wb") as f:
                while True:
                    if cancel_event and cancel_event.is_set():
                        # Non lasciare un installer troncato sul disco: un avvio
                        # successivo potrebbe tentare di eseguirlo.
                        f.close()
                        dest.unlink(missing_ok=True)
                        return
                    buf = resp.read(chunk)
                    if not buf:
                        break
                    f.write(buf)
                    downloaded += len(buf)
                    if progress_cb and total > 0:
                        progress_cb(downloaded / total)
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise RuntimeError(f"Download fallito: {e}") from e

    if progress_cb:
        progress_cb(1.0)


def launch_installer_and_exit(installer_path: Path) -> None:
    """Launch the installer executable and exit the current process."""
    if sys.platform == "win32":
        os.startfile(str(installer_path))
    else:
        import subprocess
        subprocess.Popen([str(installer_path)])
    sys.exit(0)
