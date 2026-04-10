"""Audio transcription via Mistral Voxtral Small (chat completions with audio input)."""

import base64
import logging
import time
from pathlib import Path

from config.defaults import DEFAULT_TRANSCRIPTION_PROMPT

logger = logging.getLogger(__name__)

# Supported audio MIME types by extension
AUDIO_MIME_TYPES: dict[str, str] = {
    ".mp3":  "audio/mpeg",
    ".wav":  "audio/wav",
    ".flac": "audio/flac",
    ".m4a":  "audio/mp4",
    ".ogg":  "audio/ogg",
}


class AudioTranscriberError(Exception):
    """Raised when audio transcription fails."""
    pass


def _is_rate_limit(exc: Exception) -> bool:
    """Return True if the exception is an HTTP 429 rate-limit response."""
    if getattr(exc, "status_code", None) == 429:
        return True
    msg = str(exc).lower()
    return "429" in msg or "rate_limit" in msg or "rate limit" in msg


def _retry_after_seconds(exc: Exception) -> float | None:
    """Retry-After dall'errore Mistral (SDKError espone .headers)."""
    headers = getattr(exc, "headers", None)
    if headers is None:
        return None
    raw = headers.get("retry-after") or headers.get("Retry-After")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return None


class AudioTranscriber:
    """Transcribes audio files using Mistral Voxtral Small via chat completions."""

    def __init__(
        self,
        api_key: str,
        model_id: str = "voxtral-small-latest",
        transcription_prompt: str = DEFAULT_TRANSCRIPTION_PROMPT,
    ):
        from mistralai.client import Mistral
        from mistralai.client.utils import BackoffStrategy, RetryConfig

        # Senza retry_config l'SDK non ritenta i 429: una sola richiesta e stop.
        backoff = BackoffStrategy(
            initial_interval=1_000,
            max_interval=120_000,
            exponent=1.5,
            max_elapsed_time=600_000,
        )
        sdk_retry = RetryConfig(
            strategy="backoff",
            backoff=backoff,
            retry_connection_errors=True,
        )
        self.client = Mistral(api_key=api_key, retry_config=sdk_retry)
        self.model_id = model_id
        self.transcription_prompt = transcription_prompt

    def transcribe(self, audio_path: Path) -> dict:
        """Transcribe an audio file via Voxtral Small.

        Args:
            audio_path: Path to the audio file (MP3, WAV, FLAC, M4A, OGG).

        Returns:
            {
                "text": str,
                "input_tokens": int,
                "output_tokens": int,
            }

        Raises:
            AudioTranscriberError: If the API call fails or the file is unsupported.
        """
        suffix = audio_path.suffix.lower()
        if suffix not in AUDIO_MIME_TYPES:
            raise AudioTranscriberError(
                f"Formato audio non supportato: '{suffix}'. "
                f"Formati supportati: {', '.join(AUDIO_MIME_TYPES)}"
            )

        logger.info(
            "Avvio trascrizione audio: '%s' (modello=%s)",
            audio_path.name, self.model_id,
        )

        audio_bytes = audio_path.read_bytes()
        audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")

        def do_transcribe():
            # Audio lunghi: il default SDK è 30s e può interrompere la richiesta.
            response = self.client.chat.complete(
                model=self.model_id,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "input_audio",
                            "input_audio": audio_base64,
                        },
                        {
                            "type": "text",
                            "text": self.transcription_prompt,
                        },
                    ],
                }],
                timeout_ms=600_000,
            )

            text = response.choices[0].message.content or ""
            input_tokens = getattr(response.usage, "prompt_tokens", 0) or 0
            output_tokens = getattr(response.usage, "completion_tokens", 0) or 0
            return {
                "text": text,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            }

        last_exc: Exception | None = None
        max_attempts = 6
        for attempt in range(max_attempts):
            try:
                result = do_transcribe()
                logger.info(
                    "Trascrizione completata: '%s' – %d caratteri, %d+%d token",
                    audio_path.name, len(result["text"]),
                    result["input_tokens"], result["output_tokens"],
                )
                return result
            except AudioTranscriberError:
                raise
            except Exception as e:
                last_exc = e
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

        logger.error("Errore trascrizione '%s': %s", audio_path.name, last_exc)
        raise AudioTranscriberError(
            f"Trascrizione fallita per '{audio_path.name}': {last_exc}"
        ) from last_exc
