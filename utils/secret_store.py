"""Archiviazione sicura dei segreti (chiavi API, chiave backup WhatsApp).

Su Windows i segreti vanno nel **Credential Manager** (DPAPI, per-utente) tramite
la libreria `keyring`, invece che in chiaro dentro `config.json`. Se il keyring
non è disponibile — libreria assente, nessun backend utilizzabile, oppure
disabilitato a mano con la variabile d'ambiente ``TURBOMD_DISABLE_KEYRING`` — i
segreti restano nel JSON come prima: meglio un fallback in chiaro che perdere le
chiavi dell'utente.

Uso tipico (vedi config/settings.py):
- in salvataggio: ``set_secret(name, value)``; se ritorna True il chiamante può
  azzerare il campo nel JSON (segreto al sicuro nel keyring).
- in caricamento: ``get_secret(name)``; se ritorna un valore, vince su quello del
  JSON (che resta solo come fallback legacy finché non si risalva).
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# Nome del "service" sotto cui vengono registrate le credenziali.
SERVICE_NAME = "TurboMDConverter"

# Campi di AppConfig considerati segreti: non vanno mai scritti in chiaro nel
# config.json quando un keyring è disponibile.
SECRET_FIELDS = (
    "gemini_api_key",
    "langextract_api_key",
    "elevenlabs_api_key",
    "whatsapp_backup_key",
)

_keyring_module = None
_import_attempted = False


def _keyring():
    """Ritorna il modulo `keyring` se utilizzabile, altrimenti None.

    La decisione di disabilitazione via env è ricontrollata a ogni chiamata
    (così i test possono attivarla/disattivarla); l'import vero e proprio è
    memorizzato.
    """
    if os.environ.get("TURBOMD_DISABLE_KEYRING"):
        return None
    global _keyring_module, _import_attempted
    if not _import_attempted:
        _import_attempted = True
        try:
            import keyring  # type: ignore
            _keyring_module = keyring
        except Exception as e:  # pragma: no cover - dipende dall'ambiente
            logger.info(
                "Keyring non disponibile (%s): i segreti restano nel config.json.",
                e,
            )
            _keyring_module = None
    return _keyring_module


def is_available() -> bool:
    """True se un keyring utilizzabile è presente."""
    return _keyring() is not None


def get_secret(name: str) -> str | None:
    """Legge un segreto dal keyring. Ritorna None se assente o non disponibile."""
    kr = _keyring()
    if kr is None:
        return None
    try:
        return kr.get_password(SERVICE_NAME, name)
    except Exception as e:  # pragma: no cover - dipende dal backend
        logger.info("Lettura keyring fallita per '%s': %s", name, e)
        return None


def set_secret(name: str, value: str) -> bool:
    """Scrive (o cancella, se ``value`` è vuoto) un segreto nel keyring.

    Ritorna True se l'operazione è andata a buon fine (il chiamante può quindi
    azzerare il campo nel JSON), False se il keyring non è disponibile o ha
    fallito (il chiamante deve tenere il valore nel JSON come fallback).
    """
    kr = _keyring()
    if kr is None:
        return False
    try:
        if value:
            kr.set_password(SERVICE_NAME, name, value)
        else:
            delete_secret(name)
        return True
    except Exception as e:  # pragma: no cover - dipende dal backend
        logger.info("Scrittura keyring fallita per '%s': %s", name, e)
        return False


def delete_secret(name: str) -> None:
    """Rimuove un segreto dal keyring, se presente (no-op altrimenti)."""
    kr = _keyring()
    if kr is None:
        return
    try:
        kr.delete_password(SERVICE_NAME, name)
    except Exception:
        # Tipicamente PasswordDeleteError quando la voce non esiste: ignora.
        pass
