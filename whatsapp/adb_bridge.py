"""Bridge verso adb: legge i dati WhatsApp da un telefono Android via USB.

Usa la cartella di storage condiviso `Android/media/com.whatsapp/WhatsApp`, che
è accessibile senza root (a differenza di `/data/data/com.whatsapp`). Da qui si
leggono il backup cifrato `Databases/msgstore.db.crypt15` e i file multimediali
sotto `Media/`.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from gui.resources import resource_path
from utils.system import no_window_kwargs as _no_window_kwargs
from whatsapp.msgstore_reader import normalize_number

# Radice WhatsApp nello storage condiviso (niente root necessario).
WA_SHARED_ROOT = "/sdcard/Android/media/com.whatsapp/WhatsApp"
WA_DATABASES = f"{WA_SHARED_ROOT}/Databases"
MSGSTORE_NAME = "msgstore.db.crypt15"


class AdbError(Exception):
    """Errore generico nelle operazioni adb."""


class AdbNotFoundError(AdbError):
    """Eseguibile adb non trovato."""


class NoDeviceError(AdbError):
    """Nessun dispositivo Android collegato/pronto."""


class DeviceUnauthorizedError(AdbError):
    """Dispositivo collegato ma non autorizzato (popup da approvare sul telefono)."""


@dataclass
class AdbDevice:
    serial: str
    state: str  # "device", "unauthorized", "offline", ...


_CONTACT_RE = re.compile(r"display_name=(?P<name>.*),\s*data1=(?P<num>.*?)\s*$")


def parse_contacts(stdout: str) -> dict[str, str]:
    """Costruisce numero-normalizzato → nome dall'output di `content query`.

    Righe attese: `Row: N display_name=Mario Rossi, data1=+39 333 1234567`
    """
    out: dict[str, str] = {}
    for line in (stdout or "").splitlines():
        line = line.strip()
        if "display_name=" not in line or "data1=" not in line:
            continue
        m = _CONTACT_RE.search(line)
        if not m:
            continue
        name = m.group("name").strip()
        num = normalize_number(m.group("num"))
        if name and name.lower() != "null" and num and num not in out:
            out[num] = name
    return out


def parse_devices(stdout: str) -> list[AdbDevice]:
    """Estrae i dispositivi dall'output di `adb devices` (funzione pura)."""
    out: list[AdbDevice] = []
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line or line.lower().startswith("list of devices"):
            continue
        if line.startswith("*"):  # righe del demone adb ("* daemon started *")
            continue
        parts = line.split("\t") if "\t" in line else line.split()
        if len(parts) >= 2:
            out.append(AdbDevice(serial=parts[0], state=parts[1]))
    return out


def find_adb(config_adb_path: str = "") -> Path:
    """Individua adb: override in config → binario impacchettato → PATH di sistema."""
    if config_adb_path:
        p = Path(config_adb_path)
        if p.exists():
            return p

    exe = "adb.exe" if sys.platform == "win32" else "adb"
    # "adb/<exe>"        → layout della build freezata (accanto all'eseguibile)
    # "vendor/adb/<exe>" → layout da sorgente (cartella del repository)
    for rel in (f"adb/{exe}", f"vendor/adb/{exe}"):
        bundled = resource_path(rel)
        if bundled.exists():
            return bundled

    found = shutil.which("adb")
    if found:
        return Path(found)

    raise AdbNotFoundError(
        "adb non trovato. Reinstalla l'applicazione oppure indica il percorso "
        "di adb.exe nelle Impostazioni → WhatsApp."
    )


class AdbBridge:
    """Wrapper sottile attorno alla CLI di adb."""

    def __init__(self, config_adb_path: str = "", timeout: int = 180):
        self.adb_path = find_adb(config_adb_path)
        self.timeout = timeout

    def _run(
        self, args: list[str], timeout: int | None = None
    ) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(
                [str(self.adb_path), *args],
                capture_output=True,
                text=True,
                # adb emette UTF-8: senza forzarlo, su Windows il codec locale
                # (cp1252) va in crash su nomi rubrica/emoji non-ASCII.
                encoding="utf-8",
                errors="replace",
                timeout=timeout or self.timeout,
                **_no_window_kwargs(),
            )
        except FileNotFoundError as e:
            raise AdbNotFoundError(str(e)) from e
        except subprocess.TimeoutExpired as e:
            raise AdbError(f"Timeout adb ({' '.join(args)})") from e

    # ── Dispositivi ───────────────────────────────────────────────────────
    def devices(self) -> list[AdbDevice]:
        proc = self._run(["devices"], timeout=20)
        return parse_devices(proc.stdout)

    def require_device(self) -> AdbDevice:
        """Ritorna l'unico dispositivo pronto, o solleva un errore parlante."""
        devs = self.devices()
        ready = [d for d in devs if d.state == "device"]
        if ready:
            return ready[0]
        if any(d.state == "unauthorized" for d in devs):
            raise DeviceUnauthorizedError(
                "Dispositivo non autorizzato. Sul telefono approva il popup "
                "«Consentire il debug USB?» (spunta «Consenti sempre») e riprova."
            )
        raise NoDeviceError(
            "Nessun dispositivo rilevato. Collega il telefono via USB, sbloccalo "
            "e abilita il «Debug USB» nelle Opzioni sviluppatore."
        )

    # ── File ──────────────────────────────────────────────────────────────
    def pull(self, remote: str, local: Path) -> Path:
        local = Path(local)
        local.parent.mkdir(parents=True, exist_ok=True)
        proc = self._run(["pull", remote, str(local)])
        if proc.returncode != 0 or not local.exists():
            detail = proc.stderr.strip() or proc.stdout.strip() or "errore sconosciuto"
            raise AdbError(f"Impossibile copiare '{remote}': {detail}")
        return local

    def try_pull(self, remote: str, local: Path) -> Path | None:
        """Come pull() ma ritorna None invece di sollevare (per media opzionali)."""
        try:
            return self.pull(remote, local)
        except AdbError:
            return None

    def pull_msgstore(self, dest_dir: Path) -> Path:
        """Copia il backup cifrato corrente msgstore.db.crypt15 dal telefono."""
        dest = Path(dest_dir) / MSGSTORE_NAME
        remote = f"{WA_DATABASES}/{MSGSTORE_NAME}"
        if not self.exists(remote):
            raise AdbError(
                f"Backup '{MSGSTORE_NAME}' non trovato sul telefono. Apri WhatsApp "
                f"→ Impostazioni → Chat → Backup e tocca «Esegui backup», poi riprova."
            )
        return self.pull(remote, dest)

    def exists(self, remote: str) -> bool:
        proc = self._run(["shell", "ls", remote], timeout=20)
        combined = (proc.stdout + proc.stderr)
        return proc.returncode == 0 and "No such file" not in combined

    def read_contacts(self) -> dict[str, str]:
        """Mappa numero-normalizzato → nome dalla rubrica del telefono.

        Usa il content provider dei contatti, leggibile dall'utente `shell`
        senza root. Best-effort: ritorna {} se non disponibile.
        """
        try:
            proc = self._run([
                "shell", "content", "query",
                "--uri", "content://com.android.contacts/data/phones",
                "--projection", "display_name:data1",
            ], timeout=60)
        except AdbError:
            return {}
        if proc.returncode != 0:
            return {}
        return parse_contacts(proc.stdout)
