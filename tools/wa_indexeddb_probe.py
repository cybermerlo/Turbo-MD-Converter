"""Probe SOLO-LETTURA dell'IndexedDB di WhatsApp Desktop (WebView2).

Serve a capire DOVE e COME vive il vero archivio messaggi (con mittente,
fromMe, tipo, media) per progettare l'estrazione dei MITTENTI. Il DB SQLite
`genericStorage` che già leggiamo è solo la cache di ricerca full-text: contiene
testo+chat+timestamp ma NON il mittente. Quei dati stanno nell'IndexedDB del
motore WebView2 (formato LevelDB).

Questo script NON si connette a nulla, NON decifra nulla, NON modifica nulla:
apre i file in sola lettura e riporta struttura, dimensioni e quanto testo è in
chiaro vs cifrato. Rischio ban: zero.

USO (Windows, con WhatsApp Desktop installato):

    python tools/wa_indexeddb_probe.py            # auto-trova il pacchetto
    python tools/wa_indexeddb_probe.py --root "C:\\...\\Packages\\5319275A..."

Incolla l'intero output: mi serve per progettare l'estrattore dei mittenti.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

PACKAGE_GLOB = "5319275A.WhatsAppDesktop_*"

# Token-spia: se compaiono IN CHIARO nei file LevelDB, i payload non sono cifrati
# (o lo sono solo in parte) e l'estrazione dei mittenti è fattibile leggendo qui.
SIGNAL_TOKENS = [
    b"fromMe", b"@g.us", b"@s.whatsapp.net", b"@lid", b"participant",
    b"messages", b"message", b"key", b"senderKeyHash", b"notifyName",
    b"pushName", b"mediaKey", b"directPath", b"mimetype", b"caption",
    b"WASignalStore", b"crypto", b"encKey", b"macKey", b"ciphertext",
]

# Limiti di scansione per restare veloci (basta un campione per capire il formato).
MAX_SCAN_PER_FILE = 4 * 1024 * 1024     # byte letti per singolo file
MAX_SCAN_TOTAL = 160 * 1024 * 1024      # byte totali scanditi per store
MAX_SCAN_FILES = 60                     # numero massimo di file (i più grandi)

# Tabella per contare i byte stampabili a velocità C (bytes.translate).
_NONPRINTABLE = bytes(
    c for c in range(256) if not (9 <= c <= 13 or 32 <= c <= 126)
)


def find_package_root(explicit: str | None) -> Path | None:
    if explicit:
        p = Path(explicit)
        return p if p.is_dir() else None
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return None
    for d in (Path(local) / "Packages").glob(PACKAGE_GLOB):
        if d.is_dir():
            return d
    return None


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}" if unit != "B" else f"{n}B"
        n /= 1024
    return f"{n:.1f}TB"


def find_leveldb_dirs(root: Path) -> list[Path]:
    """Cartelle che sembrano store LevelDB: contengono CURRENT + (MANIFEST|*.ldb|*.log)."""
    out: list[Path] = []
    for cur in root.rglob("CURRENT"):
        d = cur.parent
        names = {p.name for p in d.iterdir()} if d.is_dir() else set()
        has_ldb = any(n.endswith(".ldb") or n.endswith(".log") for n in names)
        has_manifest = any(n.startswith("MANIFEST") for n in names)
        if has_manifest or has_ldb:
            out.append(d)
    return sorted(set(out))


def dir_size(d: Path) -> int:
    total = 0
    for p in d.rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return total


def scan_tokens(d: Path) -> tuple[dict, list[str], float]:
    """Conta i token-spia e stima la frazione di byte stampabili nei .ldb/.log."""
    counts: dict[bytes, int] = {t: 0 for t in SIGNAL_TOKENS}
    samples: list[str] = []
    printable = 0
    scanned = 0
    files = sorted(
        [p for p in d.iterdir()
         if p.is_file() and (p.suffix in (".ldb", ".log") or p.name.startswith("MANIFEST"))],
        key=lambda p: p.stat().st_size, reverse=True,
    )[:MAX_SCAN_FILES]
    for f in files:
        if scanned >= MAX_SCAN_TOTAL:
            break
        try:
            data = f.read_bytes()[:MAX_SCAN_PER_FILE]
        except OSError:
            continue
        scanned += len(data)
        # Conteggio byte stampabili a velocità C: elimina i non-stampabili e misura.
        printable += len(data.translate(None, _NONPRINTABLE))
        for t in SIGNAL_TOKENS:
            counts[t] += data.count(t)
        # Cattura qualche contesto attorno a 'fromMe' e a un JID per capire il formato.
        for needle in (b"fromMe", b"@g.us"):
            idx = data.find(needle)
            if idx != -1 and len(samples) < 6:
                lo, hi = max(0, idx - 40), min(len(data), idx + 60)
                chunk = data[lo:hi]
                printable_chunk = bytes(c if 32 <= c <= 126 else 46 for c in chunk)
                samples.append(f"{f.name}: …{printable_chunk.decode('ascii', 'replace')}…")
    ratio = round(printable / scanned, 3) if scanned else 0.0
    return counts, samples, ratio


def main() -> int:
    ap = argparse.ArgumentParser(description="Probe read-only IndexedDB WhatsApp Desktop")
    ap.add_argument("--root", default=None, help="Cartella pacchetto (Packages\\5319275A...)")
    args = ap.parse_args()

    print("=" * 66)
    print(" Probe SOLO-LETTURA — IndexedDB WhatsApp Desktop (mittenti/media)")
    print("=" * 66)

    root = find_package_root(args.root)
    if not root:
        print("[X] Pacchetto WhatsApp Desktop non trovato.")
        print("    Passa --root \"C:\\Users\\<tu>\\AppData\\Local\\Packages\\5319275A...\"")
        return 2
    print(f"Pacchetto: {root}")

    leveldbs = find_leveldb_dirs(root)
    if not leveldbs:
        print("[!] Nessuno store LevelDB trovato sotto il pacchetto.")
        print("    (Forse l'IndexedDB è altrove o l'app non è sincronizzata.)")
        return 1

    print(f"\nStore LevelDB trovati: {len(leveldbs)}")
    # Ordina per dimensione: il più grande è quasi certamente l'archivio messaggi.
    sized = sorted(((d, dir_size(d)) for d in leveldbs), key=lambda x: x[1], reverse=True)

    for d, size in sized:
        rel = d.relative_to(root)
        print("\n" + "-" * 66)
        print(f"  {rel}")
        print(f"  dimensione totale: {human(size)}")
        files = [p for p in d.iterdir() if p.is_file()]
        n_ldb = sum(1 for p in files if p.suffix == ".ldb")
        n_log = sum(1 for p in files if p.suffix == ".log")
        print(f"  file: {len(files)}  (.ldb={n_ldb}, .log={n_log})")
        # Scansiona token solo sui primi store rilevanti per non essere lenti.
        if size < 5 * 1024 and "whatsapp" not in str(rel).lower():
            continue
        counts, samples, ratio = scan_tokens(d)
        hits = {t.decode(): c for t, c in counts.items() if c}
        print(f"  testo in chiaro ~{int(ratio * 100)}%  "
              f"(<40% ⇒ payload probabilmente cifrati)")
        if hits:
            top = sorted(hits.items(), key=lambda x: x[1], reverse=True)
            print(f"  token-spia: {dict(top)}")
        else:
            print("  token-spia: nessuno (payload cifrati o store non-WhatsApp)")
        for s in samples:
            print(f"    · {s}")

    print("\n" + "=" * 66)
    print(" Cosa guardare:")
    print(" - Lo store più grande con 'fromMe'/'@g.us' in chiaro è l'archivio")
    print("   messaggi: i mittenti sono estraibili leggendo il LevelDB.")
    print(" - Se 'testo in chiaro' è basso e i token mancano, i payload sono")
    print("   cifrati (servirà la chiave dell'IndexedDB: effort maggiore).")
    print(" Incolla tutto l'output.")
    print("=" * 66)
    return 0


if __name__ == "__main__":
    if sys.platform != "win32":
        print("Nota: percorsi/registro sono Windows; esegui sul PC con WhatsApp Desktop.")
    raise SystemExit(main())
