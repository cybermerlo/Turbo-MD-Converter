import type { AppConfig } from "./types";

export const DEFAULT_OCR_PROMPT = `Sei un assistente OCR specializzato in documenti legali italiani.
Analizza questa immagine di una pagina di un documento legale e trascrivi TUTTO il testo visibile in modo preciso e completo.

Regole:
- Mantieni la formattazione originale (paragrafi, elenchi, rientri)
- Trascrivi numeri, date, codici e riferimenti normativi esattamente come appaiono
- Preserva maiuscole/minuscole, accenti e punteggiatura
- Se una parola e' illeggibile, indica [illeggibile]
- Non aggiungere interpretazioni o commenti
- Restituisci SOLO il testo trascritto`;

export const AVAILABLE_OCR_MODELS = [
  "gemini-3-flash-preview",
  "gemini-3.1-flash-lite-preview",
];

export const AVAILABLE_EXTRACTION_MODELS = [
  "gemini-2.5-flash",
  "gemini-2.5-pro",
];

export const PAGE_SEPARATOR = "\n\n--- Pagina {page_num} ---\n\n";

export const PRICING: Record<
  string,
  { input_per_1m: number; output_per_1m: number }
> = {
  "gemini-3-flash-preview": { input_per_1m: 0.5, output_per_1m: 3.0 },
  "gemini-3.1-flash-lite-preview": { input_per_1m: 0.25, output_per_1m: 1.5 },
  "gemini-2.5-flash": { input_per_1m: 0.15, output_per_1m: 0.6 },
  "gemini-2.5-pro": { input_per_1m: 1.25, output_per_1m: 10.0 },
};

export const SCHEMA_PRESET_NAMES = [
  "full_legal",
  "parties_dates",
  "invoice",
  "estratto_conto",
  "none",
  "custom",
];

export const DEFAULT_CONFIG: AppConfig = {
  geminiApiKey: "",
  ocrModelId: "gemini-3.1-flash-lite-preview",
  extractionModelId: "gemini-2.5-flash",
  ocrPrompt: DEFAULT_OCR_PROMPT,
  activeSchema: "full_legal",
  extractionPasses: 1,
  maxWorkers: 15,
  maxCharBuffer: 1000,
  pageDpi: 200,
  jpegQuality: 85,
  includeOcrTextInOutput: true,
  customSchemaPrompts: {},
};

const SETTINGS_KEY = "ocr-langextract-settings";

export function loadConfig(): AppConfig {
  if (typeof window === "undefined") return { ...DEFAULT_CONFIG };
  try {
    const stored = localStorage.getItem(SETTINGS_KEY);
    if (stored) {
      const parsed = JSON.parse(stored);
      return { ...DEFAULT_CONFIG, ...parsed };
    }
  } catch {
    // ignore
  }
  return { ...DEFAULT_CONFIG };
}

export function saveConfig(config: AppConfig): void {
  if (typeof window === "undefined") return;
  const toSave = { ...config };
  // Never persist API key to localStorage
  delete (toSave as Record<string, unknown>)["geminiApiKey"];
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(toSave));
}
