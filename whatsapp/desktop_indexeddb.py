"""Lettura dell'IndexedDB di WhatsApp Desktop (mittenti, nomi gruppo, contatti).

Il SQLite `genericStorage` che decifriamo (vedi `desktop_crypto.py`) è solo la
cache di ricerca full-text: ha testo + chat + timestamp ma NON il mittente. I dati
veri stanno nell'IndexedDB del WebView2 (LevelDB + serializzazione V8), in chiaro
tranne il corpo del messaggio (cifrato). Qui leggiamo ciò che serve a v2:

  - **mittente per messaggio**: `model-storage/message` → `rowId` (== id di
    genericStorage), `fromMe` (prefisso `true_`/`false_` dell'id), `author` (per i
    gruppi, il @lid di chi ha scritto). Il testo arriva da genericStorage, unito
    per `rowId`.
  - **nome dei gruppi**: `model-storage/group-metadata` → `subject`.
  - **nomi contatti**: `model-storage/contact` (@lid → nome + numero) e
    `out-contact` (@s.whatsapp.net → nome).

Lettore: `ccl_chromium_reader` **vendorizzato** in `whatsapp/_vendor/`. Si legge
una **COPIA** dei file (il DB live è bloccato). Solo lettura locale.

**Performance.** Aprire l'IndexedDB legge ~2 milioni di record raw (~1 min, costo
inevitabile). Deserializzare TUTTI i ~300k messaggi costerebbe altri ~2-3 min, ma
non serve: i mittenti si estraggono **per-chat** filtrando le chiavi per `chatJid`
PRIMA della deserializzazione V8 (`_ScopedSenders`), così si deserializza solo la
chat richiesta (~5s). Risultato: ~1 min all'apertura + ~5s per chat. Il wrapper
resta aperto per la sessione (qualche centinaio di MB) e viene liberato a `close()`.
"""

from __future__ import annotations

import atexit
import hashlib
import json
import logging
import os
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

_log = logging.getLogger(__name__)

PACKAGE_GLOB = "5319275A.WhatsAppDesktop_*"
LEVELDB_REL = (
    r"LocalCache\EBWebView\Default\IndexedDB"
    r"\https_web.whatsapp.com_0.indexeddb.leveldb"
)
MODEL_DB = "model-storage"

ProgressFn = Callable[[int], None]

# Valori speciali di `progress(n)` (n>=0 = messaggi processati nel fallback):
PROGRESS_FROM_CACHE = -1     # (riservato; non usato dall'approccio scoped)
PROGRESS_OPENING = -2        # apertura IndexedDB in corso (~1 min, niente conteggio)
PROGRESS_SCANNING = -3       # scansione mittenti della chat in corso


# ─── localizzazione dei file IndexedDB ───────────────────────────────────────
def find_leveldb(explicit: Optional[Path] = None) -> Optional[Path]:
    """Cartella `...indexeddb.leveldb` di WhatsApp Desktop, o None."""
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


def _copy_tree_files(src: Path, dst: Path) -> None:
    """Copia i file di una cartella LevelDB. I `.ldb` sono immutabili; il `.log`
    aperto può dare sharing violation → lo saltiamo (i messaggi più recenti
    possono mancare, accettabile)."""
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.iterdir():
        if not f.is_file():
            continue
        try:
            shutil.copy2(f, dst / f.name)
        except (PermissionError, OSError):
            pass


def _fingerprint(leveldb: Path) -> str:
    """Impronta dei soli `.ldb` (sstable immutabili: nome+dimensione). Cambia
    quando LevelDB fa flush/compaction → l'indice condiviso si ricostruisce. Le
    scritture normali (nuovi messaggi nel `.log`) NON la cambiano: l'indice resta
    valido per la sessione."""
    parts = []
    for f in sorted(leveldb.glob("*.ldb"), key=lambda p: p.name):
        try:
            parts.append(f"{f.name}|{f.stat().st_size}")
        except OSError:
            pass
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


# ─── cache su disco della mappa mittenti (per evitare i ~60s tra riavvii) ─────
CACHE_VERSION = 1


