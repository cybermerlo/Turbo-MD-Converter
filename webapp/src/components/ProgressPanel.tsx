"use client";

import type { ProcessingPhase, CostTotals } from "@/lib/types";

interface ProgressPanelProps {
  phase: ProcessingPhase;
  ocrProgress: { current: number; total: number };
  extractionCount: number;
  costTotals: CostTotals | null;
}

export default function ProgressPanel({
  phase,
  ocrProgress,
  extractionCount,
  costTotals,
}: ProgressPanelProps) {
  const ocrPercent =
    ocrProgress.total > 0
      ? Math.round((ocrProgress.current / ocrProgress.total) * 100)
      : 0;

  return (
    <div className="bg-zinc-800/50 rounded-xl p-4 space-y-3">
      {/* OCR Progress */}
      <div>
        <div className="flex items-center justify-between text-sm mb-1">
          <span className="font-medium text-zinc-300">
            {phase === "idle"
              ? "OCR: In attesa..."
              : `OCR: Pagina ${ocrProgress.current}/${ocrProgress.total}`}
          </span>
          {ocrProgress.total > 0 && (
            <span className="text-zinc-500">{ocrPercent}%</span>
          )}
        </div>
        <div className="w-full bg-zinc-700 rounded-full h-2">
          <div
            className="bg-blue-500 h-2 rounded-full transition-all duration-300"
            style={{ width: `${ocrPercent}%` }}
          />
        </div>
      </div>

      {/* Extraction Progress */}
      <div>
        <div className="flex items-center justify-between text-sm mb-1">
          <span className="font-medium text-zinc-300">
            {phase === "extraction"
              ? "Estrazione in corso..."
              : phase === "complete" || phase === "formatting"
              ? `Estrazione completata: ${extractionCount} entita'`
              : "Estrazione: In attesa..."}
          </span>
        </div>
        <div className="w-full bg-zinc-700 rounded-full h-2">
          <div
            className={`h-2 rounded-full transition-all duration-300 ${
              phase === "extraction"
                ? "bg-amber-500 animate-pulse w-full"
                : phase === "complete" || phase === "formatting"
                ? "bg-green-500 w-full"
                : "bg-zinc-600 w-0"
            }`}
          />
        </div>
      </div>

      {/* Cost info */}
      {costTotals && (
        <div className="pt-2 border-t border-zinc-700">
          <div className="text-sm text-zinc-300">
            Costo: ${costTotals.total.costUsd.toFixed(4)} | Token:{" "}
            {(costTotals.total.inputTokens + costTotals.total.outputTokens).toLocaleString()}
          </div>
          <div className="text-xs text-zinc-500 mt-0.5">
            {costTotals.ocr.costUsd > 0 && (
              <span>OCR: ${costTotals.ocr.costUsd.toFixed(4)}</span>
            )}
            {costTotals.extraction.costUsd > 0 && (
              <span>
                {costTotals.ocr.costUsd > 0 ? " | " : ""}
                Estrazione: ~${costTotals.extraction.costUsd.toFixed(4)} (stimato)
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
