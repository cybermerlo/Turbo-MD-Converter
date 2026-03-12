@echo off
REM Script per creare l'eseguibile Windows (usa cx_Freeze invece di PyInstaller)
REM Alternativa utile se PyInstaller e' bloccato da Device Guard

echo ========================================
echo Build Eseguibile OCR + LangExtract
echo (cx_Freeze - alternativa a PyInstaller)
echo ========================================
echo.

REM Verifica che Python sia installato
python --version >nul 2>&1
if errorlevel 1 (
    echo ERRORE: Python non trovato! Assicurati che Python sia installato e nel PATH.
    pause
    exit /b 1
)

echo [1/4] Verifica dipendenze...
python -m pip show cx_Freeze >nul 2>&1
if errorlevel 1 (
    echo cx_Freeze non trovato. Installazione in corso...
    python -m pip install cx_Freeze
    if errorlevel 1 (
        echo ERRORE: Impossibile installare cx_Freeze!
        pause
        exit /b 1
    )
)

echo [2/4] Installazione/aggiornamento dipendenze...
python -m pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo ERRORE: Impossibile installare le dipendenze!
    pause
    exit /b 1
)

echo [3/4] Pulizia build precedenti...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
if exist "__pycache__" rmdir /s /q "__pycache__"

echo [4/4] Creazione eseguibile con cx_Freeze...
python setup_cxfreeze.py build_exe --build-exe=dist

if errorlevel 1 (
    echo.
    echo ERRORE durante la creazione dell'eseguibile!
    pause
    exit /b 1
)

REM cx_Freeze crea dist con exe e cartelle. Rinomino/copio se necessario
REM L'eseguibile e' in dist\OCR_LangExtract.exe (o dist\ con tutti i file)
echo.
echo ========================================
echo Build completata con successo!
echo ========================================
echo.
echo L'eseguibile e i file necessari si trovano in: dist\
echo Avvia: dist\OCR_LangExtract.exe
echo.
echo Per distribuire: copia l'intera cartella dist\ su qualsiasi PC Windows
echo (non serve installare Python o le dipendenze).
echo.
pause
