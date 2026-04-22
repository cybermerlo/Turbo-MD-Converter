# Gemini Deep Research — Skill (aprile 2026)

Questa skill descrive **come usare l’agente Gemini Deep Research** tramite **Interactions API** (non tramite `generate_content`).

## Quando usarlo

Deep Research è un **agente** (workflow autonomo) adatto a ricerche multi‑step, due diligence, analisi competitive, revisioni di letteratura. È **asincrono** (minuti) e va eseguito in **background**.

## Versioni (agent id)

- **Deep Research**: `deep-research-preview-04-2026` (veloce/efficiente, adatto allo streaming UI)
- **Deep Research Max**: `deep-research-max-preview-04-2026` (massima completezza)

## Avvio + polling (pattern base)

```python
import time
from google import genai

client = genai.Client()

interaction = client.interactions.create(
    input="Research the history of Google TPUs.",
    agent="deep-research-preview-04-2026",
    background=True,
)

while True:
    result = client.interactions.get(interaction.id)
    if result.status == "completed":
        print(result.outputs[-1].text)
        break
    if result.status == "failed":
        raise RuntimeError(result.error)
    time.sleep(10)
```

## Pianificazione collaborativa (3 passaggi)

### 1) Richiedi un piano

Imposta `agent_config.collaborative_planning=True` per ottenere un **piano** invece del report.

```python
plan = client.interactions.create(
    agent="deep-research-preview-04-2026",
    input="Do some research on Google TPUs.",
    agent_config={
        "type": "deep-research",
        "thinking_summaries": "auto",
        "collaborative_planning": True,
    },
    background=True,
)
```

### 2) (Opzionale) Raffina il piano

Continua con `previous_interaction_id` e mantieni `collaborative_planning=True`.

```python
refined = client.interactions.create(
    agent="deep-research-preview-04-2026",
    input="Focus more on differences vs competitor hardware, less on history.",
    agent_config={
        "type": "deep-research",
        "thinking_summaries": "auto",
        "collaborative_planning": True,
    },
    previous_interaction_id=plan.id,
    background=True,
)
```

### 3) Approva ed esegui

Imposta `collaborative_planning=False` (o omettilo) e avvia la ricerca vera e propria.

```python
final_report = client.interactions.create(
    agent="deep-research-preview-04-2026",
    input="Plan looks good!",
    agent_config={
        "type": "deep-research",
        "thinking_summaries": "auto",
        "collaborative_planning": False,
    },
    previous_interaction_id=refined.id,
    background=True,
)
```

## Visualizzazione (grafici/diagrammi)

Abilita `agent_config.visualization="auto"` e **chiedi esplicitamente** immagini nel prompt (altrimenti potrebbe non generarne).

```python
interaction = client.interactions.create(
    agent="deep-research-preview-04-2026",
    input="Analyze global semiconductor market trends. Include graphics showing market share changes.",
    agent_config={"type": "deep-research", "visualization": "auto"},
    background=True,
)
```

Gli output includono `text` e, quando presenti, `image` (base64). In streaming arrivano come `content.delta` con `delta.type="image"`.

## Strumenti supportati

Per default (se non passi `tools`) l’agente può usare:

- `google_search`
- `url_context`
- `code_execution`

Puoi **limitare** o **estendere** passando `tools=[...]`:

- Solo search:
  - `tools=[{"type":"google_search"}]`
- Solo url context:
  - `tools=[{"type":"url_context"}]`
- Solo code execution:
  - `tools=[{"type":"code_execution"}]`
- **MCP remoto**:
  - `{"type":"mcp_server","name":"...","url":"...","headers":{...},"allowed_tools":[...]}`
- **File search**:
  - `{"type":"file_search","file_search_store_names":["fileSearchStores/<store>"]}`

## Streaming + riconnessione (timeout 600s)

Deep Research può durare più del timeout della connessione streaming. Pattern consigliato:

- avvia con `background=True, stream=True`
- salva `interaction_id` dall’evento `interaction.start`
- salva `last_event_id` da ogni chunk
- se cade la connessione: `client.interactions.get(id=interaction_id, stream=True, last_event_id=last_event_id)` finché `status == "in_progress"`

Per avere i passaggi intermedi, abilita `agent_config.thinking_summaries="auto"`.

## Follow‑up dopo il report (riuso contesto)

Dopo `completed`, puoi fare domande di approfondimento con `previous_interaction_id` (anche usando un **modello** Gemini standard per rifiniture/formattazione).

```python
follow = client.interactions.create(
    model="gemini-3.1-pro-preview",
    input="Puoi approfondire il punto 2 del report?",
    previous_interaction_id="COMPLETED_INTERACTION_ID",
)
```

## Costi stimati (stima doc, soggetta a cambi)

- **Deep Research** (`deep-research-preview-04-2026`):
  - ~80 query search, ~250k token input (50–70% cached), ~60k token output
  - **stimato**: 1–3 € / task
- **Deep Research Max** (`deep-research-max-preview-04-2026`):
  - ~160 query search, ~900k token input (50–70% cached), ~80k token output
  - **stimato**: 3–7 € / task

Nota pricing: Search Grounding addebita le **query** (e non addebita come token i contenuti recuperati), mentre `url_context`/`file_search` includono i token recuperati come input (oltre al costo embedding per l’indicizzazione nel caso `file_search`).

## Limitazioni / sicurezza

- **Solo Interactions API** (Deep Research non via `generate_content`).
- **Output strutturato**: non supportato dall’agente (aprile 2026).
- **Strumenti personalizzati (function calling)**: non disponibili direttamente; usare **MCP remoto** per tool esterni.
- **Tempo massimo**: 60 minuti (tipicamente < 20 min).
- **Requisito store**: `background=True` richiede `store=True`.
- **Prompt injection**: attenzione a file/PDF non fidati e a contenuti web malevoli; verificare citazioni/fonti.

