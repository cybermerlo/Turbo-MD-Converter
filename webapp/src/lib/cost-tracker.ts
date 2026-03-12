import { PRICING } from "./defaults";
import type { CostTotals } from "./types";

interface CallRecord {
  modelId: string;
  inputTokens: number;
  outputTokens: number;
  phase: "ocr" | "extraction";
}

export class CostTracker {
  private calls: CallRecord[] = [];

  addCall(
    modelId: string,
    inputTokens: number,
    outputTokens: number,
    phase: "ocr" | "extraction" = "ocr"
  ): void {
    this.calls.push({ modelId, inputTokens, outputTokens, phase });
  }

  getTotals(): CostTotals {
    const phases = ["ocr", "extraction"] as const;
    let totalIn = 0;
    let totalOut = 0;
    let totalCost = 0;

    const result: Record<string, { inputTokens: number; outputTokens: number; costUsd: number }> = {};

    for (const phase of phases) {
      const phaseCalls = this.calls.filter((c) => c.phase === phase);
      const inTokens = phaseCalls.reduce((s, c) => s + c.inputTokens, 0);
      const outTokens = phaseCalls.reduce((s, c) => s + c.outputTokens, 0);
      const cost = phaseCalls.reduce((s, c) => s + this.costForCall(c), 0);
      result[phase] = { inputTokens: inTokens, outputTokens: outTokens, costUsd: cost };
      totalIn += inTokens;
      totalOut += outTokens;
      totalCost += cost;
    }

    return {
      ocr: result.ocr,
      extraction: result.extraction,
      total: { inputTokens: totalIn, outputTokens: totalOut, costUsd: totalCost },
    };
  }

  getLastCallCost(): number {
    if (this.calls.length === 0) return 0;
    return this.costForCall(this.calls[this.calls.length - 1]);
  }

  getLastCallTokens(): [number, number] {
    if (this.calls.length === 0) return [0, 0];
    const last = this.calls[this.calls.length - 1];
    return [last.inputTokens, last.outputTokens];
  }

  reset(): void {
    this.calls = [];
  }

  getAllCalls(): CallRecord[] {
    return [...this.calls];
  }

  private costForCall(call: CallRecord): number {
    const pricing = PRICING[call.modelId];
    if (!pricing) return 0;
    const inputCost = (call.inputTokens / 1_000_000) * pricing.input_per_1m;
    const outputCost = (call.outputTokens / 1_000_000) * pricing.output_per_1m;
    return inputCost + outputCost;
  }
}
