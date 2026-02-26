@echo off
REM Script per creare l'eseguibile Windows con PyInstaller

echo ========================================
echo Build Eseguibile OCR + LangExtract
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
python -m pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo PyInstaller non trovato. Installazione in corso...
    python -m pip install pyinstaller
    if errorlevel 1 (
        echo ERRORE: Impossibile installare PyInstaller!
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

echo [4/4] Creazione eseguibile con PyInstaller...
pyinstaller build_exe.spec --clean --noconfirm

if errorlevel 1 (
    echo.
    echo ERRORE durante la creazione dell'eseguibile!
    pause
    exit /b 1
)

echo.
echo ========================================
echo Build completata con successo!
echo ========================================
echo.
echo L'eseguibile si trova in: dist\OCR_LangExtract.exe
echo.
echo Puoi copiare l'eseguibile e usarlo su qualsiasi PC Windows
echo (non serve installare Python o le dipendenze).
echo.
pause