def _default_cache_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "OCRLangExtract" / "wa_cache"


def _encode_sender(s: "Sender"):
    if s.from_me:
        return 1
    return s.author_jid if s.author_jid else 0


def _decode_sender(v) -> "Sender":
    if v == 1:
        return Sender(True, None)
    if v == 0:
        return Sender(False, None)
    return Sender(False, v)


def _cache_file(cache_dir: Optional[Path] = None) -> Path:
    return (Path(cache_dir) if cache_dir else _default_cache_dir()) / "index.json"


def _save_cache(cache_file: Path, fingerprint: str, idx: "WhatsAppIndex") -> None:
    """Scrive la mappa mittenti + nomi su disco (scrittura atomica)."""
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": CACHE_VERSION,
        "fingerprint": fingerprint,
        "senders": {str(k): _encode_sender(v) for k, v in idx.senders.items()},
        "group_subjects": idx.group_subjects,
        "name_by_jid": idx.name_by_jid,
        "lid_to_phone": idx.lid_to_phone,
    }
    tmp = cache_file.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    tmp.replace(cache_file)


def _load_cache(cache_file: Path, fingerprint: str) -> Optional["WhatsAppIndex"]:
    """Carica l'indice dalla cache se il fingerprint combacia. None altrimenti."""
    if not cache_file.is_file():
        return None
    try:
        with cache_file.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if data.get("version") != CACHE_VERSION or data.get("fingerprint") != fingerprint:
        return None
    try:
        senders = {int(k): _decode_sender(v)
                   for k, v in data.get("senders", {}).items()}
        return WhatsAppIndex(
            group_subjects=dict(data.get("group_subjects", {})),
            name_by_jid=dict(data.get("name_by_jid", {})),
            lid_to_phone=dict(data.get("lid_to_phone", {})),
            senders=senders,   # mappa completa → senders_for_chat la usa, niente wrapper
        )
    except (ValueError, TypeError):
        return None


# ─── helper sui valori deserializzati ────────────────────────────────────────
def _as_str(v) -> Optional[str]:
    """Ritorna la stringa solo se `v` è davvero una stringa non vuota.
    (ccl usa un sentinella `Undefined` per i campi assenti: non è una str.)"""
    return v if isinstance(v, str) and v else None


def _bare(jid: str) -> str:
    return jid.split("@", 1)[0] if jid else jid


# ─── strutture dati ──────────────────────────────────────────────────────────
@dataclass
class Sender:
    """Mittente di un messaggio, ricavato dall'IndexedDB."""
    from_me: bool
    author_jid: Optional[str] = None   # per i gruppi: @lid di chi ha scritto


@dataclass
class WhatsAppIndex:
    """Indici estratti dall'IndexedDB, già pronti per la risoluzione nomi.

    I mittenti si ottengono **per-chat** via `senders_for_chat` (veloce). Il campo
    `senders` è usato solo quando l'indice è iniettato (test) o pre-calcolato: in
    quel caso `senders_for_chat` lo ritorna così com'è.
    """
    group_subjects: dict[str, str] = field(default_factory=dict)   # groupJid → nome
    name_by_jid: dict[str, str] = field(default_factory=dict)      # jid/numero → nome
    lid_to_phone: dict[str, str] = field(default_factory=dict)     # @lid → numero@c.us
    senders: dict[int, Sender] = field(default_factory=dict)       # rowId → Sender
    _scoped: Optional["_ScopedSenders"] = field(default=None, repr=False)

    def senders_for_chat(self, chat_id: str) -> dict[int, Sender]:
        """Mappa `rowId → Sender` per i messaggi di `chat_id`."""
        if self._scoped is not None:
            return self._scoped.for_chat(chat_id)
        return self.senders

    def close(self) -> None:
        """Libera il wrapper IndexedDB e la copia temporanea dei file."""
        if self._scoped is not None:
            self._scoped.close()
            self._scoped = None

    # ── risoluzione nomi ─────────────────────────────────────────────────────
    def name_for(self, jid: Optional[str]) -> Optional[str]:
        """Miglior nome noto per un JID (contatto, numero), o None."""
        if not jid:
            return None
        n = self.name_by_jid.get(jid) or self.name_by_jid.get(_bare(jid))
        if n:
            return n
        phone = self.lid_to_phone.get(jid)
        if phone:
            n = self.name_by_jid.get(phone) or self.name_by_jid.get(_bare(phone))
            if n:
                return n
        return None

    def phone_for(self, jid: Optional[str]) -> Optional[str]:
        """Numero di telefono (solo cifre) per un JID, se ricavabile."""
        if not jid:
            return None
        if jid.endswith("@c.us") or jid.endswith("@s.whatsapp.net"):
            num = _bare(jid)
            return num if num.isdigit() else None
        phone = self.lid_to_phone.get(jid)
        if phone:
            num = _bare(phone)
            return num if num.isdigit() else None
        return None

    def group_title(self, group_jid: str) -> Optional[str]:
        return self.group_subjects.get(group_jid)


