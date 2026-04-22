# Build Windows (cx_Freeze + Inno Setup)

Questa guida descrive il flusso attuale per generare l'installer Windows (`setup.exe`) usando **cx_Freeze** per creare una cartella di build e **Inno Setup** per impacchettarla in un installer.

Questo approccio (build “a cartella”, non “onefile”) tende a ridurre diversi falsi positivi antivirus rispetto agli eseguibili auto‑estraenti.

## Prerequisiti

- **Python** installato su Windows (versione compatibile con il progetto)
- Dipendenze installabili dal progetto
- **Inno Setup** installato (serve `ISCC.exe`)

## Build completa (consigliata)

Dalla root del progetto:

```powershell
python build_installer.py
```

Lo script:
- aggiorna la versione (`version.py` / `build_info.json`)
- esegue la build con `setup_cxfreeze.py`
- compila l'installer con Inno Setup (`installer/turbomd.iss`)

L'output finale è in `installer/output/` (file `TurboMDConverter_Setup_*.exe`).

## Solo installer (riusa build esistente)

Se hai già una build in `build/exe.*` e vuoi rigenerare solo il setup:

```powershell
python build_installer.py --iss-only
```

## Risoluzione problemi

### ISCC.exe non trovato

Installa Inno Setup e assicurati che `ISCC.exe` sia presente in uno dei path standard oppure nel `PATH` di sistema.
