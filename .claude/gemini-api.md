# Gemini API — Riferimento completo (aprile 2026)

## SDK e client

```python
from google import genai
client = genai.Client()  # legge GEMINI_API_KEY dall'env
```

```javascript
import { GoogleGenAI } from '@google/genai';
const client = new GoogleGenAI({});
```

---

## Interactions API (beta) — endpoint unificato

**Endpoint:** `POST https://generativelanguage.googleapis.com/v1beta/interactions`

L'Interactions API è l'alternativa migliorata a `generate_content`. Gestisce stato, orchestrazione strumenti e attività lunghe. Gli oggetti interaction vengono salvati lato server per default (`store=true`).

### Chiamata base

```python
interaction = client.interactions.create(
    model="gemini-3-flash-preview",
    input="Testo del prompt"
)
print(interaction.outputs[-1].text)
```

### Conversazione stateful (storia server-side)

```python
# Turno 1
i1 = client.interactions.create(model="gemini-3-flash-preview", input="Mi chiamo Marco.")
# Turno 2 — passa solo il nuovo input
i2 = client.interactions.create(
    model="gemini-3-flash-preview",
    input="Come mi chiamo?",
    previous_interaction_id=i1.id
)
```

### Recuperare un'interazione passata

```python
interaction = client.interactions.get("<ID>")
interaction = client.interactions.get("<ID>", include_input=True)  # include anche l'input originale
```

### Conversazione stateless (storia lato client)

```python
history = [{"role": "user", "content": "Domanda 1"}]
i1 = client.interactions.create(model="gemini-3-flash-preview", input=history)
history.append({"role": "model", "content": i1.outputs})
history.append({"role": "user", "content": "Domanda 2"})
i2 = client.interactions.create(model="gemini-3-flash-preview", input=history)
```

---

## Input multimodali

`input` può essere stringa oppure lista di oggetti contenuto:

```python
# Immagine
input=[
    {"type": "text", "text": "Descrivi questa immagine."},
    {"type": "image", "uri": "https://...", "mime_type": "image/jpeg"}
]

# Audio
input=[
    {"type": "text", "text": "Cosa dice questo audio?"},
    {"type": "audio", "uri": "https://...", "mime_type": "audio/wav"}
]

# Video
input=[
    {"type": "text", "text": "Cosa succede in questo video?"},
    {"type": "video", "uri": "https://...", "mime_type": "video/mp4"}
]

# Documento PDF
input=[
    {"type": "text", "text": "Di cosa parla questo documento?"},
    {"type": "document", "uri": "https://...", "mime_type": "application/pdf"}
]
```

---

## Streaming

Richiede `background=True` e `stream=True`. Il flusso può interrompersi (timeout 600s) — riconnettersi con `last_event_id`.

```python
interaction_id = None
last_event_id = None
is_complete = False

def process_stream(stream):
    global interaction_id, last_event_id, is_complete
    for chunk in stream:
        if chunk.event_type == "interaction.start":
            interaction_id = chunk.interaction.id
        if chunk.event_id:
            last_event_id = chunk.event_id
        if chunk.event_type == "content.delta":
            if chunk.delta.type == "text":
                print(chunk.delta.text, end="", flush=True)
            elif chunk.delta.type == "thought_summary":
                print(f"[Pensiero] {chunk.delta.content.text}")
        elif chunk.event_type in ("interaction.complete", "error"):
            is_complete = True

stream = client.interactions.create(
    input="...", model="gemini-3-flash-preview",
    background=True, stream=True,
    agent_config={"type": "deep-research", "thinking_summaries": "auto"}
)
process_stream(stream)

# Riconnessione se il flusso si interrompe
while not is_complete and interaction_id:
    status = client.interactions.get(interaction_id)
    if status.status != "in_progress": break
    stream = client.interactions.get(id=interaction_id, stream=True, last_event_id=last_event_id)
    process_stream(stream)
```

