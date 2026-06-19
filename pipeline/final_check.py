"""Post-conversion quality check via a single LLM call on batch Markdown output."""

import json
import logging
import re
from dataclasses import dataclass, field

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)


@dataclass
class FinalCheckResult:
    passed: bool
    issues: list[dict] = field(default_factory=list)
    error_message: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    check_failed_technically: bool = False


def build_md_documents_block(md_documents: list[tuple[str, str]]) -> str:
    parts: list[str] = []
    for filename, content in md_documents:
        parts.append(f"--- FILE: {filename} ---")
        parts.append(content.strip())
        parts.append("")
    return "\n".join(parts).strip()


def run_final_error_check(
    md_documents: list[tuple[str, str]],
    api_key: str,
    model_id: str,
    prompt_template: str,
) -> FinalCheckResult:
    if not md_documents:
        return FinalCheckResult(
            passed=True,
            issues=[],
            error_message="",
        )

    if not (api_key or "").strip():
        return FinalCheckResult(
            passed=False,
            issues=[],
            error_message="Chiave API Gemini non configurata",
            check_failed_technically=True,
        )

    md_block = build_md_documents_block(md_documents)
    prompt = prompt_template.format(md_documents=md_block)

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model_id,
            contents=[types.Part.from_text(text=prompt)],
        )
        raw = (response.text or "").strip()
        if not raw:
            return FinalCheckResult(
                passed=False,
                issues=[],
                error_message="Risposta LLM vuota",
                check_failed_technically=True,
            )

        data = json.loads(_strip_json_fences(raw))
        passed = bool(data.get("passed", False))
        issues_raw = data.get("issues", [])
        issues: list[dict] = []
        if isinstance(issues_raw, list):
            for item in issues_raw:
                if not isinstance(item, dict):
                    continue
                issues.append({
                    "file": str(item.get("file", "")).strip(),
                    "type": str(item.get("type", "unknown")).strip(),
                    "description": str(item.get("description", "")).strip(),
                })

        input_tokens = 0
        output_tokens = 0
        usage = getattr(response, "usage_metadata", None)
        if usage:
            input_tokens = getattr(usage, "prompt_token_count", 0) or 0
            output_tokens = getattr(usage, "candidates_token_count", 0) or 0

        error_message = ""
        if not passed:
            if issues:
                summaries = [
                    f"{issue.get('type', 'issue')}: {issue.get('description', '')}"
                    for issue in issues[:3]
                ]
                error_message = "; ".join(s for s in summaries if s)
            else:
                error_message = "Check finale non superato"

        return FinalCheckResult(
            passed=passed,
            issues=issues,
            error_message=error_message,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
    except json.JSONDecodeError as e:
        logger.warning("Check finale: JSON non valido: %s", e)
        return FinalCheckResult(
            passed=False,
            issues=[],
            error_message=f"Risposta LLM non interpretabile: {e}",
            check_failed_technically=True,
        )
    except Exception as e:
        logger.error("Check finale errori fallito: %s", e)
        return FinalCheckResult(
            passed=False,
            issues=[],
            error_message=str(e),
            check_failed_technically=True,
        )


def _strip_json_fences(raw: str) -> str:
    cleaned = re.sub(r"^```[a-z]*\s*", "", raw, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()
