@echo off
REM Versione semplificata senza file .spec

echo ========================================
echo Build Eseguibile OCR + LangExtract (Semplice)
echo ========================================
echo.

REM Verifica Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERRORE: Python non trovato!
    pause
    exit /b 1
)

echo Installazione PyInstaller...
python -m pip install pyinstaller --quiet

echo Installazione dipendenze...
python -m pip install -r requirements.txt --quiet

echo Pulizia...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"

echo Creazione eseguibile...
pyinstaller --name="OCR_LangExtract" ^
    --onefile ^
    --windowed ^
    --add-data "config;config" ^
    --hidden-import=customtkinter ^
    --hidden-import=customtkinter.windows ^
    --collect-all langextract ^
    --hidden-import=google.genai ^
    --hidden-import=fitz ^
    --hidden-import=dotenv ^
    --clean ^
    --noconfirm ^
    main.py

if errorlevel 1 (
    echo ERRORE durante la build!
    pause
    exit /b 1
)

echo.
echo Build completata! Eseguibile in: dist\OCR_LangExtract.exe
pause
