"""API cost tracking for Gemini calls."""

from dataclasses import dataclass, field
from config.defaults import PRICING


@dataclass
class CallRecord:
    """Record of a single API call."""
    model_id: str
    input_tokens: int
    output_tokens: int
    phase: str  # "ocr" or "extraction"


class CostTracker:
    """Accumulates token usage and computes costs across API calls."""

    def __init__(self):
        self._calls: list[CallRecord] = []

    def add_call(self, model_id: str, input_tokens: int, output_tokens: int,
                 phase: str = "ocr") -> None:
        """Record a single API call."""
        self._calls.append(CallRecord(
            model_id=model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            phase=phase,
        ))

    def get_totals(self) -> dict:
        """Get aggregated totals by phase.

        Returns:
            {
                "ocr": {"input_tokens": N, "output_tokens": N, "cost_usd": X},
                "extraction": {"input_tokens": N, "output_tokens": N, "cost_usd": X},
                "total": {"input_tokens": N, "output_tokens": N, "cost_usd": X},
            }
        """
        result = {}
        total_in = 0
        total_out = 0
        total_cost = 0.0

        for phase in ("ocr", "extraction", "transcription"):
            phase_calls = [c for c in self._calls if c.phase == phase]
            in_tokens = sum(c.input_tokens for c in phase_calls)
            out_tokens = sum(c.output_tokens for c in phase_calls)
            cost = self._compute_cost(phase_calls)
            result[phase] = {
                "input_tokens": in_tokens,
                "output_tokens": out_tokens,
                "cost_usd": cost,
            }
            total_in += in_tokens
            total_out += out_tokens
            total_cost += cost

        result["total"] = {
            "input_tokens": total_in,
            "output_tokens": total_out,
            "cost_usd": total_cost,
        }
        return result

    def get_last_call_cost(self) -> float:
        """Get cost of the most recent call."""
        if not self._calls:
            return 0.0
        call = self._calls[-1]
        return self._cost_for_call(call)

    def get_last_call_tokens(self) -> tuple[int, int]:
        """Get (input_tokens, output_tokens) for the most recent call."""
        if not self._calls:
            return 0, 0
        call = self._calls[-1]
        return call.input_tokens, call.output_tokens

    def reset(self) -> None:
        """Clear all recorded calls."""
        self._calls.clear()

    def _compute_cost(self, calls: list[CallRecord]) -> float:
        return sum(self._cost_for_call(c) for c in calls)

    def _cost_for_call(self, call: CallRecord) -> float:
        pricing = PRICING.get(call.model_id)
        if not pricing:
            return 0.0
        input_cost = (call.input_tokens / 1_000_000) * pricing["input_per_1m"]
        output_cost = (call.output_tokens / 1_000_000) * pricing["output_per_1m"]
        return input_cost + output_cost
