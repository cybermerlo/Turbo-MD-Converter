# Batch Rename Context (LLM Examples) Implementation Plan
 
> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan.
 
**Goal:** Rendere le rinomine automatiche coerenti all’interno di un batch, passando al modello esempi delle rinomine già effettuate.
 
**Architecture:** Manteniamo una “rename history” in memoria per la durata di `process_batch`. Ad ogni file successivo, iniettiamo nel prompt di rinomina una sezione con esempi `originale -> finale` (ultimi N) e istruzioni per mantenere lo stesso stile. Dopo la rinomina effettiva su disco, aggiungiamo l’esempio reale alla history.
 
**Tech Stack:** Python, logging, pipeline events già esistenti, Gemini (google-genai).
 
---
 
### Task 1: Aggiungere supporto esempi al prompt LLM
 
**Files:**
- Modify: `C:/Programmi Locali/Turbo-MD-Converter/utils/file_renamer.py`
 
**Step 1: Aggiornare API pubblica**
- Estendere `derive_filename_from_llm(...)` con un parametro opzionale `rename_examples` (lista di esempi del batch).
 
**Step 2: Costruire blocco di contesto**
- Generare testo “Esempi già usati in questo batch” includendo solo gli ultimi N esempi (es. 8) ma senza perdere la history in memoria.
 
**Step 3: Iniettare il contesto nel prompt**
- Prependere (o inserire prima di “Testo OCR:”) il blocco esempi + istruzioni “mantieni stesso stile/terminologia”.
 
**Step 4: Verifica manuale**
- Eseguire l’app e verificare che il prompt venga composto e che la rinomina continui a funzionare.
 
---
 
### Task 2: Mantenere e aggiornare la history durante il batch
 
**Files:**
- Modify: `C:/Programmi Locali/Turbo-MD-Converter/pipeline/processor.py`
 
**Step 1: Creare history per batch**
- In `process_batch`, inizializzare `rename_history = []` e passarla a `process_single`.
 
**Step 2: Passare esempi alla derivazione nome**
- In `process_single`, passare gli esempi a `derive_filename_from_llm(...)`.
 
**Step 3: Aggiornare history dopo rinomina reale**
- In `_rename_files`, dopo ogni `rename_file(...)` riuscita, aggiungere un record alla history:
  - `original_name`, `final_name`, `date_str`, `description`, `file_type`.
 
**Step 4: Verifica manuale**
- Avviare batch con più file e verificare che le rinomine successive risultino più coerenti.
 