class _ScopedSenders:
    """Estrae i mittenti di UNA chat alla volta dal wrapper IndexedDB aperto,
    filtrando le chiavi `message` per `chatJid` PRIMA della deserializzazione V8
    (le chiavi sono `<fromMe>_<chatJid>_<msgId>[_<author@lid>]`). Così si
    deserializza solo la chat richiesta (~5s) invece di tutti i ~300k messaggi.

    Dipende da dettagli **interni** di ccl (pacchetto vendorizzato e *fissato*):
    `store._raw_db`, `make_prefix`, `_fetched_records`, `read_record_precursor`,
    `IdbKey`, `_le_varint_from_bytes`. Se cambiano, `open_index` usa il fallback
    full-scan. Tiene aperto il wrapper finché non si chiama `close()`."""

    def __init__(self, wrapper, store, tmpdir: Path):
        from whatsapp._vendor.ccl_chromium_reader.serialization_formats import (
            ccl_blink_value_deserializer,
        )
        self._wrapper = wrapper
        self._tmp = tmpdir
        self._raw = store._raw_db
        self._dbid = store._dbid_no
        self._sid = store._obj_store_id
        self._prefix = self._raw.make_prefix(self._dbid, self._sid, 1)
        self._blink = ccl_blink_value_deserializer.BlinkV8Deserializer()
        self._cache: dict[str, dict[int, Sender]] = {}

    def for_chat(self, chat_id: str) -> dict[int, Sender]:
        if chat_id in self._cache:
            return self._cache[chat_id]
        from whatsapp._vendor.ccl_chromium_reader.ccl_chromium_indexeddb import (
            IdbKey, _le_varint_from_bytes,
        )
        from whatsapp._vendor.ccl_chromium_reader.serialization_formats import (
            ccl_v8_value_deserializer,
        )
        _t0 = time.perf_counter()
        want = (f"false_{chat_id}_", f"true_{chat_id}_")
        prefix, raw = self._prefix, self._raw
        out: dict[int, Sender] = {}
        n = 0
        for rec in raw._fetched_records:
            if not rec.key.startswith(prefix):
                continue
            n += 1
            if (n & 0x3FFF) == 0:
                time.sleep(0)                    # cede il GIL: UI reattiva
            key = IdbKey(rec.key[len(prefix):])
            ks = key.value
            if not isinstance(ks, str) or not ks.startswith(want):
                continue
            if not rec.value:
                continue
            _, varint_raw = _le_varint_from_bytes(rec.value)
            precursor = raw.read_record_precursor(
                key, self._dbid, self._sid, rec.value[len(varint_raw):], None)
            if precursor is None:
                continue
            _, obj_raw, _, _ = precursor
            try:
                value = ccl_v8_value_deserializer.Deserializer(
                    obj_raw, host_object_delegate=self._blink.read).read()
            except Exception:  # noqa: BLE001 — record illeggibile: salta
                continue
            if not isinstance(value, dict):
                continue
            rid = value.get("rowId")
            if not isinstance(rid, (int, float)):
                continue
            mid = value.get("id")
            from_me = isinstance(mid, str) and mid.startswith("true_")
            author = value.get("author")
            auth = author.get("_serialized") if isinstance(author, dict) else None
            # author serve solo per i messaggi ALTRUI nei gruppi; per i miei
            # (from_me) si rende sempre "Tu" → non lo memorizziamo (dato canonico).
            out[int(rid)] = Sender(from_me, None if from_me else _as_str(auth))
        self._cache[chat_id] = out
        _log.info("WA-idx: scoped chat %s -> %d mittenti in %.2fs",
                  chat_id, len(out), time.perf_counter() - _t0)
        return out

    def close(self) -> None:
        self._wrapper = None
        self._raw = None
        self._cache.clear()
        shutil.rmtree(self._tmp, ignore_errors=True)


