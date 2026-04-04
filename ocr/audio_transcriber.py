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
    msg = str(exc).lower()
    return "429" in msg or "rate_limit" in msg or "rate limit" in msg


class AudioTranscriber:
    """Transcribes audio files using Mistral Voxtral Small via chat completions."""

    def __init__(
        self,
        api_key: str,
        model_id: str = "voxtral-small-latest",
        transcription_prompt: str = DEFAULT_TRANSCRIPTION_PROMPT,
    ):
        from mistralai.client import Mistral
        self.client = Mistral(api_key=api_key)
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
            try:
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
                )
            except Exception as api_exc:
                # 429 Rate Limit: non ha senso ritentare subito, rilancia
                # direttamente come AudioTranscriberError non-retryable
                if _is_rate_limit(api_exc):
                    raise AudioTranscriberError(
                        "Quota API Mistral esaurita (HTTP 429). "
                        "Verifica il tuo piano su console.mistral.ai → "
                        "aggiungi un metodo di pagamento per sbloccare l'accesso."
                    ) from api_exc
                raise

            text = response.choices[0].message.content or ""
            input_tokens = getattr(response.usage, "prompt_tokens", 0) or 0
            output_tokens = getattr(response.usage, "completion_tokens", 0) or 0
            return {
                "text": text,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            }

        last_exc: Exception | None = None
        for attempt in range(4):  # tentativo 0 + max 3 retry
            try:
                result = do_transcribe()
                logger.info(
                    "Trascrizione completata: '%s' – %d caratteri, %d+%d token",
                    audio_path.name, len(result["text"]),
                    result["input_tokens"], result["output_tokens"],
                )
                return result
            except AudioTranscriberError:
                # 429 e altri errori non recuperabili → fallisce subito
                raise
            except Exception as e:
                last_exc = e
                if attempt == 3:
                    break
                wait = min(2.0 * (2 ** attempt), 30.0)
                logger.warning(
                    "Retry %d/3 trascrizione '%s': %s",
                    attempt + 1, audio_path.name, e,
                )
                time.sleep(wait)

        logger.error("Errore trascrizione '%s': %s", audio_path.name, last_exc)
        raise AudioTranscriberError(
            f"Trascrizione fallita per '{audio_path.name}': {last_exc}"
        ) from last_exc
