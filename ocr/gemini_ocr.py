"""OCR via Gemini Flash vision API."""

import logging
import re

from google import genai
from google.genai import types

from config.defaults import DEFAULT_OCR_PROMPT, IMAGE_HANDLING_INSTRUCTION

logger = logging.getLogger(__name__)


class GeminiOCRError(Exception):
    """Raised when Gemini OCR fails (errore permanente: non va ritentato)."""
    pass


class GeminiOCRRetryableError(GeminiOCRError):
    """Errore OCR transitorio (429, 5xx, rete): vale la pena ritentare."""
    pass


def _is_non_retryable(exc: Exception) -> bool:
    """True per errori client permanenti (4xx, escluso 429 e affini).

    Ritentare un 401 (chiave non valida), un 400 (richiesta malformata) o un 404
    (modello inesistente) spreca solo chiamate e secondi di backoff — su un PDF di
    50 pagine con chiave errata sarebbero 200 tentativi inutili. I 429 e i 5xx
    restano ritentabili.
    """
    code = getattr(exc, "code", None)
    if not isinstance(code, int):
        code = getattr(exc, "status_code", None)
    if isinstance(code, int):
        return 400 <= code < 500 and code not in (408, 409, 425, 429)
    m = re.search(r"\b(\d{3})\b", str(exc))
    if m:
        c = int(m.group(1))
        return 400 <= c < 500 and c not in (408, 409, 425, 429)
    return False


class GeminiOCR:
    """Sends page images to Gemini for text extraction."""

    def __init__(self, api_key: str, model_id: str = "gemini-3-flash-preview",
                 ocr_prompt: str = DEFAULT_OCR_PROMPT):
        self.client = genai.Client(api_key=api_key)
        self.model_id = model_id
        self.ocr_prompt = ocr_prompt

    def ocr_page(self, image_bytes: bytes, page_num: int = 0,
                 mime_type: str = "image/jpeg") -> dict:
        """Send one page image to Gemini, return extracted text and token usage.

        Args:
            image_bytes: JPEG image bytes.
            page_num: Page number (for logging).

        Returns:
            {
                "text": str,
                "input_tokens": int,
                "output_tokens": int,
            }

        Raises:
            GeminiOCRError: If the API call fails.
        """
        try:
            # Configure safety settings to avoid blocking on sensitive financial documents
            safety_settings = [
                types.SafetySetting(category=cat, threshold="BLOCK_NONE")
                for cat in [
                    "HARM_CATEGORY_HATE_SPEECH",
                    "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                    "HARM_CATEGORY_HARASSMENT",
                    "HARM_CATEGORY_DANGEROUS_CONTENT",
                ]
            ]
            config = types.GenerateContentConfig(safety_settings=safety_settings)

            full_prompt = self.ocr_prompt + IMAGE_HANDLING_INSTRUCTION

            stream_response = self.client.models.generate_content_stream(
                model=self.model_id,
                contents=[
                    types.Part.from_text(text=full_prompt),
                    types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                ],
                config=config,
            )

            text_chunks = []
            input_tokens = 0
            output_tokens = 0

            for chunk in stream_response:
                if chunk.text:
                    text_chunks.append(chunk.text)
                
                if not chunk.text and hasattr(chunk, "candidates") and chunk.candidates:
                    candidate = chunk.candidates[0]
                    finish_reason = getattr(candidate, "finish_reason", "UNKNOWN")
                    # Log only if it stops unexpectedly
                    if finish_reason and str(finish_reason) not in ("UNKNOWN", "STOP", "FinishReason.STOP"):
                        logger.warning(
                            "Attenzione: Chunk della pagina %d ha restituito testo vuoto. Finish reason: %s. "
                            "Safety ratings: %s", 
                            page_num + 1, finish_reason, getattr(candidate, "safety_ratings", "N/A")
                        )

                if hasattr(chunk, "usage_metadata") and chunk.usage_metadata:
                    input_tokens = getattr(chunk.usage_metadata, "prompt_token_count", input_tokens) or input_tokens
                    output_tokens = getattr(chunk.usage_metadata, "candidates_token_count", output_tokens) or output_tokens

            text = "".join(text_chunks)

            logger.info(
                "Pagina %d OCR completata: %d caratteri, %d+%d tokens",
                page_num + 1, len(text), input_tokens, output_tokens,
            )
            return {
                "text": text,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            }

        except Exception as e:
            logger.error("Errore OCR pagina %d: %s", page_num + 1, e)
            err_cls = GeminiOCRError if _is_non_retryable(e) else GeminiOCRRetryableError
            raise err_cls(f"OCR fallito per pagina {page_num + 1}: {e}") from e
