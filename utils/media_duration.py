"""Lettura della durata di un file video senza dipendenze native (no ffmpeg).

Legge solo i metadati del container per ricavare la durata in secondi:
- MP4 / MOV / M4V (ISO-BMFF): atom ``mvhd`` dentro ``moov``.
- MKV / WebM (Matroska/EBML): elemento ``Duration`` (× ``TimecodeScale``).

``probe_duration_seconds()`` ritorna la durata in secondi (float) oppure ``None``
se il formato non è supportato o i metadati non sono leggibili. Il chiamante
decide come comportarsi col valore ``None`` (es. procedere comunque con un tetto
sui token di output).
"""

import logging
import struct
from pathlib import Path

logger = logging.getLogger(__name__)

# Limite di sicurezza: non leggere più di questo per cercare gli header.
_MAX_SCAN_BYTES = 64 * 1024 * 1024  # 64 MB


def probe_duration_seconds(path: Path) -> float | None:
    """Ritorna la durata del video in secondi, o None se non determinabile."""
    suffix = path.suffix.lower()
    try:
        if suffix in (".mp4", ".mov", ".m4v"):
            return _mp4_duration(path)
        if suffix in (".mkv", ".webm"):
            return _ebml_duration(path)
    except Exception as e:  # parsing best-effort: mai propagare
        logger.debug("Durata non leggibile da '%s': %s", path.name, e)
    return None


# ---------------------------------------------------------------------------
# MP4 / MOV (ISO Base Media File Format)
# ---------------------------------------------------------------------------

def _mp4_duration(path: Path) -> float | None:
    """Cerca l'atom ``moov/mvhd`` e calcola duration / timescale."""
    with path.open("rb") as f:
        moov_range = _find_atom(f, b"moov", 0, _file_size(f))
        if moov_range is None:
            return None
        moov_start, moov_end = moov_range
        mvhd_range = _find_atom(f, b"mvhd", moov_start, moov_end)
        if mvhd_range is None:
            return None
        mvhd_start, _ = mvhd_range
        f.seek(mvhd_start)
        version = f.read(1)[0]
        f.read(3)  # flags
        if version == 1:
            f.read(8 + 8)  # creation + modification time (64 bit)
            timescale = struct.unpack(">I", f.read(4))[0]
            duration = struct.unpack(">Q", f.read(8))[0]
        else:
            f.read(4 + 4)  # creation + modification time (32 bit)
            timescale = struct.unpack(">I", f.read(4))[0]
            duration = struct.unpack(">I", f.read(4))[0]
        if not timescale:
            return None
        # duration == 0xFFFFFFFF segnala durata sconosciuta nel mvhd.
        if duration in (0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF):
            return None
        return duration / timescale


def _find_atom(f, target: bytes, start: int, end: int) -> tuple[int, int] | None:
    """Scansiona gli atom di primo livello in [start, end); ritorna (payload_start,
    payload_end) del primo atom di tipo ``target``. ``moov`` viene trattato come
    container da scandire ricorsivamente dal chiamante."""
    pos = start
    while pos + 8 <= end:
        f.seek(pos)
        header = f.read(8)
        if len(header) < 8:
            break
        size = struct.unpack(">I", header[:4])[0]
        atom_type = header[4:8]
        header_len = 8
        if size == 1:  # dimensione estesa a 64 bit
            ext = f.read(8)
            if len(ext) < 8:
                break
            size = struct.unpack(">Q", ext)[0]
            header_len = 16
        elif size == 0:  # l'atom arriva fino a fine file
            size = end - pos
        if size < header_len:
            break
        payload_start = pos + header_len
        payload_end = pos + size
        if atom_type == target:
            return payload_start, min(payload_end, end)
        pos = payload_end
    return None


def _file_size(f) -> int:
    cur = f.tell()
    f.seek(0, 2)
    size = f.tell()
    f.seek(cur)
    return min(size, _MAX_SCAN_BYTES)


# ---------------------------------------------------------------------------
# MKV / WebM (Matroska / EBML)
# ---------------------------------------------------------------------------