def _has_scoped_internals(store) -> bool:
    raw = getattr(store, "_raw_db", None)
    return bool(
        raw is not None
        and hasattr(raw, "make_prefix")
        and hasattr(raw, "_fetched_records")
        and hasattr(raw, "read_record_precursor")
        and hasattr(store, "_dbid_no")
        and hasattr(store, "_obj_store_id")
    )


# ─── indice condiviso a livello di processo ──────────────────────────────────
# L'indice è costoso da costruire (~1 min: lettura LevelDB). Lo teniamo VIVO per
# l'intera sessione dell'app e lo riusiamo tra una finestra di import e l'altra,
# così solo la PRIMA creazione-MD paga l'attesa; le successive sono istantanee.
# Si ricostruisce solo se il DB è cambiato (nuovi `.ldb`: flush/compaction).
_shared_index: Optional[WhatsAppIndex] = None
_shared_fingerprint: Optional[str] = None
_shared_lock = threading.Lock()


def get_index(localstate_leveldb: Optional[Path] = None,
              progress: Optional[ProgressFn] = None) -> Optional[WhatsAppIndex]:
    """Ritorna l'indice condiviso, costruendolo solo se assente o se il DB è
    cambiato (fingerprint dei `.ldb`). Thread-safe. **Da NON chiudere** dal
    chiamante: la sua vita è gestita qui (chiusura all'uscita dell'app)."""
    global _shared_index, _shared_fingerprint
    leveldb = find_leveldb(localstate_leveldb)
    if not leveldb:
        return None
    try:
        fp = _fingerprint(leveldb)
    except Exception:  # noqa: BLE001
        fp = None
    with _shared_lock:
        if _shared_index is not None and fp is not None and _shared_fingerprint == fp:
            if progress is not None:
                progress(PROGRESS_FROM_CACHE)
            _log.info("WA-idx: indice condiviso riusato (nessuna ricostruzione)")
            return _shared_index
        # DB cambiato o prima volta: ricostruisci (chiudi il vecchio)
        if _shared_index is not None:
            try:
                _shared_index.close()
            except Exception:  # noqa: BLE001
                pass
            _shared_index = None
            _shared_fingerprint = None
        idx = open_index(localstate_leveldb, progress)
        if idx is not None:
            _shared_index = idx
            _shared_fingerprint = fp
        return idx


@atexit.register
def _close_shared_index() -> None:
    global _shared_index, _shared_fingerprint
    if _shared_index is not None:
        try:
            _shared_index.close()
        except Exception:  # noqa: BLE001
            pass
        _shared_index = None
        _shared_fingerprint = None


# ─── build completo in background → scrive la cache su disco ─────────────────
_cache_build_lock = threading.Lock()
_cache_build_active: set = set()


