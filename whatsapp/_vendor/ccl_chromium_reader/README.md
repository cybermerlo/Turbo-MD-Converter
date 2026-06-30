# `ccl_chromium_reader` (vendorizzato — sottoinsieme IndexedDB)

Codice di terze parti **incluso nel repo** (vendoring) perché la libreria **non è
pubblicata su PyPI** (esiste solo su GitHub) e una dipendenza git-only non è
impacchettabile in modo affidabile nell'`.exe` (cx_Freeze). Vendorizzando, la
feature "import WhatsApp Desktop → mittenti" funziona **identica da sorgente e
nell'installer**, senza dipendenze esterne a runtime.

## Cosa c'è (solo la catena di lettura IndexedDB)
- `ccl_chromium_indexeddb.py` — API alto livello (`WrappedIndexDB`, ecc.)
- `storage_formats/ccl_leveldb.py` — lettore LevelDB
- `serialization_formats/ccl_v8_value_deserializer.py` — deserializzatore valori V8
- `serialization_formats/ccl_blink_value_deserializer.py` — wrapper Blink
- `ccl_simplesnappy.py` — decompressore Snappy puro-Python (da repo separato)

**Volutamente escluso** tutto il resto del pacchetto upstream (cache, history,
filesystem, localstorage, ecc.) e la dipendenza nativa **`Brotli`**: non servono
per leggere l'IndexedDB. Per questo l'`__init__.py` locale è minimale e non
importa nulla — così l'import non trascina `Brotli`.

## Provenienza
- `ccl_chromium_reader` — https://github.com/cclgroupltd/ccl_chromium_reader
  (branch `master`), versione pyproject `0.3.14`. Autore: Alex Caithness / CCL Solutions.
- `ccl_simplesnappy` — https://github.com/cclgroupltd/ccl_simplesnappy (branch `main`).
- Licenza: **MIT** (CCL Forensics). Vedi `LICENSE.ccl_chromium_reader` e
  `LICENSE.ccl_simplesnappy` in questa cartella.

## Patch locali (rispetto all'upstream)
1. `storage_formats/ccl_leveldb.py`: l'import assoluto `import ccl_simplesnappy` è
   stato reso **relativo** (`from .. import ccl_simplesnappy`) perché snappy è
   vendorizzato alla radice di questo pacchetto invece che come modulo top-level.
2. `__init__.py` (questo pacchetto e i sottopacchetti): sostituiti con versioni
   minimali per non importare i moduli upstream dipendenti da `Brotli`.
3. `ccl_chromium_indexeddb.py` → `IndexedDb._cache_records`: aggiunto un
   `time.sleep(0)` ogni ~16k record (cede il GIL) così la lettura iniziale del
   LevelDB (~1 min) non blocca la UI Tkinter dell'app. Marcato con `[vendor patch]`.

Nessun'altra modifica al codice sorgente.

## Accesso a interni (fuori da questo pacchetto)
`whatsapp/desktop_indexeddb.py::_ScopedSenders` usa alcuni dettagli interni di ccl
(`IndexedDb._fetched_records`, `make_prefix`, `read_record_precursor`, `IdbKey`,
`_le_varint_from_bytes`) per estrarre i mittenti di una sola chat senza
deserializzare tutti i messaggi. Se si aggiorna il vendor e questi interni
cambiano, `open_index` ricade automaticamente sul full-scan (più lento ma robusto).

## Aggiornare
Riscaricare i due repo, ricopiare i file elencati sopra e riapplicare la patch 1.
