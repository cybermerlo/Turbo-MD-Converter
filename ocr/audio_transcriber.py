"""Audio transcription via ElevenLabs Scribe v2 (batch Speech-to-Text)."""

import logging
import re
import time
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_STT_MODEL = "scribe_v2"

# Estensioni audio/video supportate (usate per il routing e la validazione).
# ElevenLabs rileva da sé il content-type; la mappa resta per coerenza e test.
AUDIO_MIME_TYPES: dict[str, str] = {
    ".mp3":  "audio/mpeg",
    ".wav":  "audio/wav",
    ".flac": "audio/flac",
    ".m4a":  "audio/mp4",
    ".ogg":  "audio/ogg",
    ".mp4":  "audio/mp4",
    # Le note vocali (.opus) sono Opus in container Ogg.
    ".opus": "audio/ogg",
}


class AudioTranscriberError(Exception):
    """Raised when audio transcription fails."""
    pass


class AudioNotDecodableError(AudioTranscriberError):
    """Il file non contiene audio decodificabile (es. video muto).

    Condizione attesa e benigna: va trattata come skip, non come errore.
    """
    pass


def _format_timestamp(seconds: float) -> str:
    """Formatta secondi in mm:ss (o hh:mm:ss)."""
    total = max(0, int(seconds or 0))
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def segments_from_words(words) -> list[dict]:
    """Raggruppa le parole consecutive per speaker in turni di conversazione.

    ElevenLabs restituisce una lista di "words" con `text/start/end/type/speaker_id`
    (type ∈ word|spacing|audio_event). Le spaziature si attaccano al turno corrente;
    un cambio di `speaker_id` apre un nuovo turno.
    Ritorna [{"speaker_id", "start", "end", "text"}].
    """
    segments: list[dict] = []
    cur: dict | None = None
    for w in words or []:
        wtype = getattr(w, "type", "word") or "word"
        text = getattr(w, "text", "") or ""
        if wtype == "spacing":
            if cur is not None:
                cur["text"] += text
            continue
        sid = getattr(w, "speaker_id", None) or "speaker_0"
        start = getattr(w, "start", None)
        end = getattr(w, "end", None)
        if cur is None or sid != cur["speaker_id"]:
            if cur is not None:
                segments.append(cur)
            cur = {"speaker_id": sid, "start": start, "end": end, "text": text}
        else:
            cur["text"] += text
            if end is not None:
                cur["end"] = end
    if cur is not None:
        segments.append(cur)
    out = []
    for s in segments:
        s["text"] = s["text"].strip()
        if s["text"]:
            out.append(s)
    return out


def distinct_speakers(segments: list[dict]) -> list[str]:
    """Speaker distinti nell'ordine di prima comparsa."""
    seen: list[str] = []
    for s in segments:
        if s["speaker_id"] not in seen:
            seen.append(s["speaker_id"])
    return seen


def build_transcript(segments: list[dict],
                     speaker_labels: dict[str, str] | None = None) -> str:
    """Compone il testo finale dai segmenti.

    - Un solo speaker → testo piano (senza etichette/timestamp, più leggibile per
      le note vocali).
    - Più speaker → una riga `[mm:ss] <etichetta>: testo` per turno, applicando
      eventuali etichette utente (speaker_0 → "Mario").
    """
    speaker_labels = speaker_labels or {}
    speakers = distinct_speakers(segments)
    if len(speakers) <= 1:
        return " ".join(s["text"] for s in segments).strip()
    lines = []
    for s in segments:
        label = speaker_labels.get(s["speaker_id"], s["speaker_id"])
        ts = _format_timestamp(s["start"] or 0)
        lines.append(f"[{ts}] {label}: {s['text']}")
    return "\n".join(lines)


def _status_code(exc: Exception) -> int | None:
    code = getattr(exc, "status_code", None)
    if isinstance(code, int):
        return code
    m = re.search(r"\b(\d{3})\b", str(exc))
    return int(m.group(1)) if m else None


def _is_rate_limit(exc: Exception) -> bool:
    """True per un 429 (rate limit)."""
    if _status_code(exc) == 429:
        return True
    msg = str(exc).lower()
    return "rate limit" in msg or "rate_limit" in msg


def _is_non_retryable(exc: Exception) -> bool:
    """True per errori client permanenti (4xx, escluso 429 e affini).

    Ritentare un 401 (chiave non valida) o un 400 (file non valido) è inutile.
    """
    code = _status_code(exc)
    if code is not None:
        return 400 <= code < 500 and code not in (408, 409, 425, 429)
    return False


