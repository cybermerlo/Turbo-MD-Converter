"""Audio transcription via Mistral Voxtral Small (chat completions with audio input)."""

import base64
import logging
from pathlib import Path

from config.defaults import DEFAULT_TRANSCRIPTION_PROMPT
from utils.retry import retry_with_backoff

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
            text = response.choices[0].message.content or ""
            input_tokens = getattr(response.usage, "prompt_tokens", 0) or 0
            output_tokens = getattr(response.usage, "completion_tokens", 0) or 0
            return {
                "text": text,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            }

        def on_retry(attempt: int, exc: Exception):
            logger.warning(
                "Retry %d/3 trascrizione '%s': %s",
                attempt, audio_path.name, exc,
            )

        try:
            result = retry_with_backoff(
                func=do_transcribe,
                max_retries=3,
                base_delay=2.0,
                retryable_exceptions=(AudioTranscriberError, Exception),
                on_retry=on_retry,
            )
            logger.info(
                "Trascrizione completata: '%s' – %d caratteri, %d+%d token",
                audio_path.name, len(result["text"]),
                result["input_tokens"], result["output_tokens"],
            )
            return result

        except Exception as e:
            logger.error("Errore trascrizione '%s': %s", audio_path.name, e)
            raise AudioTranscriberError(
                f"Trascrizione fallita per '{audio_path.name}': {e}"
            ) from e