def _spawn_cache_build(store, base_idx: "WhatsAppIndex", fingerprint: Optional[str]) -> None:
    """Costruisce in un thread daemon la mappa mittenti COMPLETA (deserializza
    tutti i messaggi: ~2 min) riusando il wrapper già aperto, e la salva su disco.
    Non blocca: serve solo a velocizzare i PROSSIMI avvii dell'app. Un solo build
    per fingerprint alla volta."""
    if not fingerprint:
        return
    with _cache_build_lock:
        if fingerprint in _cache_build_active:
            return
        _cache_build_active.add(fingerprint)

    def _worker():
        try:
            full = WhatsAppIndex(
                group_subjects=dict(base_idx.group_subjects),
                name_by_jid=dict(base_idx.name_by_jid),
                lid_to_phone=dict(base_idx.lid_to_phone),
            )
            t0 = time.perf_counter()
            _load_senders(store, full, None)
            if full.senders:
                _save_cache(_cache_file(), fingerprint, full)
                _log.info("WA-idx: CACHE SU DISCO scritta (%d mittenti) in %.0fs "
                          "(background)", len(full.senders), time.perf_counter() - t0)
        except Exception as e:  # noqa: BLE001 — best-effort, mai fatale
            _log.info("WA-idx: build cache su disco non riuscito (ignorato): %s", e)
        finally:
            with _cache_build_lock:
                _cache_build_active.discard(fingerprint)

    threading.Thread(target=_worker, name="wa-idx-cache", daemon=True).start()


# ─── apertura dell'indice (costruttore + cache su disco) ─────────────────────
def open_index(localstate_leveldb: Optional[Path] = None,
               progress: Optional[ProgressFn] = None,
               workdir: Optional[Path] = None) -> Optional[WhatsAppIndex]:
    """Apre l'IndexedDB (copia temporanea), estrae nomi gruppo/contatti e prepara
    l'estrazione mittenti **per-chat**. Ritorna un `WhatsAppIndex` da chiudere con
    `.close()` (tiene aperto il wrapper). None se l'IndexedDB non è leggibile →
    il chiamante degrada a solo testo. `progress(n)` riceve i valori speciali
    `PROGRESS_*` e, nel fallback full-scan, il conteggio messaggi."""
    leveldb = find_leveldb(localstate_leveldb)
    if not leveldb:
        return None

    # 0) cache su disco: se i `.ldb` non sono cambiati, carica la mappa mittenti
    #    da disco e SALTA del tutto la lettura del LevelDB (~60s) → solo ~3s.
    try:
        fingerprint = _fingerprint(leveldb)
    except Exception:  # noqa: BLE001
        fingerprint = None
    if fingerprint:
        cached = _load_cache(_cache_file(), fingerprint)
        if cached is not None:
            if progress is not None:
                progress(PROGRESS_FROM_CACHE)
            _log.info("WA-idx: caricato da CACHE SU DISCO (%d mittenti, niente "
                      "lettura LevelDB)", len(cached.senders))
            return cached

    try:
        from whatsapp._vendor.ccl_chromium_reader import ccl_chromium_indexeddb  # noqa: F401
    except Exception:  # noqa: BLE001 — lettore vendorizzato assente/rotto
        return None

    if progress is not None:
        progress(PROGRESS_OPENING)
    tmp = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="wa_idb_"))
    ldb_copy = tmp / "leveldb"
    t0 = time.perf_counter()
    _copy_tree_files(leveldb, ldb_copy)
    blob_src = leveldb.with_name(leveldb.name.replace(".leveldb", ".blob"))
    blob_copy = None
    if blob_src.is_dir():
        blob_copy = tmp / "blob"
        try:
            shutil.copytree(blob_src, blob_copy, dirs_exist_ok=True)
        except Exception:  # noqa: BLE001
            blob_copy = None
    _log.info("WA-idx: copia file LevelDB+blob in %.1fs", time.perf_counter() - t0)

    keep_open = False
    try:
        t0 = time.perf_counter()
        try:
            wrapper = ccl_chromium_indexeddb.WrappedIndexDB(
                str(ldb_copy), str(blob_copy) if blob_copy else None)
        except TypeError:
            wrapper = ccl_chromium_indexeddb.WrappedIndexDB(str(ldb_copy))
        _log.info("WA-idx: apertura wrapper (lettura LevelDB) in %.1fs",
                  time.perf_counter() - t0)

        db = wrapper[MODEL_DB]
        stores = set(db.object_store_names)
        idx = WhatsAppIndex()

        # nomi gruppo + contatti (store piccoli: pochi secondi)
        t0 = time.perf_counter()
        if "group-metadata" in stores:
            _load_group_subjects(db["group-metadata"], idx)
        if "contact" in stores:
            _load_contacts(db["contact"], idx)
        if "out-contact" in stores:
            _load_out_contacts(db["out-contact"], idx)
        _log.info("WA-idx: nomi (gruppi=%d, contatti=%d, lid-num=%d) in %.1fs",
                  len(idx.group_subjects), len(idx.name_by_jid),
                  len(idx.lid_to_phone), time.perf_counter() - t0)

        # mittenti: scoped (veloce) se gli interni ccl ci sono, altrimenti full-scan
        if "message" in stores:
            store = db["message"]
            if _has_scoped_internals(store):
                idx._scoped = _ScopedSenders(wrapper, store, tmp)
                keep_open = True   # il wrapper/tmp resta vivo fino a idx.close()
                _log.info("WA-idx: mittenti in modalità scoped (per-chat)")
                # build completo in BACKGROUND (il wrapper è già aperto: solo
                # +deserializzazione) → scrive la cache su disco per i prossimi
                # AVVII dell'app, che salteranno i ~60s di lettura LevelDB.
                _spawn_cache_build(store, idx, fingerprint)
            else:
                _log.info("WA-idx: interni ccl assenti → fallback full-scan mittenti")
                t0 = time.perf_counter()
                _load_senders(store, idx, progress)
                _log.info("WA-idx: full-scan mittenti (%d) in %.1fs",
                          len(idx.senders), time.perf_counter() - t0)
        return idx
    except Exception:  # noqa: BLE001 — IndexedDB illeggibile → degrada a solo testo
        return None
    finally:
        if not keep_open and workdir is None:
            shutil.rmtree(tmp, ignore_errors=True)


