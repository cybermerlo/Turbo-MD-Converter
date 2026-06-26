"""Utilità ffmpeg leggere: localizzazione del binario e rimozione traccia audio.

Il binario ffmpeg arriva da ``imageio-ffmpeg`` (un'unica dipendenza pip che
impacchetta l'eseguibile, niente installazione di sistema). Nel build cx_Freeze
il binario viene incluso accanto all'eseguibile in ``ffmpeg/ffmpeg.exe``.

La rimozione dell'audio è un **remux senza re-encoding** (``-c copy -an``):
velocissima e senza perdita di qualità video. Serve a NON inviare la traccia
audio a Gemini per la descrizione visiva (l'audio contamina la descrizione).
"""

import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from utils.system import no_window_kwargs as _no_window_kwargs

logger = logging.getLogger(__name__)


def get_ffmpeg_exe() -> str | None:
    """Ritorna il percorso dell'eseguibile ffmpeg, o None se non disponibile."""
    # 1. Override esplicito (onorato anche da imageio_ffmpeg).
    env = os.environ.get("IMAGEIO_FFMPEG_EXE")
    if env and Path(env).exists():
        return env
    # 2. Build freezato: binario impacchettato accanto all'eseguibile.
    if getattr(sys, "frozen", False):
        candidate = Path(sys.executable).parent / "ffmpeg" / "ffmpeg.exe"
        if candidate.exists():
            return str(candidate)
    # 3. Da sorgente: binario fornito da imageio-ffmpeg.
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:  # pacchetto assente o binario non scaricabile
        logger.warning("ffmpeg non disponibile: %s", e)
        return None


def strip_audio(src: Path, timeout_s: float = 120.0) -> Path | None:
    """Crea una copia di ``src`` SENZA traccia audio (remux, no re-encoding).

    Ritorna il Path del file temporaneo muto, oppure None se ffmpeg non è
    disponibile o l'operazione fallisce. Il chiamante è responsabile di
    eliminare il file temporaneo.
    """
    exe = get_ffmpeg_exe()
    if not exe:
        return None

    fd, tmp = tempfile.mkstemp(suffix=src.suffix or ".mp4", prefix="turbomd_noaudio_")
    os.close(fd)
    tmp_path = Path(tmp)

    cmd = [
        exe, "-y", "-loglevel", "error",
        "-i", str(src),
        "-map", "0:v",   # solo i flussi video
        "-c", "copy",    # nessuna ri-codifica
        "-an",           # niente audio
        str(tmp_path),
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            **_no_window_kwargs(),
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.warning("Rimozione audio fallita per '%s': %s", src.name, e)
        _safe_unlink(tmp_path)
        return None

    if proc.returncode != 0 or not tmp_path.exists() or tmp_path.stat().st_size == 0:
        logger.warning(
            "Rimozione audio fallita per '%s' (rc=%s): %s",
            src.name, proc.returncode, (proc.stderr or "").strip()[:300],
        )
        _safe_unlink(tmp_path)
        return None
    return tmp_path


def extract_audio_track(src: Path, timeout_s: float = 300.0) -> Path | None:
    """Estrae la sola traccia audio di ``src`` in un m4a 16 kHz mono.

    Per i video evita di caricare l'intero file alla trascrizione (il flusso
    video è inutile per lo speech-to-text) e 16 kHz mono è il formato ideale per
    lo STT. I timestamp restano allineati all'originale (nessun taglio), quindi
    gli spezzoni audio per l'identificazione interlocutori funzionano sul file di
    partenza. Ritorna il Path del temporaneo, o None se ffmpeg manca / non c'è
    audio decodificabile (il chiamante ripiega sul file originale).
    """
    exe = get_ffmpeg_exe()
    if not exe:
        return None

    fd, tmp = tempfile.mkstemp(suffix=".m4a", prefix="turbomd_audio_")
    os.close(fd)
    tmp_path = Path(tmp)

    cmd = [
        exe, "-y", "-loglevel", "error",
        "-i", str(src),
        "-vn",                       # scarta il video
        "-ac", "1", "-ar", "16000",  # mono 16 kHz (ottimale per STT)
        "-c:a", "aac", "-b:a", "64k",
        str(tmp_path),
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, encoding="utf-8", errors="replace",
            timeout=timeout_s, **_no_window_kwargs(),
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.warning("Estrazione traccia audio fallita per '%s': %s", src.name, e)
        _safe_unlink(tmp_path)
        return None
    if proc.returncode != 0 or not tmp_path.exists() or tmp_path.stat().st_size == 0:
        _safe_unlink(tmp_path)
        return None
    return tmp_path


def extract_audio_segment(
    src: Path, start: float, end: float, timeout_s: float = 60.0,
) -> Path | None:
    """Estrae l'audio nell'intervallo [start, end] di ``src`` in un wav temporaneo.

    Usato per far ascoltare all'utente uno spezzone e riconoscere lo speaker.
    Ritorna il Path del wav (mono) o None se ffmpeg non è disponibile/fallisce;
    il chiamante è responsabile di eliminarlo.
    """
    exe = get_ffmpeg_exe()
    if not exe:
        return None
    start = max(0.0, float(start or 0.0))
    duration = max(0.5, float(end or 0.0) - start)

    fd, tmp = tempfile.mkstemp(suffix=".wav", prefix="turbomd_snippet_")
    os.close(fd)
    tmp_path = Path(tmp)

    # -ss prima di -i = seek veloce; -t dopo -i = durata in output.
    cmd = [
        exe, "-y", "-loglevel", "error",
        "-ss", f"{start:.3f}",
        "-i", str(src),
        "-t", f"{duration:.3f}",
        "-vn",          # niente video
        "-ac", "1",     # mono
        str(tmp_path),
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, encoding="utf-8", errors="replace",
            timeout=timeout_s, **_no_window_kwargs(),
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.warning("Estrazione spezzone audio fallita: %s", e)
        _safe_unlink(tmp_path)
        return None
    if proc.returncode != 0 or not tmp_path.exists() or tmp_path.stat().st_size == 0:
        _safe_unlink(tmp_path)
        return None
    return tmp_path


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
