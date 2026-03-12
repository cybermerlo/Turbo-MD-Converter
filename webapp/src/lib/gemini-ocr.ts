import { GoogleGenAI, HarmCategory, HarmBlockThreshold } from "@google/genai";
import { DEFAULT_OCR_PROMPT } from "./defaults";

export class GeminiOCRError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "GeminiOCRError";
  }
}

interface OCRPageResponse {
  text: string;
  inputTokens: number;
  outputTokens: number;
}

export async function ocrPage(
  apiKey: string,
  modelId: string,
  imageBase64: string,
  pageNum: number,
  ocrPrompt: string = DEFAULT_OCR_PROMPT
): Promise<OCRPageResponse> {
  try {
    const ai = new GoogleGenAI({ apiKey });

    const response = await ai.models.generateContent({
      model: modelId,
      contents: [
        {
          role: "user",
          parts: [
            { text: ocrPrompt },
            {
              inlineData: {
                mimeType: "image/jpeg",
                data: imageBase64,
              },
            },
          ],
        },
      ],
      config: {
        safetySettings: [
          { category: HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold: HarmBlockThreshold.BLOCK_NONE },
          { category: HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold: HarmBlockThreshold.BLOCK_NONE },
          { category: HarmCategory.HARM_CATEGORY_HARASSMENT, threshold: HarmBlockThreshold.BLOCK_NONE },
          { category: HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold: HarmBlockThreshold.BLOCK_NONE },
        ],
      },
    });

    const text = response.text ?? "";
    const inputTokens = response.usageMetadata?.promptTokenCount ?? 0;
    const outputTokens = response.usageMetadata?.candidatesTokenCount ?? 0;

    return { text, inputTokens, outputTokens };
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    throw new GeminiOCRError(`OCR fallito per pagina ${pageNum + 1}: ${msg}`);
  }
}

export async function ocrPageWithRetry(
  apiKey: string,
  modelId: string,
  imageBase64: string,
  pageNum: number,
  ocrPrompt: string = DEFAULT_OCR_PROMPT,
  maxRetries: number = 3
): Promise<OCRPageResponse> {
  let lastError: Error | null = null;

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      return await ocrPage(apiKey, modelId, imageBase64, pageNum, ocrPrompt);
    } catch (e) {
      lastError = e instanceof Error ? e : new Error(String(e));
      if (attempt < maxRetries) {
        const delay = Math.min(2000 * Math.pow(2, attempt) + Math.random() * 1000, 30000);
        await new Promise((resolve) => setTimeout(resolve, delay));
      }
    }
  }

  throw lastError;
}
