"""Decifratura del backup WhatsApp (msgstore.db.crypt15) tramite wa-crypt-tools.

Per robustezza verso i cambi di API interna della libreria, si pilota la sua CLI
stabile (`wadecrypt <chiave> <cifrato> <output>`) chiamando `wadecrypt.main()` con
`sys.argv` temporaneamente sostituito. L'output viene poi validato come SQLite.
"""

from __future__ import annotations

import gc
import io
import re
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

SQLITE_MAGIC = b"SQLite format 3\x00"
_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")


class BackupDecryptError(Exception):
    """Decifratura del backup fallita."""


def normalize_key(raw: str) -> str:
    """Pulisce e valida la chiave a 64 cifre esadecimali (rimuove spazi/trattini)."""
    cleaned = re.sub(r"[\s\-]+", "", raw or "")
    if not _HEX64.match(cleaned):
        raise BackupDecryptError(
            "Chiave di backup non valida: servono 64 caratteri esadecimali "
            "(la chiave del backup cifrato end-to-end di WhatsApp)."
        )
    return cleaned.lower()


def decrypt_msgstore(encrypted: Path, key_hex: str, output: Path) -> Path:
    """Decifra msgstore.db.crypt15 → SQLite in chiaro. Ritorna `output`.

    Solleva BackupDecryptError con un messaggio comprensibile in caso di chiave
    errata, formato non supportato o libreria mancante.
    """
    key_hex = normalize_key(key_hex)
    encrypted = Path(encrypted)
    output = Path(output)

    if not encrypted.exists():
        raise BackupDecryptError(f"File cifrato non trovato: {encrypted}")

    try:
        from wa_crypt_tools import wadecrypt
    except Exception as e:  # pragma: no cover - dipende dall'ambiente
        raise BackupDecryptError(
            "Libreria 'wa-crypt-tools' non disponibile. Reinstalla l'applicazione "
            "(o esegui: pip install wa-crypt-tools)."
        ) from e

    output.parent.mkdir(parents=True, exist_ok=True)

    buf_out, buf_err = io.StringIO(), io.StringIO()
    argv_backup = sys.argv
    sys.argv = ["wadecrypt", key_hex, str(encrypted), str(output)]
    try:
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            wadecrypt.main()
    except SystemExit as e:
        if e.code not in (0, None):
            raise BackupDecryptError(
                _error_message(buf_err.getvalue() or buf_out.getvalue())
            ) from e
    except BackupDecryptError:
        raise
    except Exception as e:
        raise BackupDecryptError(
            _error_message(str(e) or buf_err.getvalue())
        ) from e
    finally:
        sys.argv = argv_backup
        # wadecrypt.main() apre il file di output con argparse.FileType e non lo
        # chiude esplicitamente nel percorso predefinito: forziamo il flush su
        # disco prima di validare il risultato.
        gc.collect()

    if not output.exists() or output.stat().st_size == 0:
        raise BackupDecryptError(
            _error_message(buf_err.getvalue() or buf_out.getvalue())
        )

    with output.open("rb") as fh:
        if fh.read(len(SQLITE_MAGIC)) != SQLITE_MAGIC:
            raise BackupDecryptError(
                "Decifratura non riuscita: chiave errata o backup non compatibile "
                "(il risultato non è un database SQLite valido)."
            )
    return output


def _error_message(detail: str) -> str:
    detail = (detail or "").strip()
    base = (
        "Decifratura del backup fallita. Controlla che la chiave a 64 cifre sia "
        "corretta e che il backup sia in formato crypt15 (end-to-end)."
    )
    return f"{base}\nDettagli: {detail}" if detail else base
