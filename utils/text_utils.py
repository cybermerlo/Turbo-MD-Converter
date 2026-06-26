"""Piccole utility di manipolazione testo condivise."""

import re


def strip_json_fences(raw: str) -> str:
    """Rimuove eventuali fence Markdown (```json ... ```) attorno a un JSON.

    I modelli a volte avvolgono l'output JSON in un blocco di codice: questa
    funzione restituisce il payload pulito, pronto per ``json.loads``.
    """
    cleaned = re.sub(r"^```[a-z]*\s*", "", raw, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()