**Tipi di eventi stream:**
| event_type | delta.type | Contenuto |
|---|---|---|
| `content.delta` | `text` | Testo finale |
| `content.delta` | `thought_summary` | Ragionamento intermedio |
| `content.delta` | `image` | Immagine base64 generata |
| `interaction.complete` | — | Fine task |
| `error` | — | Errore |

**Nota importante (Interactions Streaming SSE):** quando `stream=true`, l’evento finale `interaction.complete` **non** contiene `outputs`. Devi ricostruire testo/tool‑args accumulando i `content.delta` (e usando `content.start/stop` e `index` quando presenti).

---

## Function calling

```python
weather_tool = {
    "type": "function",
    "name": "get_weather",
    "description": "Restituisce il meteo per una città.",
    "parameters": {
        "type": "object",
        "properties": {
            "location": {"type": "string", "description": "Città, es. Milano, IT"}
        },
        "required": ["location"]
    }
}

interaction = client.interactions.create(
    model="gemini-3-flash-preview",
    input="Che tempo fa a Roma?",
    tools=[weather_tool]
)

# Se il modello vuole chiamare una funzione:
for output in interaction.outputs:
    if output.type == "function_call":
        result = my_dispatcher(output.name, output.args)
        # Inviare il risultato come turno successivo
        client.interactions.create(
            model="gemini-3-flash-preview",
            previous_interaction_id=interaction.id,
            input=[{
                "type": "function_result",
                "name": output.name,
                "call_id": output.call_id,
                "result": result  # dict, str, o lista di content objects
            }]
        )
```

**Nota:** `result` deve essere dict, stringa o lista di content objects. MAI una lista grezza di oggetti arbitrari.

---

## Output strutturato (JSON schema)

```python
interaction = client.interactions.create(
    model="gemini-3-flash-preview",
    input="Elenca 3 capitali europee con popolazione.",
    generation_config={
        "response_mime_type": "application/json",
        "response_schema": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "city": {"type": "string"},
                    "population": {"type": "integer"}
                }
            }
        }
    }
)
import json
data = json.loads(interaction.outputs[-1].text)
```

---

## Generazione di immagini

```python
import base64

interaction = client.interactions.create(
    model="gemini-3-pro-image-preview",   # oppure gemini-3.1-flash-image-preview
    input="Una città futuristica al tramonto.",
    response_modalities=["IMAGE"],
    generation_config={
        "image_config": {
            "aspect_ratio": "16:9",   # 1:1 | 2:3 | 3:4 | 4:5 | 9:16 | 16:9 | 21:9 ecc.
            "image_size": "1k"         # 1k | 2k | 4k
        }
    }
)

for output in interaction.outputs:
    if output.type == "image":
        with open("out.png", "wb") as f:
            f.write(base64.b64decode(output.data))
```

---

## Generazione vocale (TTS)

```python
import base64, wave

interaction = client.interactions.create(
    model="gemini-3.1-flash-tts-preview",  # oppure gemini-2.5-flash-preview-tts
    input="Benvenuto nell'app! [laughs]",
    response_modalities=["AUDIO"],
    generation_config={
        "speech_config": {
            "language": "it-IT",
            "voice": "kore"   # vari: kore, puck, zephyr, ecc.
        }
    }
)

# Output: PCM 24000 Hz, 16-bit, mono
for output in interaction.outputs:
    if output.type == "audio":
        pcm = base64.b64decode(output.data)
        # Salva come WAV:
        with wave.open("out.wav", "wb") as wf:
            wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(24000)
            wf.writeframes(pcm)
```

**Multi-speaker:**
```python
generation_config={
    "speech_config": [
        {"voice": "Zephyr", "speaker": "Alice", "language": "it-IT"},
        {"voice": "Puck",   "speaker": "Bob",   "language": "it-IT"}
    ]
}
```

---

## MCP remoto

