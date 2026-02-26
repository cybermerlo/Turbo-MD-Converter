"""OCR via Gemini Flash vision API."""

import logging

from google import genai
from google.genai import types

from config.defaults import DEFAULT_OCR_PROMPT

logger = logging.getLogger(__name__)


class GeminiOCRError(Exception):
    """Raised when Gemini OCR fails."""
    pass


class GeminiOCR:
    """Sends page images to Gemini for text extraction."""

    def __init__(self, api_key: str, model_id: str = "gemini-3-flash-preview",
                 ocr_prompt: str = DEFAULT_OCR_PROMPT):
        self.client = genai.Client(api_key=api_key)
        self.model_id = model_id
        self.ocr_prompt = ocr_prompt

    def ocr_page(self, image_bytes: bytes, page_num: int = 0) -> dict:
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
            response = self.client.models.generate_content(
                model=self.model_id,
                contents=[
                    types.Part.from_text(text=self.ocr_prompt),
                    types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                ],
            )

            text = response.text or ""

            # Extract token usage from response
            input_tokens = 0
            output_tokens = 0
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                input_tokens = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
                output_tokens = getattr(response.usage_metadata, "candidates_token_count", 0) or 0

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
            raise GeminiOCRError(f"OCR fallito per pagina {page_num + 1}: {e}") from e
