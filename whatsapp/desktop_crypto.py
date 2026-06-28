"""Decifratura dei database locali di WhatsApp Desktop (Windows, WebView2).

Porting in Python dell'algoritmo di ZAPiXDESK, validato sul campo (vedi
`tools/wa_desktop_decrypt_spike.py` e `docs/plans/whatsapp-desktop-import.md`).
Catena: RandomSeed -> ODUID -> (DPAPI-NG su staticKey) sessionDBSecret ->
session.db -> clientKey (SHA1 == nome cartella sessione) -> dbKey -> nativeSettings
-> chiavi -> genericStorage.db (messaggi, chiave tipo 1) + contacts.db (chiave
tipo 2). Cifratura: AES-256-OFB per-pagina (4096B), IV = pageNumber(LE 4B) ||
ultimi 12B della pagina. I file decifrati sono SQLite standard.

Solo lettura di file locali: nessuna connessione ai server WhatsApp.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import struct
import tempfile
from dataclasses import dataclass
from pathlib import Path

STATIC_BYTES = bytes.fromhex("23a7f19c11e5bd784235c96f85d24913")
APP_SALT = "cv1g1gv".encode("utf-16-le")
PBKDF2_ITERS = 10000
PAGE_SIZE = 4096
SQLITE_MAGIC = b"SQLite format 3\x00"
PACKAGE_GLOB = "5319275A.WhatsAppDesktop_*"


class WhatsAppDesktopError(Exception):
    """Errore di accesso/decifratura del database di WhatsApp Desktop."""


# ─── AES (cryptography | Cryptodome | Crypto) ────────────────────────────────
def _pycrypto_aes():
    import importlib
    for ns in ("Cryptodome", "Crypto"):
        try:
            return importlib.import_module(ns + ".Cipher.AES")
        except ImportError:
            continue
    return None


def _aes_ofb_decrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        d = Cipher(algorithms.AES(key), modes.OFB(iv)).decryptor()
        return d.update(data) + d.finalize()
    except ImportError:
        aes = _pycrypto_aes()
        if aes is None:
            raise WhatsAppDesktopError(
                "Manca una libreria AES: esegui 'pip install cryptography'."
            ) from None
        return aes.new(key, aes.MODE_OFB, iv=iv).decrypt(data)


def _aes_cbc_encrypt_pkcs7(key: bytes, iv: bytes, data: bytes) -> bytes:
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives import padding
        p = padding.PKCS7(128).padder()
        enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
        return enc.update(p.update(data) + p.finalize()) + enc.finalize()
    except ImportError:
        aes = _pycrypto_aes()
        n = 16 - len(data) % 16
        return aes.new(key, aes.MODE_CBC, iv=iv).encrypt(data + bytes([n]) * n)


# ─── DPAPI-NG / ODUID (Windows) ──────────────────────────────────────────────
def ncrypt_protect_secret(data: bytes, descriptor: str = "LOCAL=user") -> bytes:
    import ctypes
    from ctypes import wintypes

    ncrypt = ctypes.WinDLL("ncrypt")
    ncrypt.NCryptCreateProtectionDescriptor.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
    ncrypt.NCryptCreateProtectionDescriptor.restype = ctypes.c_long
    ncrypt.NCryptProtectSecret.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, ctypes.c_char_p, wintypes.ULONG,
        ctypes.c_void_p, ctypes.c_void_p,
        ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte)), ctypes.POINTER(wintypes.ULONG)]
    ncrypt.NCryptProtectSecret.restype = ctypes.c_long

    h = ctypes.c_void_p()
    st = ncrypt.NCryptCreateProtectionDescriptor(descriptor, 0, ctypes.byref(h))
    if st != 0:
        raise WhatsAppDesktopError(
            f"NCryptCreateProtectionDescriptor 0x{st & 0xffffffff:08x}")
    out = ctypes.POINTER(ctypes.c_ubyte)()
    outlen = wintypes.ULONG()
    st = ncrypt.NCryptProtectSecret(
        h, 0x40, data, len(data), None, None, ctypes.byref(out), ctypes.byref(outlen))
    if st != 0:
        raise WhatsAppDesktopError(f"NCryptProtectSecret 0x{st & 0xffffffff:08x}")
    blob = bytes(bytearray(out[:outlen.value]))
    ctypes.windll.kernel32.LocalFree(out)
    return blob


def read_random_seed() -> bytes:
    import winreg
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Services\TPM\ODUID",
        ) as k:
            val, _ = winreg.QueryValueEx(k, "RandomSeed")
        return bytes(val)
    except FileNotFoundError as e:
        raise WhatsAppDesktopError(
            "Chiave dispositivo (ODUID) non trovata nel registro.") from e


def compute_oduid(seed: bytes) -> bytes:
    return hashlib.sha256(APP_SALT + seed).digest()


# ─── Cifratura per-pagina ────────────────────────────────────────────────────
def decrypt_db(data: bytes, key: bytes) -> bytes:
    out = bytearray()
    for p in range(len(data) // PAGE_SIZE):
        page = data[p * PAGE_SIZE:(p + 1) * PAGE_SIZE]
        iv = struct.pack("<I", p + 1) + page[-12:]
        out += _aes_ofb_decrypt(key, iv, page)
    if len(out) >= 24 and len(data) >= 24:
        out[16:24] = data[16:24]  # header SQLite ripristinato dall'originale
    return bytes(out)


def decrypt_wal(data: bytes, key: bytes) -> bytes:
    if len(data) < 32:
        return data
    out = bytearray(data[:32])
    i = 32
    while i + 24 + PAGE_SIZE <= len(data):
        hdr = data[i:i + 24]
        enc = data[i + 24:i + 24 + PAGE_SIZE]
        iv = struct.pack("<I", int.from_bytes(hdr[0:4], "big")) + enc[-12:]
        out += hdr + _aes_ofb_decrypt(key, iv, enc)
        i += 24 + PAGE_SIZE
    return bytes(out)


def _is_plain_sqlite(b: bytes) -> bool:
    return b[:16] == SQLITE_MAGIC


def _decrypt_pair(db: Path, key: bytes, out_dir: Path, stem: str) -> Path:
    clear = out_dir / f"{stem}.clear.db"
    clear.write_bytes(decrypt_db(db.read_bytes(), key))
    wal = db.with_name(db.name + "-wal")
    if wal.exists():
        (out_dir / f"{stem}.clear.db-wal").write_bytes(decrypt_wal(wal.read_bytes(), key))
    return clear


def _find_key_by_sha1(data: bytes, targets: set[str], lengths) -> bytes | None:
    for L in lengths:
        if L > len(data):
            continue
        for off in range(len(data) - L + 1):
            if hashlib.sha1(data[off:off + L]).hexdigest().upper() in targets:
                return data[off:off + L]
    return None


def _carve_blob_candidates(data: bytes, lengths) -> list[bytes]:
    out, seen = [], set()
    for L in lengths:
        marker = 12 + 2 * L
        if marker > 127:
            continue
        mb = bytes([marker])
        i = data.find(mb)
        while i != -1:
            if i + 1 + L <= len(data):
                c = data[i + 1:i + 1 + L]
                if c not in seen:
                    seen.add(c)
                    out.append(c)
            i = data.find(mb, i + 1)
    return out


def _key_validates(db: Path, key: bytes) -> bool:
    try:
        return _is_plain_sqlite(decrypt_db(db.read_bytes()[:PAGE_SIZE], key))
    except Exception:
        return False


def _find_validating_key(db: Path, native_bytes: bytes, known: bytes | None = None) -> bytes | None:
    if known and _key_validates(db, known):
        return known
    for k in _carve_blob_candidates(native_bytes, [32, 16, 24]):
        if _key_validates(db, k):
            return k
    for L in (32, 16, 24):
        for off in range(len(native_bytes) - L + 1):
            k = native_bytes[off:off + L]
            if _key_validates(db, k):
                return k
    return None


# ─── Localizzazione e decifratura completa ───────────────────────────────────
def find_localstate() -> Path | None:
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return None
    for d in (Path(local) / "Packages").glob(PACKAGE_GLOB):
        ls = d / "LocalState"
        if ls.is_dir():
            return ls
    return None


def source_fingerprint(localstate: Path | None = None) -> str | None:
    """Impronta dei DB sorgente CIFRATI (genericStorage/contacts + i loro -wal).
    Serve a sapere se la decifratura in cache è ancora valida: cambia appena
    WhatsApp scrive nuovi messaggi → si ri-decifra (dati freschi); se WhatsApp è
    fermo, l'impronta è stabile → si riusa la decifratura (istantaneo). None se i
    file non sono individuabili."""
    ls = localstate or find_localstate()
    if not ls or not ls.is_dir():
        return None
    sessions = ls / "sessions"
    if not sessions.is_dir():
        return None
    parts = []
    for pat in ("*/genericStorage.db", "*/genericStorage.db-wal",
                "*/contacts.db", "*/contacts.db-wal"):
        for f in sorted(sessions.glob(pat)):
            try:
                st = f.stat()
                parts.append(f"{f.parent.name}/{f.name}|{st.st_size}|{st.st_mtime_ns}")
            except OSError:
                pass
    if not parts:
        return None
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


@dataclass
class DecryptedStore:
    """Percorsi ai DB decifrati (SQLite standard) in una cartella temporanea."""
    workdir: Path
    messages_db: Path            # genericStorage (tabella `message`)
    contacts_db: Path | None     # contacts (UserStatuses) per i nomi

    def cleanup(self) -> None:
        shutil.rmtree(self.workdir, ignore_errors=True)


def decrypt_databases(localstate: Path | None = None,
                      oduid_hex: str | None = None,
                      workdir: Path | None = None) -> DecryptedStore:
    """Esegue l'intera catena e ritorna i DB decifrati. Solleva
    WhatsAppDesktopError con messaggio chiaro su qualunque passo fallito."""
    import sys
    if sys.platform != "win32":
        raise WhatsAppDesktopError("Disponibile solo su Windows.")

    ls = localstate or find_localstate()
    if not ls or not ls.is_dir():
        raise WhatsAppDesktopError(
            "WhatsApp Desktop non trovato. Installa l'app ufficiale ed esegui "
            "almeno un accesso.")
    session_db = ls / "session.db"
    sessions = ls / "sessions"
    folders = [d.name for d in sessions.iterdir() if d.is_dir()] if sessions.is_dir() else []
    if not session_db.exists() or not folders:
        raise WhatsAppDesktopError("Sessione WhatsApp Desktop non inizializzata.")

    work = workdir or Path(tempfile.mkdtemp(prefix="turbomd_wa_"))
    try:
        # 1-2: sessionDBSecret -> session.db
        secret = ncrypt_protect_secret(STATIC_BYTES)[:32]
        clear_session = _decrypt_pair(session_db, secret, work, "session")
        if not _is_plain_sqlite(clear_session.read_bytes()[:16]):
            raise WhatsAppDesktopError("Decifratura session.db fallita (DPAPI-NG).")

        # 3: clientKey via oracolo SHA1 == nome cartella sessione
        targets = {f.upper() for f in folders}
        blob = clear_session.read_bytes()
        wal = clear_session.with_name("session.clear.db-wal")
        if wal.exists():
            blob += wal.read_bytes()
        client_key = _find_key_by_sha1(blob, targets, [48, 32] + list(range(16, 65)))
        if not client_key:
            raise WhatsAppDesktopError("clientKey non individuato in session.db.")
        folder = hashlib.sha1(client_key).hexdigest().upper()
        sess = sessions / folder

        # 4: ODUID -> dbKey -> nativeSettings
        native = sess / "nativeSettings.db"
        if not native.exists():
            raise WhatsAppDesktopError("nativeSettings.db assente.")
        oduids = ([bytes.fromhex(oduid_hex)] if oduid_hex
                  else [compute_oduid(read_random_seed())])
        clear_native = None
        for oduid in oduids:
            aux = hashlib.pbkdf2_hmac("sha256", client_key, oduid, PBKDF2_ITERS, dklen=32)
            iv = hashlib.pbkdf2_hmac("sha256", aux, oduid, PBKDF2_ITERS, dklen=16)
            dbkey = _aes_cbc_encrypt_pkcs7(aux, iv, STATIC_BYTES)[:32]
            cn = _decrypt_pair(native, dbkey, work, "nativeSettings")
            if _is_plain_sqlite(cn.read_bytes()[:16]):
                clear_native = cn
                break
        if not clear_native:
            raise WhatsAppDesktopError("Derivazione chiave (ODUID) fallita.")

        native_bytes = clear_native.read_bytes()
        nwal = clear_native.with_name("nativeSettings.clear.db-wal")
        if nwal.exists():
            native_bytes += nwal.read_bytes()

        # 5-6: chiave messaggi (tipo 1) -> genericStorage
        generic = sess / "genericStorage.db"
        if not generic.exists():
            raise WhatsAppDesktopError("genericStorage.db assente.")
        msg_key = _find_validating_key(generic, native_bytes)
        if not msg_key:
            raise WhatsAppDesktopError("Chiave dei messaggi non trovata.")
        messages_db = _decrypt_pair(generic, msg_key, work, "genericStorage")

        # contacts (tipo 2) per i nomi — best-effort
        contacts_db = None
        contacts = sess / "contacts.db"
        if contacts.exists():
            ckey = _find_validating_key(contacts, native_bytes)
            if ckey:
                try:
                    contacts_db = _decrypt_pair(contacts, ckey, work, "contacts")
                except Exception:
                    contacts_db = None

        return DecryptedStore(work, messages_db, contacts_db)
    except Exception:
        shutil.rmtree(work, ignore_errors=True)
        raise
