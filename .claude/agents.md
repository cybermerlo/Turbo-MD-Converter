# Skills / Knowledge base (Claude) — Turbo‑MD‑Converter

Questi file in `.claude/` sono pensati come **skill di riferimento** per agenti (Claude o altri) quando si lavora su questo progetto.

## Indice

- `gemini-api.md`
  - API Gemini (GenAI SDK), **Interactions API** (beta), multimodale, streaming SSE, tool calling, MCP remoto, output strutturato (per modelli), modelli supportati e prezzi essenziali.
- `gemini-deep-research.md`
  - Skill specifica per **Gemini Deep Research**: pianificazione collaborativa, strumenti supportati, streaming con riconnessione, follow‑up, limitazioni e stime costo.

## Regole operative (importanti)

- **Non esporre queste API nella UI** finché non richiesto esplicitamente: qui stiamo solo raccogliendo documentazione e pattern.
- **Interactions è beta**: possibili breaking changes. Per produzione stabile, preferire `generateContent` finché l’Interactions non è stabilizzata.
- **Data retention** (Interactions, `store=true` di default):
  - **Paid**: 55 giorni
  - **Free**: 1 giorno
  - `store=false` **non** è compatibile con `background=true` e **impedisce** l’uso di `previous_interaction_id`.

