"""Spike Fase 1 — decifratura del DB messaggi di WhatsApp Desktop (WebView2).

Porta in Python l'algoritmo di ZAPiXDESK (kraftdenker) per il build WebView2 di
WhatsApp Desktop su Windows. NON si connette a nulla: legge e decifra solo file
locali (rischio ban zero).

Catena: RandomSeed -> ODUID -> (DPAPI-NG su staticKey) sessionDBSecret ->
decifra session.db -> clientKey (checkpoint: SHA1(clientKey) == nome cartella
sessione) -> dbKey (PBKDF2+AES-CBC) -> decifra nativeSettings.db -> chiave tipo 1
-> decifra genericStorage.db (i MESSAGGI). Cifratura: AES-256-OFB per-pagina 4096B,
IV = pageNumber(LE 4B) || ultimi 12B della pagina cifrata. I file decifrati sono
SQLite STANDARD: si aprono con sqlite3 della stdlib.

USO (Windows, con WhatsApp Desktop installato e sincronizzato):

    pip install cryptography        # (o: pip install pycryptodome)
    python tools/wa_desktop_decrypt_spike.py

Opzioni:
    --localstate "C:\\...\\LocalState"   percorso LocalState (auto se omesso)
    --out DIR                            cartella per i .clear.db (default: %TEMP%)
    --oduid HEX                          ODUID a 32 byte (hex) fornito a mano
                                         (se il calcolo automatico non combacia)
    --limit N                            righe di esempio da stampare (default 8)

È uno spike diagnostico: stampa checkpoint per ogni stadio. Incolla l'output.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import struct
import sys
import tempfile
import traceback
from pathlib import Path

# Costanti dell'algoritmo (da ZAPiXDESK, build WebView2).
STATIC_BYTES = bytes.fromhex("23a7f19c11e5bd784235c96f85d24913")  # 16 byte
APP_SALT = "cv1g1gv".encode("utf-16-le")  # 63 00 76 00 31 00 67 00 31 00 67 00 76 00
PBKDF2_ITERS = 10000
PAGE_SIZE = 4096
SQLITE_MAGIC = b"SQLite format 3\x00"


# ─── Backend AES: cryptography | Cryptodome (pycryptodomex) | Crypto (pycryptodome)
def _pycrypto_mod():
    import importlib
    for ns in ("Cryptodome", "Crypto"):
        try:
            return importlib.import_module(ns + ".Cipher.AES")
        except ImportError:
            continue
    return None


def _have_aes() -> str | None:
    try:
        import cryptography  # noqa: F401
        return "cryptography"
    except ImportError:
        pass
    import importlib
    for ns in ("Cryptodome", "Crypto"):
        try:
            importlib.import_module(ns + ".Cipher.AES")
            return ns
        except ImportError:
            continue
    return None


def _aes_ofb_decrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        dec = Cipher(algorithms.AES(key), modes.OFB(iv)).decryptor()
        return dec.update(data) + dec.finalize()
    except ImportError:
        AES = _pycrypto_mod()
        return AES.new(key, AES.MODE_OFB, iv=iv).decrypt(data)


def _aes_cbc_encrypt_pkcs7(key: bytes, iv: bytes, data: bytes) -> bytes:
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives import padding
        padder = padding.PKCS7(128).padder()
        padded = padder.update(data) + padder.finalize()
        enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
        return enc.update(padded) + enc.finalize()
    except ImportError:
        AES = _pycrypto_mod()
        pad = (16 - len(data) % 16)
        return AES.new(key, AES.MODE_CBC, iv=iv).encrypt(data + bytes([pad]) * pad)


# ─── DPAPI-NG (NCryptProtectSecret, "LOCAL=user") via ctypes ─────────────────
def ncrypt_protect_secret(data: bytes, descriptor: str = "LOCAL=user") -> bytes:
    import ctypes
    from ctypes import wintypes

    ncrypt = ctypes.WinDLL("ncrypt")
    NCRYPT_SILENT_FLAG = 0x40

    ncrypt.NCryptCreateProtectionDescriptor.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)
    ]
    ncrypt.NCryptCreateProtectionDescriptor.restype = ctypes.c_long
    ncrypt.NCryptProtectSecret.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, ctypes.c_char_p, wintypes.ULONG,
        ctypes.c_void_p, ctypes.c_void_p,
        ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte)), ctypes.POINTER(wintypes.ULONG),
    ]
    ncrypt.NCryptProtectSecret.restype = ctypes.c_long

    h = ctypes.c_void_p()
    st = ncrypt.NCryptCreateProtectionDescriptor(descriptor, 0, ctypes.byref(h))
    if st != 0:
        raise OSError(f"NCryptCreateProtectionDescriptor 0x{st & 0xffffffff:08x}")
    out = ctypes.POINTER(ctypes.c_ubyte)()
    outlen = wintypes.ULONG()
    st = ncrypt.NCryptProtectSecret(
        h, NCRYPT_SILENT_FLAG, data, len(data), None, None,
        ctypes.byref(out), ctypes.byref(outlen),
    )
    if st != 0:
        raise OSError(f"NCryptProtectSecret 0x{st & 0xffffffff:08x}")
    blob = bytes(bytearray(out[:outlen.value]))
    ctypes.windll.kernel32.LocalFree(out)
    return blob


# ─── ODUID dal registro ──────────────────────────────────────────────────────
def read_random_seed() -> bytes:
    import winreg
    with winreg.OpenKey(
        winreg.HKEY_LOCAL_MACHINE,
        r"SYSTEM\CurrentControlSet\Services\TPM\ODUID",
    ) as k:
        val, _ = winreg.QueryValueEx(k, "RandomSeed")
    return bytes(val) if isinstance(val, (bytes, bytearray)) else bytes(val, "latin1")


def compute_oduid(seed: bytes, order: str) -> bytes:
    if order == "salt_seed":
        return hashlib.sha256(APP_SALT + seed).digest()
    return hashlib.sha256(seed + APP_SALT).digest()


# ─── Cifratura per-pagina AES-256-OFB ────────────────────────────────────────
def decrypt_db(data: bytes, key: bytes) -> bytes:
    out = bytearray()
    npages = len(data) // PAGE_SIZE
    for p in range(npages):
        page = data[p * PAGE_SIZE:(p + 1) * PAGE_SIZE]
        iv = struct.pack("<I", p + 1) + page[-12:]
        out += _aes_ofb_decrypt(key, iv, page)
    # ZAPiXDESK ripristina i byte d'header [0x10:0x18] dall'originale (encrypted).
    if len(out) >= 24 and len(data) >= 24:
        out[16:24] = data[16:24]
    return bytes(out)


def decrypt_wal(data: bytes, key: bytes) -> bytes:
    if len(data) < 32:
        return data
    out = bytearray(data[:32])  # header WAL non cifrato
    frame_hdr = 24
    i = 32
    while i + frame_hdr + PAGE_SIZE <= len(data):
        hdr = data[i:i + frame_hdr]
        page_num = int.from_bytes(hdr[0:4], "big")
        enc = data[i + frame_hdr:i + frame_hdr + PAGE_SIZE]
        iv = struct.pack("<I", page_num) + enc[-12:]
        out += hdr
        out += _aes_ofb_decrypt(key, iv, enc)
        i += frame_hdr + PAGE_SIZE
    return bytes(out)


def decrypt_pair(db_path: Path, key: bytes, out_dir: Path, stem: str) -> Path:
    """Decifra <db> e <db>-wal e scrive <stem>.clear.db (+ -wal). Ritorna il path."""
    clear_db = out_dir / f"{stem}.clear.db"
    clear_db.write_bytes(decrypt_db(db_path.read_bytes(), key))
    wal = db_path.with_name(db_path.name + "-wal")
    if wal.exists():
        (out_dir / f"{stem}.clear.db-wal").write_bytes(
            decrypt_wal(wal.read_bytes(), key)
        )
    return clear_db


def is_plain_sqlite(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            return f.read(16) == SQLITE_MAGIC
    except OSError:
        return False


# ─── Lettura SQLite (in sola lettura su copie) ───────────────────────────────
def open_ro(db: Path):
    import sqlite3
    # Apertura normale su copia temporanea: applica il WAL se presente.
    return sqlite3.connect(str(db))


def list_tables(con) -> list[str]:
    cur = con.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return [r[0] for r in cur.fetchall()]


def find_blobs(con, lo: int = 16, hi: int = 64) -> list[tuple]:
    """Cerca BLOB di lunghezza [lo,hi] in tutte le tabelle. Ritorna (tab,col,bytes)."""
    found = []
    for t in list_tables(con):
        try:
            cur = con.execute(f'SELECT * FROM "{t}"')
        except Exception:
            continue
        cols = [d[0] for d in cur.description] if cur.description else []
        for row in cur.fetchall():
            for col, v in zip(cols, row):
                if isinstance(v, (bytes, bytearray)) and lo <= len(v) <= hi:
                    found.append((t, col, bytes(v)))
    return found


def find_keytypes(con) -> dict:
    """nativeSettings: cerca righe (intero piccolo -> blob)."""
    out: dict[int, bytes] = {}
    for t in list_tables(con):
        try:
            cur = con.execute(f'SELECT * FROM "{t}"')
        except Exception:
            continue
        for row in cur.fetchall():
            ints = [v for v in row if isinstance(v, int) and 1 <= v <= 9]
            blobs = [bytes(v) for v in row if isinstance(v, (bytes, bytearray))]
            if len(ints) == 1 and len(blobs) == 1:
                out[ints[0]] = blobs[0]  # l'ultima vince
    return out


# ─── Pipeline dello spike ────────────────────────────────────────────────────
def default_localstate() -> Path | None:
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return None
    base = Path(local) / "Packages"
    for d in base.glob("5319275A.WhatsAppDesktop_*"):
        ls = d / "LocalState"
        if ls.is_dir():
            return ls
    return None


def run(localstate: Path, out_dir: Path, manual_oduid: str | None, limit: int) -> int:
    print("=" * 66)
    print(" Spike Fase 1 — decifratura WhatsApp Desktop (WebView2)")
    print("=" * 66)
    backend = _have_aes()
    print(f"AES backend: {backend or 'NESSUNO — esegui: pip install cryptography'}")
    if not backend:
        return 2
    print(f"LocalState : {localstate}")
    print(f"Output     : {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)

    session_db = localstate / "session.db"
    if not session_db.exists():
        print(f"[X] session.db non trovato in {localstate}")
        return 2
    sessions_dir = localstate / "sessions"
    session_folders = (
        [d.name for d in sessions_dir.iterdir() if d.is_dir()]
        if sessions_dir.is_dir() else []
    )
    print(f"Cartelle sessione: {session_folders}")

    # 1) sessionDBSecret via DPAPI-NG
    try:
        protected = ncrypt_protect_secret(STATIC_BYTES, "LOCAL=user")
        session_secret = protected[:32]
        print(f"[1] NCryptProtectSecret OK (blob {len(protected)}B) -> "
              f"sessionDBSecret {len(session_secret)}B")
    except Exception as e:
        print(f"[1][X] DPAPI-NG fallito: {e}")
        return 3

    # 2) decifra session.db -> deve essere SQLite valido
    try:
        clear_session = decrypt_pair(session_db, session_secret, out_dir, "session")
        ok = is_plain_sqlite(clear_session)
        print(f"[2] session.db decifrato -> SQLite valido: {'SI ✓' if ok else 'NO ✗'}")
        if not ok:
            print("    (se NO: NCryptProtectSecret/decifratura pagina non combaciano)")
            return 4
    except Exception as e:
        print(f"[2][X] decifratura session.db fallita: {e}")
        return 4

    # 3) clientKey: il BLOB il cui SHA1 == nome cartella sessione
    try:
        con = open_ro(clear_session)
        blobs = find_blobs(con, 16, 64)
        con.close()
        print(f"[3] BLOB candidati in session.db: {len(blobs)} "
              f"(lunghezze: {sorted({len(b) for _,_,b in blobs})})")
        client_key = None
        matched_folder = None
        for _t, _c, b in blobs:
            sha1 = hashlib.sha1(b).hexdigest().upper()
            if sha1 in (f.upper() for f in session_folders):
                client_key = b
                matched_folder = sha1
                break
        if client_key:
            print(f"[3] clientKey TROVATO ({len(client_key)}B): "
                  f"SHA1 == cartella sessione {matched_folder} ✓✓  "
                  f"(CHECKPOINT CHIAVE: la catena DPAPI/decifratura è CORRETTA)")
        else:
            print("[3][!] nessun BLOB con SHA1 == cartella sessione. "
                  "Stampo i candidati per analisi:")
            for t, c, b in blobs[:20]:
                print(f"      {t}.{c}: {len(b)}B sha1={hashlib.sha1(b).hexdigest().upper()}")
            return 5
    except Exception as e:
        print(f"[3][X] estrazione clientKey fallita: {e}")
        traceback.print_exc()
        return 5

    sess_folder = sessions_dir / matched_folder

    # 4) ODUID + dbKey -> decifra nativeSettings.db (valida l'ordine ODUID)
    native = sess_folder / "nativeSettings.db"
    if not native.exists():
        print(f"[4][X] nativeSettings.db non trovato in {sess_folder}")
        return 6

    oduid = None
    db_key = None
    if manual_oduid:
        candidates = [("manuale", bytes.fromhex(manual_oduid))]
    else:
        seed = read_random_seed()
        print(f"[4] RandomSeed letto: {len(seed)}B")
        candidates = [
            ("salt||seed", compute_oduid(seed, "salt_seed")),
            ("seed||salt", compute_oduid(seed, "seed_salt")),
        ]
    clear_native = None
    for label, cand in candidates:
        try:
            aux = hashlib.pbkdf2_hmac("sha256", client_key, cand, PBKDF2_ITERS, dklen=32)
            iv = hashlib.pbkdf2_hmac("sha256", aux, cand, PBKDF2_ITERS, dklen=16)
            key = _aes_cbc_encrypt_pkcs7(aux, iv, STATIC_BYTES)[:32]
            cn = decrypt_pair(native, key, out_dir, "nativeSettings")
            if is_plain_sqlite(cn):
                oduid, db_key, clear_native = cand, key, cn
                print(f"[4] ODUID '{label}' CORRETTO ✓ -> nativeSettings.db SQLite valido")
                break
            print(f"[4] ODUID '{label}': nativeSettings non valido, provo altro…")
        except Exception as e:
            print(f"[4] ODUID '{label}': errore {e}")
    if not clear_native:
        print("[4][X] nessun ordine ODUID ha prodotto un nativeSettings valido. "
              "Esegui ZAPiXDESK -GetID e ripassa con --oduid <hex>.")
        return 6

    # 5) chiavi tipo 1/2/3
    try:
        con = open_ro(clear_native)
        keytypes = find_keytypes(con)
        con.close()
        print(f"[5] chiavi in nativeSettings: { {k: len(v) for k,v in keytypes.items()} }")
        type1 = keytypes.get(1)
        if not type1:
            print("[5][X] chiave tipo 1 (messaggi) non trovata")
            return 7
    except Exception as e:
        print(f"[5][X] estrazione chiavi fallita: {e}")
        return 7

    # 6) decifra genericStorage.db (i MESSAGGI) e ispeziona
    generic = sess_folder / "genericStorage.db"
    if not generic.exists():
        print(f"[6][X] genericStorage.db non trovato in {sess_folder}")
        return 8
    try:
        clear_generic = decrypt_pair(generic, type1, out_dir, "genericStorage")
        ok = is_plain_sqlite(clear_generic)
        print(f"[6] genericStorage.db decifrato -> SQLite valido: {'SI ✓✓✓' if ok else 'NO ✗'}")
        if not ok:
            return 8
        con = open_ro(clear_generic)
        tables = list_tables(con)
        print(f"[6] tabelle ({len(tables)}): {tables}")
        for t in tables:
            try:
                n = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            except Exception:
                n = "?"
            print(f"      - {t}: {n} righe")
        # Stampa qualche riga delle tabelle che sembrano messaggi
        for t in tables:
            low = t.lower()
            if any(h in low for h in ("message", "msg", "chat", "conversation")):
                print(f"\n    --- esempio righe da '{t}' (max {limit}) ---")
                try:
                    cur = con.execute(f'SELECT * FROM "{t}" LIMIT {limit}')
                    cols = [d[0] for d in cur.description]
                    print(f"      colonne: {cols}")
                    for row in cur.fetchall():
                        vals = [
                            (v[:60] + "…") if isinstance(v, str) and len(v) > 60 else
                            (f"<{len(v)}B blob>" if isinstance(v, (bytes, bytearray)) else v)
                            for v in row
                        ]
                        print(f"      {vals}")
                except Exception as e:
                    print(f"      (lettura '{t}' fallita: {e})")
        con.close()
    except Exception as e:
        print(f"[6][X] decifratura/lettura genericStorage fallita: {e}")
        traceback.print_exc()
        return 8

    print("\n" + "=" * 66)
    print(" RISULTATO: catena di decifratura COMPLETA. I messaggi sono leggibili.")
    print(f" File decifrati in: {out_dir}")
    print(" Incolla l'intero output: mi serve per costruire il lettore/selettore.")
    print("=" * 66)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Spike decifratura WhatsApp Desktop")
    ap.add_argument("--localstate", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--oduid", default=None, help="ODUID a 32 byte in hex (override)")
    ap.add_argument("--limit", type=int, default=8)
    args = ap.parse_args()

    if sys.platform != "win32":
        print("Questo spike va eseguito su Windows (usa ncrypt.dll/winreg).")
        return 2

    ls = Path(args.localstate) if args.localstate else default_localstate()
    if not ls or not ls.is_dir():
        print("LocalState non trovato. Passa --localstate \"C:\\...\\LocalState\".")
        return 2
    out = Path(args.out) if args.out else Path(tempfile.gettempdir()) / "wa_spike_out"
    try:
        return run(ls, out, args.oduid, args.limit)
    except Exception:
        print("Errore imprevisto:\n" + traceback.format_exc())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