# ID EBML rilevanti (interi, byte completi incluso il marker di lunghezza).
_EBML_SEGMENT = 0x18538067
_EBML_INFO = 0x1549A966
_EBML_TIMECODE_SCALE = 0x2AD7B1
_EBML_DURATION = 0x4489
# TimecodeScale (uint) e Duration (float) sono scalari ≤ 8 byte: oltre questo è
# un file corrotto/malevolo e non va letto in memoria (un elem_size enorme
# causerebbe un read da gigabyte).
_EBML_MAX_SCALAR_BYTES = 8


def _ebml_duration(path: Path) -> float | None:
    """Estrae Duration (× TimecodeScale) dall'elemento Info del Segment."""
    with path.open("rb") as f:
        size = _file_size(f)
        seg = _ebml_find(f, _EBML_SEGMENT, 0, size)
        if seg is None:
            return None
        seg_start, seg_end = seg
        info = _ebml_find(f, _EBML_INFO, seg_start, seg_end)
        if info is None:
            return None
        info_start, info_end = info

        timecode_scale = 1_000_000  # default Matroska: 1 ms in nanosecondi
        duration_val: float | None = None

        pos = info_start
        while pos < info_end:
            f.seek(pos)
            elem_id, id_len = _read_vint(f, keep_marker=True)
            if elem_id is None:
                break
            elem_size, size_len = _read_vint(f, keep_marker=False)
            if elem_size is None:
                break
            data_start = pos + id_len + size_len
            # Legge solo i due scalari che ci servono, e solo se di dimensione
            # plausibile; gli altri elementi vengono saltati senza leggerli.
            if elem_id in (_EBML_TIMECODE_SCALE, _EBML_DURATION) and \
                    0 < elem_size <= _EBML_MAX_SCALAR_BYTES:
                f.seek(data_start)
                raw = f.read(elem_size)
                if elem_id == _EBML_TIMECODE_SCALE:
                    timecode_scale = int.from_bytes(raw, "big") or timecode_scale
                else:
                    duration_val = _read_ebml_float(raw)
            pos = data_start + elem_size

        if duration_val is None:
            return None
        return duration_val * timecode_scale / 1_000_000_000.0


def _ebml_find(f, target_id: int, start: int, end: int) -> tuple[int, int] | None:
    """Cerca un elemento EBML di id ``target_id`` tra i figli in [start, end)."""
    pos = start
    while pos < end:
        f.seek(pos)
        elem_id, id_len = _read_vint(f, keep_marker=True)
        if elem_id is None:
            break
        elem_size, size_len = _read_vint(f, keep_marker=False)
        if elem_size is None:
            break
        data_start = pos + id_len + size_len
        if elem_id == target_id:
            return data_start, min(data_start + elem_size, end)
        pos = data_start + elem_size
    return None


def _read_vint(f, *, keep_marker: bool) -> tuple[int | None, int]:
    """Legge un intero a lunghezza variabile EBML dalla posizione corrente.

    Con ``keep_marker=True`` (ID elemento) conserva il bit marcatore di lunghezza;
    con ``keep_marker=False`` (dimensioni) lo azzera per ottenere il valore reale.
    Ritorna (valore, numero_byte_letti); (None, 0) a fine dati.
    """
    first = f.read(1)
    if not first:
        return None, 0
    b0 = first[0]
    if b0 == 0:
        return None, 0
    length = 1
    mask = 0x80
    while not (b0 & mask):
        length += 1
        mask >>= 1
    rest = f.read(length - 1)
    if len(rest) < length - 1:
        return None, 0
    value = b0
    if not keep_marker:
        value = b0 & (mask - 1)  # azzera il bit marcatore
    for byte in rest:
        value = (value << 8) | byte
    return value, length


def _read_ebml_float(raw: bytes) -> float | None:
    """Decodifica un float EBML (4 o 8 byte big-endian IEEE-754)."""
    if len(raw) == 4:
        return struct.unpack(">f", raw)[0]
    if len(raw) == 8:
        return struct.unpack(">d", raw)[0]
    return None