def _load_senders(store, idx: WhatsAppIndex, progress: Optional[ProgressFn]) -> None:
    """Fallback: deserializza TUTTI i messaggi (lento) se la via scoped non è
    disponibile. Riempie `idx.senders` completo."""
    n = 0
    for rec in store.iterate_records():
        v = getattr(rec, "value", None)
        if not isinstance(v, dict):
            continue
        n += 1
        if (n & 0x0FFF) == 0:
            time.sleep(0)
            if progress is not None and (n & 0x3FFF) == 0:
                progress(n)
        rid = v.get("rowId")
        if not isinstance(rid, (int, float)):
            continue
        mid = v.get("id")
        from_me = isinstance(mid, str) and mid.startswith("true_")
        author = v.get("author")
        auth = author.get("_serialized") if isinstance(author, dict) else None
        idx.senders[int(rid)] = Sender(from_me, None if from_me else _as_str(auth))


def _load_group_subjects(store, idx: WhatsAppIndex) -> None:
    for rec in store.iterate_records():
        v = getattr(rec, "value", None)
        if not isinstance(v, dict):
            continue
        gid = _as_str(v.get("id"))
        subject = _as_str(v.get("subject"))
        if gid and subject:
            idx.group_subjects[gid] = subject


def _register_name(idx: WhatsAppIndex, jid: Optional[str], name: Optional[str]) -> None:
    if not jid or not name:
        return
    idx.name_by_jid.setdefault(jid, name)
    idx.name_by_jid.setdefault(_bare(jid), name)


def _load_contacts(store, idx: WhatsAppIndex) -> None:
    for rec in store.iterate_records():
        v = getattr(rec, "value", None)
        if not isinstance(v, dict):
            continue
        jid = _as_str(v.get("id"))
        if not jid:
            continue
        name = _as_str(v.get("name")) or _as_str(v.get("shortName")) \
            or _as_str(v.get("pushname"))
        phone = _as_str(v.get("phoneNumber"))
        if phone:
            idx.lid_to_phone[jid] = phone
        _register_name(idx, jid, name)
        if phone and name:
            _register_name(idx, phone, name)


def _load_out_contacts(store, idx: WhatsAppIndex) -> None:
    for rec in store.iterate_records():
        v = getattr(rec, "value", None)
        if not isinstance(v, dict):
            continue
        jid = _as_str(v.get("id"))
        name = _as_str(v.get("fullName")) or _as_str(v.get("firstName"))
        _register_name(idx, jid, name)
