"""Spike esplorativo dell'IndexedDB di WhatsApp Desktop (mittenti/media).

Il probe ha confermato che l'archivio messaggi sta in
`...\\IndexedDB\\https_web.whatsapp.com_0.indexeddb.leveldb` ed è IN CHIARO, ma
nel formato IndexedDB di Chromium + serializzazione V8. Questo spike usa
`ccl_chromium_reader` (MIT, puro Python) per:

  1. copiare i file LevelDB in una cartella temporanea (il DB live è bloccato),
  2. elencare database e object store dell'IndexedDB di WhatsApp,
  3. stampare qualche record di esempio degli store che sembrano messaggi/contatti
     per scoprire i nomi dei campi (mittente, fromMe, timestamp, testo, media).

NON si connette a nulla, NON modifica nulla, NON scrive nella cartella di WA.

PREPARAZIONE (una volta sola, nel venv del progetto):

    pip install ccl_chromium_reader

USO (Windows, con WhatsApp Desktop installato):

    python tools/wa_indexeddb_spike.py
    python tools/wa_indexeddb_spike.py --samples 4 --store message

Incolla l'intero output: mi serve per costruire l'estrazione dei mittenti.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

PACKAGE_GLOB = "5319275A.WhatsAppDesktop_*"
LEVELDB_REL = r"LocalCache\EBWebView\Default\IndexedDB\https_web.whatsapp.com_0.indexeddb.leveldb"

# Store il cui contenuto vogliamo campionare per scoprire lo schema.
INTERESTING = ("message", "msg", "chat", "contact", "participant", "group")


def find_leveldb(explicit: str | None) -> Path | None:
    if explicit:
        p = Path(explicit)
        return p if p.is_dir() else None
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return None
    for pkg in (Path(local) / "Packages").glob(PACKAGE_GLOB):
        cand = pkg / LEVELDB_REL
        if cand.is_dir():
            return cand
    return None


def copy_leveldb(src: Path, dst: Path) -> tuple[int, int]:
    """Copia i file LevelDB (i .ldb sono immutabili → copiabili; il .log aperto
    può dare sharing violation: in tal caso lo saltiamo)."""
    dst.mkdir(parents=True, exist_ok=True)
    ok = skipped = 0
    for f in src.iterdir():
        if not f.is_file():
            continue
        try:
            shutil.copy2(f, dst / f.name)
            ok += 1
        except (PermissionError, OSError):
            skipped += 1
    return ok, skipped


def short(v, n: int = 70) -> str:
    if isinstance(v, (bytes, bytearray)):
        return f"<{len(v)}B blob>"
    s = repr(v)
    return s if len(s) <= n else s[:n] + "…"


def describe_value(value) -> str:
    """Riassume un valore deserializzato (dict atteso) mostrando le chiavi e
    un campione dei campi utili al riconoscimento di mittente/testo/timestamp."""
    if isinstance(value, dict):
        keys = list(value.keys())
        out = [f"keys={keys}"]
        for probe in ("id", "key", "from", "to", "author", "participant",
                      "fromMe", "type", "t", "ts", "timestamp", "body", "text",
                      "caption", "notifyName", "senderUserJid", "mediaKey"):
            if probe in value:
                out.append(f"{probe}={short(value[probe], 50)}")
        return "  ".join(out)
    return f"({type(value).__name__}) {short(value, 90)}"


def run(leveldb: Path, samples: int, only_store: str | None) -> int:
    print("=" * 66)
    print(" Spike IndexedDB WhatsApp Desktop — scoperta schema mittenti")
    print("=" * 66)
    try:
        import ccl_chromium_reader  # noqa: F401
        from ccl_chromium_reader import ccl_chromium_indexeddb
        ver = getattr(ccl_chromium_reader, "__version__", "?")
        print(f"ccl_chromium_reader: OK (v{ver})")
    except ImportError:
        print("[X] manca ccl_chromium_reader. Esegui:  pip install ccl_chromium_reader")
        return 2

    print(f"LevelDB (sorgente): {leveldb}")
    blob = leveldb.with_name(leveldb.name.replace(".leveldb", ".blob"))
    blob_arg = blob if blob.is_dir() else None
    print(f"Blob dir          : {blob_arg or '(assente)'}")

    tmp = Path(tempfile.mkdtemp(prefix="wa_idb_"))
    ldb_copy = tmp / "leveldb"
    print(f"Copia in          : {ldb_copy}")
    ok, skipped = copy_leveldb(leveldb, ldb_copy)
    print(f"File copiati: {ok}  (saltati/bloccati: {skipped})")
    blob_copy = None
    if blob_arg:
        blob_copy = tmp / "blob"
        try:
            shutil.copytree(blob_arg, blob_copy, dirs_exist_ok=True)
        except Exception as e:  # noqa: BLE001
            print(f"(copia blob fallita, proseguo senza: {e})")
            blob_copy = None

    try:
        # La firma accetta (leveldb, blob); alcune versioni accettano solo leveldb.
        try:
            wrapper = ccl_chromium_indexeddb.WrappedIndexDB(str(ldb_copy), str(blob_copy) if blob_copy else None)
        except TypeError:
            wrapper = ccl_chromium_indexeddb.WrappedIndexDB(str(ldb_copy))

        dbids = list(wrapper.database_ids)
        print(f"\n[1] Database IndexedDB trovati: {len(dbids)}")
        for d in dbids:
            print(f"    - {short(d, 90)}")

        for d in dbids:
            # Apri il database in modo difensivo (per id numerico o per nome).
            db = None
            for accessor in (getattr(d, "dbid_no", None), getattr(d, "name", None), d):
                if accessor is None:
                    continue
                try:
                    db = wrapper[accessor]
                    break
                except Exception:
                    continue
            if db is None:
                print(f"\n[!] impossibile aprire database {short(d, 60)}")
                continue
            try:
                stores = list(db.object_store_names)
            except Exception as e:  # noqa: BLE001
                print(f"\n[!] object_store_names fallito per {short(d, 60)}: {e}")
                continue
            print(f"\n[2] DB {short(getattr(d, 'name', d), 50)} → {len(stores)} object store:")
            print(f"    {stores}")

            for sname in stores:
                if only_store and only_store.lower() not in sname.lower():
                    continue
                if not only_store and not any(h in sname.lower() for h in INTERESTING):
                    continue
                try:
                    store = db[sname]
                except Exception as e:  # noqa: BLE001
                    print(f"      [{sname}] apertura fallita: {e}")
                    continue
                print(f"\n    --- store '{sname}': primi {samples} record ---")
                n = 0
                try:
                    for rec in store.iterate_records():
                        key = getattr(rec, "user_key", getattr(rec, "key", "?"))
                        print(f"      key={short(key, 80)}")
                        print(f"        {describe_value(getattr(rec, 'value', None))}")
                        n += 1
                        if n >= samples:
                            break
                except Exception as e:  # noqa: BLE001
                    print(f"      (iterazione '{sname}' fallita: {e})")
                if n == 0:
                    print("      (nessun record o store vuoto)")
    except Exception:
        print("Errore imprevisto:\n" + traceback.format_exc())
        return 1
    finally:
        try:
            shutil.rmtree(tmp, ignore_errors=True)
        except Exception:
            pass

    print("\n" + "=" * 66)
    print(" Cosa mi serve dall'output: i NOMI degli store messaggi/contatti e i")
    print(" CAMPI dei valori (mittente, fromMe, timestamp, testo). Incolla tutto.")
    print("=" * 66)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Spike IndexedDB WhatsApp Desktop")
    ap.add_argument("--leveldb", default=None, help="Percorso cartella .indexeddb.leveldb")
    ap.add_argument("--samples", type=int, default=3, help="Record di esempio per store")
    ap.add_argument("--store", default=None, help="Filtra a uno store (substring)")
    args = ap.parse_args()

    if sys.platform != "win32":
        print("Nota: esegui sul PC Windows con WhatsApp Desktop installato.")

    ldb = find_leveldb(args.leveldb)
    if not ldb:
        print("[X] LevelDB non trovato. Passa --leveldb \"C:\\...\\https_web.whatsapp.com_0.indexeddb.leveldb\"")
        return 2
    try:
        return run(ldb, args.samples, args.store)
    except Exception:
        print("Errore imprevisto:\n" + traceback.format_exc())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
