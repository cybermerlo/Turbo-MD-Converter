import { GoogleGenAI, HarmCategory, HarmBlockThreshold } from "@google/genai";
import type { Extraction, SchemaPreset, ExampleData } from "./types";

function buildExtractionPrompt(
  schema: SchemaPreset,
  text: string
): string {
  let prompt = schema.promptDescription + "\n\n";

  // Add examples if available
  if (schema.examples.length > 0) {
    prompt += "--- ESEMPI ---\n\n";
    for (const example of schema.examples) {
      prompt += `TESTO DI ESEMPIO:\n${example.text}\n\nESTRAZIONI ATTESE:\n`;
      prompt += JSON.stringify(example.extractions, null, 2);
      prompt += "\n\n";
    }
    prompt += "--- FINE ESEMPI ---\n\n";
  }

  prompt += `TESTO DA ANALIZZARE:\n${text}\n\n`;
  prompt += `Rispondi SOLO con un array JSON di oggetti con i campi:
- "extraction_class": la classe dell'entita'
- "extraction_text": il testo estratto dal documento
- "attributes": un oggetto con attributi aggiuntivi

Rispondi SOLO con l'array JSON, senza markdown o altro testo.`;

  return prompt;
}

function splitTextIntoChunks(text: string, maxChars: number): string[] {
  if (text.length <= maxChars) return [text];

  const chunks: string[] = [];
  let remaining = text;

  while (remaining.length > 0) {
    if (remaining.length <= maxChars) {
      chunks.push(remaining);
      break;
    }

    // Find a good split point (paragraph or sentence boundary)
    let splitAt = maxChars;
    const lastParagraph = remaining.lastIndexOf("\n\n", maxChars);
    if (lastParagraph > maxChars * 0.5) {
      splitAt = lastParagraph;
    } else {
      const lastSentence = remaining.lastIndexOf(". ", maxChars);
      if (lastSentence > maxChars * 0.5) {
        splitAt = lastSentence + 1;
      }
    }

    chunks.push(remaining.substring(0, splitAt));
    remaining = remaining.substring(splitAt).trim();
  }

  return chunks;
}

export async function extractStructured(
  apiKey: string,
  modelId: string,
  text: string,
  schema: SchemaPreset,
  maxCharBuffer: number = 1000,
  onProgress?: (message: string) => void
): Promise<{ extractions: Extraction[]; inputTokens: number; outputTokens: number }> {
  const ai = new GoogleGenAI({ apiKey });
  const allExtractions: Extraction[] = [];
  let totalInputTokens = 0;
  let totalOutputTokens = 0;

  // Split text into manageable chunks if needed
  // Use a generous chunk size for extraction (larger than OCR buffer)
  const effectiveChunkSize = Math.max(maxCharBuffer * 10, 8000);
  const chunks = splitTextIntoChunks(text, effectiveChunkSize);

  for (let i = 0; i < chunks.length; i++) {
    if (onProgress) {
      onProgress(
        chunks.length > 1
          ? `Estrazione chunk ${i + 1}/${chunks.length}...`
          : "Estrazione in corso..."
      );
    }

    const prompt = buildExtractionPrompt(schema, chunks[i]);

    try {
      const response = await ai.models.generateContent({
        model: modelId,
        contents: [{ role: "user", parts: [{ text: prompt }] }],
        config: {
          safetySettings: [
            { category: HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold: HarmBlockThreshold.BLOCK_NONE },
            { category: HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold: HarmBlockThreshold.BLOCK_NONE },
            { category: HarmCategory.HARM_CATEGORY_HARASSMENT, threshold: HarmBlockThreshold.BLOCK_NONE },
            { category: HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold: HarmBlockThreshold.BLOCK_NONE },
          ],
          responseMimeType: "application/json",
        },
      });

      totalInputTokens += response.usageMetadata?.promptTokenCount ?? 0;
      totalOutputTokens += response.usageMetadata?.candidatesTokenCount ?? 0;

      const responseText = response.text ?? "[]";

      // Parse the JSON response
      let parsed: Array<{
        extraction_class: string;
        extraction_text: string;
        attributes?: Record<string, string>;
      }>;

      try {
        parsed = JSON.parse(responseText);
        if (!Array.isArray(parsed)) {
          parsed = [parsed];
        }
      } catch {
        // Try to extract JSON from the response text
        const jsonMatch = responseText.match(/\[[\s\S]*\]/);
        if (jsonMatch) {
          parsed = JSON.parse(jsonMatch[0]);
        } else {
          console.warn("Could not parse extraction response:", responseText);
          parsed = [];
        }
      }

      for (const item of parsed) {
        allExtractions.push({
          extractionClass: item.extraction_class || "",
          extractionText: item.extraction_text || "",
          attributes: item.attributes || null,
        });
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      throw new Error(`Errore estrazione chunk ${i + 1}: ${msg}`);
    }
  }

  // Deduplicate
  const deduplicated = deduplicateExtractions(allExtractions);

  return {
    extractions: deduplicated,
    inputTokens: totalInputTokens,
    outputTokens: totalOutputTokens,
  };
}

function deduplicateExtractions(extractions: Extraction[]): Extraction[] {
  const seen = new Set<string>();
  const unique: Extraction[] = [];

  for (const ext of extractions) {
    const attrKey = ext.attributes
      ? JSON.stringify(Object.entries(ext.attributes).sort())
      : "";
    const key = `${ext.extractionClass}|${ext.extractionText.trim()}|${attrKey}`;

    if (!seen.has(key)) {
      seen.add(key);
      unique.push(ext);
    }
  }

  return unique;
}