def _is_undecodable_audio(exc: Exception | None) -> bool:
    """True quando l'API rifiuta il file perché privo di audio decodificabile.

    Tipico dei video senza traccia audio (es. GIF salvate come .mp4). Copre sia i
    messaggi ElevenLabs sia, per retro-compatibilità, quelli storici di Mistral.
    """
    if exc is None:
        return False
    if str(getattr(exc, "code", "")) == "3310":
        return True
    msg = str(exc).lower()
    return (
        "could not be decoded" in msg
        or "invalid_request_file" in msg
        or '"code":"3310"' in msg
        or "no audio" in msg
        or "could not detect any audio" in msg
        or "no speech" in msg
    )


def _retry_after_seconds(exc: Exception) -> float | None:
    """Estrae l'header Retry-After dall'errore, se presente."""
    headers = getattr(exc, "headers", None)
    if not headers:
        body = getattr(exc, "body", None)
        headers = getattr(body, "headers", None)
    if not headers:
        return None
    try:
        raw = headers.get("retry-after") or headers.get("Retry-After")
    except AttributeError:
        return None
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return None


class AudioTranscriber:
    """Transcribes audio/video files using ElevenLabs Scribe v2 (batch STT)."""

    def __init__(self, api_key: str, model_id: str = DEFAULT_STT_MODEL):
        from elevenlabs.client import ElevenLabs

        self.client = ElevenLabs(api_key=api_key)
        self.model_id = model_id

    def transcribe(self, audio_path: Path) -> dict:
        """Transcribe an audio or video file via ElevenLabs Scribe v2.

        Returns:
            {
                "text": str,                # trascrizione (piana o diarizzata)
                "duration_seconds": float,  # durata audio (per il costo)
                "language_code": str,
                "speakers": list[str],      # speaker distinti (per la diarization)
                "segments": list[dict],     # [{"speaker_id","start","end","text"}]
            }

        Raises:
            AudioTranscriberError / AudioNotDecodableError: in caso di errore.
        """
        suffix = audio_path.suffix.lower()
        if suffix not in AUDIO_MIME_TYPES:
            raise AudioTranscriberError(
                f"Formato non supportato: '{suffix}'. "
                f"Formati supportati: {', '.join(AUDIO_MIME_TYPES)}"
            )

        logger.info(
            "Avvio trascrizione: '%s' (modello=%s)",
            audio_path.name, self.model_id,
        )

        def do_transcribe():
            # Riapre il file a ogni tentativo (niente intero blob in RAM,
            # compatibile col retry per i 429/5xx).
            with audio_path.open("rb") as audio_file:
                response = self.client.speech_to_text.convert(
                    file=audio_file,
                    model_id=self.model_id,
                    diarize=True,           # annota chi parla
                    tag_audio_events=True,  # tagga risate/applausi ecc.
                    # language_code omesso → rilevamento automatico
                )

            words = getattr(response, "words", None) or []
            segments = segments_from_words(words)
            speakers = distinct_speakers(segments)
            text = build_transcript(segments)
            if not text:
                text = (getattr(response, "text", "") or "").strip()
            duration = float(getattr(response, "audio_duration_secs", 0.0) or 0.0)
            return {
                "text": text,
                "duration_seconds": duration,
                "language_code": getattr(response, "language_code", "") or "",
                "speakers": speakers,
                "segments": segments,
            }

        last_exc: Exception | None = None
        max_attempts = 6
        for attempt in range(max_attempts):
            try:
                result = do_transcribe()
                logger.info(
                    "Trascrizione completata: '%s' – %d caratteri, %.1fs audio, "
                    "%d speaker",
                    audio_path.name, len(result["text"]),
                    result["duration_seconds"], len(result["speakers"]),
                )
                return result
            except AudioTranscriberError:
                raise
            except Exception as e:
                last_exc = e
                if _is_non_retryable(e):
                    logger.warning(
                        "Trascrizione '%s' non ritentabile (errore client): %s",
                        audio_path.name, e,
                    )
                    break
                if attempt == max_attempts - 1:
                    break
                ra = _retry_after_seconds(e)
                if _is_rate_limit(e):
                    wait = ra if ra is not None else min(90.0, 10.0 * (1.6**attempt))
                else:
                    wait = ra if ra is not None else min(30.0, 2.0 * (2**attempt))
                logger.warning(
                    "Retry %d/%d trascrizione '%s' (attesa %.1fs): %s",
                    attempt + 1, max_attempts - 1, audio_path.name, wait, e,
                )
                time.sleep(wait)

        if _is_undecodable_audio(last_exc):
            logger.info(
                "Nessun audio decodificabile in '%s' (probabile video muto): %s",
                audio_path.name, last_exc,
            )
            raise AudioNotDecodableError(
                f"Nessuna traccia audio decodificabile in '{audio_path.name}' "
                f"(probabile video senza audio)"
            ) from last_exc

        logger.error("Errore trascrizione '%s': %s", audio_path.name, last_exc)
        raise AudioTranscriberError(
            f"Trascrizione fallita per '{audio_path.name}': {last_exc}"
        ) from last_exc