```python
interaction = client.interactions.create(
    model="gemini-3-flash-preview",
    input="Controlla l'ultimo deployment.",
    tools=[{
        "type": "mcp_server",
        "name": "Deployment Tracker",
        "url": "https://mcp.example.com/mcp",
        "headers": {"Authorization": "Bearer TOKEN"},
        "allowed_tools": ["get_status", "list_deployments"]  # facoltativo
    }]
)
```

---

## Modelli e agenti supportati (aprile 2026)

### Modelli di testo/multimodali

| Model ID | Note | Tier |
|---|---|---|
| `gemini-3-flash-preview` | Veloce, smart, vision+audio | Free + Paid |
| `gemini-3.1-pro-preview` | Qualità massima | Solo Paid |
| `gemini-3.1-flash-lite-preview` | Più economico, task agentici | Free + Paid |
| `gemini-2.5-pro` | Coding/reasoning, 1M ctx | Free + Paid |
| `gemini-2.5-flash` | Ragionamento ibrido, 1M ctx | Free + Paid |
| `gemini-2.5-flash-lite` | Più piccolo/economico | Free + Paid |

### Modelli di generazione immagini

| Model ID | Note |
|---|---|
| `gemini-3-pro-image-preview` | Qualità Pro, testo+immagine |
| `gemini-3.1-flash-image-preview` | Veloce |
| `gemini-2.5-flash-image` | 2.5 Flash quality |

### TTS

| Model ID | Note |
|---|---|
| `gemini-3.1-flash-tts-preview` | Bassa latenza, controllabile |
| `gemini-2.5-flash-preview-tts` | Buon rapporto qualità/prezzo |
| `gemini-2.5-pro-preview-tts` | Parlato più naturale |

### Musica (Lyria 3)

| Model ID | Output |
|---|---|
| `lyria-3-clip-preview` | Clip 30 secondi |
| `lyria-3-pro-preview` | Brano completo ~4 min |

### Agenti Deep Research → vedi gemini-deep-research.md

- Deep Research: `deep-research-preview-04-2026`
- Deep Research Max: `deep-research-max-preview-04-2026`

---

## Prezzi (paid tier, USD per 1M token, aprile 2026)

| Modello | Input | Output |
|---|---|---|
| gemini-3-flash-preview | $0.50 (testo/img/video) | $3.00 |
| gemini-3.1-flash-lite-preview | $0.25 | $1.50 |
| gemini-3.1-pro-preview | $2.00 (≤200K) / $4.00 (>200K) | $12.00 / $18.00 |
| gemini-2.5-pro | $1.25 (≤200K) / $2.50 (>200K) | $10.00 / $15.00 |
| gemini-2.5-flash | $0.30 (testo/img/video) | $2.50 |
| gemini-2.5-flash-lite | $0.10 | $0.40 |

**Google Search grounding:**
- Gemini 3: 5000 query/mese gratis, poi $14/1000 query
- Gemini 2.5: 1500 RPD gratis, poi $35/1000 prompt grounded

**URL context:** fatturato come token di input normali.
**Code execution:** token di output al momento della generazione, token di input quando il modello li usa nel ragionamento.

---

## Limitazioni Interactions API (beta)

- Gli schemi possono cambiare (breaking changes possibili)
- Non supporta output strutturato per gli agenti Deep Research
- `store=true` default: le interazioni vengono salvate sul server
- Gestione stato: i campi ereditati dall'interazione precedente non vanno rispecificati (modello, system_instruction, tools); gli altri vanno sempre passati esplicitamente

## Stato server-side, store e retention (Interactions)

- **`previous_interaction_id`** conserva solo **cronologia input/output**.
- I seguenti parametri sono **ambito interazione** e vanno ripassati a ogni turno se servono:
  - `tools`
  - `system_instruction`
  - `generation_config` (es. `temperature`, `thinking_level`, ecc.)
- **Retention** per `store=true`:
  - **Paid**: 55 giorni
  - **Free**: 1 giorno
- `store=false`:
  - non compatibile con `background=true`
  - impedisce l’uso di `previous_interaction_id`
