export interface AppConfig {
  geminiApiKey: string;
  ocrModelId: string;
  extractionModelId: string;
  ocrPrompt: string;
  activeSchema: string;
  extractionPasses: number;
  maxWorkers: number;
  maxCharBuffer: number;
  pageDpi: number;
  jpegQuality: number;
  includeOcrTextInOutput: boolean;
  customSchemaPrompts: Record<string, string>;
}

export interface Extraction {
  extractionClass: string;
  extractionText: string;
  attributes: Record<string, string> | null;
}

export interface ExampleExtraction {
  extraction_class: string;
  extraction_text: string;
  attributes: Record<string, string>;
}

export interface ExampleData {
  text: string;
  extractions: ExampleExtraction[];
}

export interface SchemaPreset {
  name: string;
  description: string;
  promptDescription: string;
  examples: ExampleData[];
}

export interface OCRPageResult {
  pageNum: number;
  text: string;
  success: boolean;
  error?: string;
  inputTokens: number;
  outputTokens: number;
}

export interface OCRResult {
  fileName: string;
  pageResults: OCRPageResult[];
  combinedText: string;
  totalPages: number;
  successfulPages: number;
}

export interface CostInfo {
  inputTokens: number;
  outputTokens: number;
  costUsd: number;
}

export interface CostTotals {
  ocr: CostInfo;
  extraction: CostInfo;
  total: CostInfo;
}

export type LogLevel = "INFO" | "WARNING" | "ERROR";

export interface LogEntry {
  timestamp: number;
  message: string;
  level: LogLevel;
}

export type ProcessingPhase =
  | "idle"
  | "ocr"
  | "extraction"
  | "formatting"
  | "complete"
  | "error"
  | "cancelled";
