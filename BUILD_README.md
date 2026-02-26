# Creazione Eseguibile Windows

Questa guida spiega come creare un eseguibile Windows (.exe) per l'applicazione OCR + LangExtract.

## Prerequisiti

1. **Python 3.10 o superiore** installato su Windows
2. Tutte le dipendenze installate (vedi `requirements.txt`)

## Metodo 1: Script Automatico (Consigliato)

1. Apri il prompt dei comandi o PowerShell nella cartella del progetto
2. Esegui:
   ```batch
   build_exe.bat
   ```

Lo script:
- Verifica che Python sia installato
- Installa PyInstaller se necessario
- Installa/aggiorna tutte le dipendenze
- Pulisce le build precedenti
- Crea l'eseguibile

L'eseguibile sarà disponibile in `dist\OCR_LangExtract.exe`

## Metodo 2: Comando Manuale

Se preferisci eseguire i comandi manualmente:

```batch
REM Installa PyInstaller
pip install pyinstaller

REM Installa dipendenze
pip install -r requirements.txt

REM Crea l'eseguibile
pyinstaller build_exe.spec --clean --noconfirm
```

## Utilizzo dell'Eseguibile

1. Copia `dist\OCR_LangExtract.exe` su qualsiasi PC Windows
2. Esegui il file .exe (doppio click)
3. Non è necessario installare Python o altre dipendenze

**Nota:** La prima esecuzione potrebbe essere più lenta mentre l'applicazione si inizializza.

## Personalizzazione

### Aggiungere un'Icona

1. Crea o scarica un file `.ico`
2. Modifica `build_exe.spec` e cambia la riga:
   ```python
   icon=None,  # Cambia con: icon='path/to/icona.ico',
   ```

### Modificare il Nome dell'Eseguibile

Modifica la riga `name='OCR_LangExtract'` in `build_exe.spec`

### Mostrare la Console (per debug)

Se vuoi vedere i log nella console, modifica in `build_exe.spec`:
```python
console=True,  # invece di console=False
```

## Risoluzione Problemi

### Errore: "PyInstaller non trovato"
```batch
pip install pyinstaller
```

### Errore: "Modulo non trovato"
Aggiungi il modulo mancante alla lista `hiddenimports` in `build_exe.spec`

### L'eseguibile è troppo grande
PyInstaller include tutte le dipendenze. Per ridurre la dimensione:
- Usa `--exclude-module` per escludere moduli non necessari
- Considera l'uso di `--onefile` invece di `--onedir` (ma può essere più lento all'avvio)

### Antivirus segnala l'eseguibile
Gli eseguibili creati con PyInstaller possono essere segnalati da alcuni antivirus. Questo è un falso positivo comune. Puoi:
- Aggiungere un'eccezione nell'antivirus
- Firmare digitalmente l'eseguibile (richiede certificato)

## Note

- La prima build può richiedere alcuni minuti
- L'eseguibile sarà grande (circa 100-200 MB) perché include Python e tutte le dipendenze
- L'eseguibile è standalone: non richiede Python installato sul PC di destinazione
