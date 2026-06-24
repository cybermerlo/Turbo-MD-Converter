"""Descrizione visiva di un video via Gemini (Files API).

Si occupa SOLO del "cosa si vede": l'audio del video è trascritto separatamente da
Voxtral. IMPORTANTE: la traccia audio viene **rimossa** prima dell'upload (remux
senza re-encoding), perché altrimenti contamina la descrizione visiva (il modello
"sente" un cane e lo descrive a schermo anche se non è inquadrato).

La risoluzione (qualità frame) è scelta in base alla durata: video brevi → HIGH,
video lunghi → LOW (per contenere i token). Il costo è riportato tramite
``usage_metadata`` reale (non stimato).
"""

import logging
import os
import time
from pathlib import Path

from google import genai
from google.genai import types

from config.defaults import DEFAULT_VIDEO_DESCRIPTION_PROMPT
from utils.ffmpeg_tools import strip_audio

logger = logging.getLogger(__name__)

_LOW = types.MediaResolution.MEDIA_RESOLUTION_LOW
_HIGH = types.MediaResolution.MEDIA_RESOLUTION_HIGH

# Forzatura "al volo" della risoluzione (scavalca la scelta automatica per durata),
# utile per test/confronti qualità:
#   TURBOMD_VIDEO_MEDIA_RESOLUTION = low | medium | high
#   TURBOMD_VIDEO_MAX_OUTPUT_TOKENS = <intero>
_RESOLUTION_MAP = {
    "low": _LOW,
    "medium": types.MediaResolution.MEDIA_RESOLUTION_MEDIUM,
    "high": _HIGH,
}


def _resolution_name(res) -> str:
    """Etichetta leggibile ("LOW"/"MEDIUM"/"HIGH") da un valore MediaResolution."""
    return res.name.replace("MEDIA_RESOLUTION_", "")


class VideoDescriberError(Exception):
    """Raised when the visual description of a video fails."""
    pass


class VideoDescriber:
    """Genera una descrizione visiva di un video tramite Gemini."""

    def __init__(
        self,
        api_key: str,
        model_id: str = "gemini-3.1-flash-lite",
        prompt: str = DEFAULT_VIDEO_DESCRIPTION_PROMPT,
        max_output_tokens: int = 2048,
        high_quality_max_min: int = 3,
    ):
        self.client = genai.Client(api_key=api_key)
        self.model_id = model_id
        self.prompt = prompt
        # Soglia durata per la qualità automatica: video ≤ soglia → HIGH, oltre → LOW.
        self.high_quality_max_min = high_quality_max_min
        # Forzatura via env (scavalca la scelta per durata); None se non impostata.
        raw_res = os.environ.get("TURBOMD_VIDEO_MEDIA_RESOLUTION", "").strip().lower()
        self.forced_resolution = _RESOLUTION_MAP.get(raw_res)
        # Tetto sui token di output: default dal chiamante, sovrascrivibile via env.
        env_max = os.environ.get("TURBOMD_VIDEO_MAX_OUTPUT_TOKENS", "").strip()
        if env_max.isdigit() and int(env_max) > 0:
            max_output_tokens = int(env_max)
        self.max_output_tokens = max_output_tokens

    def resolution_for(self, duration_s: float | None):
        """Sceglie (enum, nome) della risoluzione per un video di data durata.

        Precedenza: forzatura via env > durata (breve→HIGH, lungo/ignota→LOW).
        """
        if self.forced_resolution is not None:
            res = self.forced_resolution
        elif duration_s is not None and duration_s <= self.high_quality_max_min * 60:
            res = _HIGH
        else:
            res = _LOW
        return res, _resolution_name(res)

    def describe(self, video_path: Path, media_resolution=None) -> dict:
        """Descrive il contenuto visivo del video (audio rimosso) e ritorna il testo.

        Args:
            video_path: percorso del video sorgente.
            media_resolution: risoluzione frame; se None usa LOW.

        Returns:
            {"text": str, "input_tokens": int, "output_tokens": int}

        Raises:
            VideoDescriberError: se la rimozione audio, l'upload o la generazione
                falliscono.
        """
        resolution = media_resolution or _LOW
        logger.info(
            "Avvio descrizione visiva: '%s' (modello=%s, risoluzione=%s, max_out=%d)",
            video_path.name, self.model_id,
            _resolution_name(resolution), self.max_output_tokens,
        )

        # Rimuovi la traccia audio: altrimenti contamina la descrizione visiva.
        muted_path = strip_audio(video_path)
        if muted_path is None:
            raise VideoDescriberError(
                f"Impossibile rimuovere l'audio da '{video_path.name}' "
                f"(ffmpeg non disponibile): descrizione visiva saltata per evitare "
                f"che l'audio contamini la descrizione"
            )

        uploaded = None
        try:
            uploaded = self.client.files.upload(file=muted_path)
            uploaded = self._wait_until_active(uploaded)

            safety_settings = [
                types.SafetySetting(category=cat, threshold="BLOCK_NONE")
                for cat in (
                    "HARM_CATEGORY_HATE_SPEECH",
                    "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                    "HARM_CATEGORY_HARASSMENT",
                    "HARM_CATEGORY_DANGEROUS_CONTENT",
                )
            ]
            config = types.GenerateContentConfig(
                media_resolution=resolution,
                max_output_tokens=self.max_output_tokens,
                safety_settings=safety_settings,
            )

            response = self.client.models.generate_content(
                model=self.model_id,
                contents=[uploaded, types.Part.from_text(text=self.prompt)],
                config=config,
            )

            text = (getattr(response, "text", None) or "").strip()
            usage = getattr(response, "usage_metadata", None)
            input_tokens = getattr(usage, "prompt_token_count", 0) or 0
            output_tokens = getattr(usage, "candidates_token_count", 0) or 0

            logger.info(
                "Descrizione visiva completata: '%s' – %d caratteri, %d+%d token",
                video_path.name, len(text), input_tokens, output_tokens,
            )
            return {
                "text": text,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            }
        except VideoDescriberError:
            raise
        except Exception as e:
            logger.error("Errore descrizione visiva '%s': %s", video_path.name, e)
            raise VideoDescriberError(
                f"Descrizione visiva fallita per '{video_path.name}': {e}"
            ) from e
        finally:
            if uploaded is not None:
                self._safe_delete(uploaded)
            try:
                muted_path.unlink(missing_ok=True)
            except OSError:
                pass

    def _wait_until_active(self, uploaded, timeout_s: float = 300.0):
        """Attende che il file caricato passi da PROCESSING ad ACTIVE."""
        deadline_steps = int(timeout_s / 2.0)
        for _ in range(max(1, deadline_steps)):
            state_name = self._state_name(uploaded)
            if "ACTIVE" in state_name:
                return uploaded
            if "FAILED" in state_name:
                raise VideoDescriberError(
                    f"Elaborazione del video fallita lato Gemini (stato {state_name})"
                )
            time.sleep(2.0)
            uploaded = self.client.files.get(name=uploaded.name)
        raise VideoDescriberError("Timeout nell'elaborazione del video (Files API)")

    @staticmethod
    def _state_name(uploaded) -> str:
        state = getattr(uploaded, "state", None)
        return (getattr(state, "name", None) or str(state) or "").upper()

    def _safe_delete(self, uploaded) -> None:
        try:
            self.client.files.delete(name=uploaded.name)
        except Exception as e:  # cleanup best-effort
            logger.debug("Impossibile eliminare il file remoto '%s': %s",
                         getattr(uploaded, "name", "?"), e)
