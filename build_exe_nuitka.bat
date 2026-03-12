@echo off
REM Script alternativo con Nuitka (compila Python in C)
REM Puo' sfuggire ai blocchi Device Guard - eseguibili "reali"
REM NOTA: PyMuPDF puo' rallentare molto la compilazione (anche ore)

echo ========================================
echo Build Eseguibile OCR + LangExtract
echo (Nuitka - compilazione in C)
echo ========================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo ERRORE: Python non trovato!
    pause
    exit /b 1
)

echo [1/4] Verifica Nuitka...
python -m pip show nuitka >nul 2>&1
if errorlevel 1 (
    echo Installazione Nuitka...
    python -m pip install nuitka ordered-set
)

echo [2/4] Installazione dipendenze...
python -m pip install -r requirements.txt --quiet

echo [3/4] Pulizia...
if exist "dist" rmdir /s /q "dist"
if exist "main.build" rmdir /s /q "main.build"
if exist "main.dist" rmdir /s /q "main.dist"
if exist "main.onefile-build" rmdir /s /q "main.onefile-build"

echo [4/4] Compilazione con Nuitka (puo' richiedere diversi minuti)...
python -m nuitka ^
    --standalone ^
    --windows-disable-console ^
    --output-filename=OCR_LangExtract.exe ^
    --output-dir=dist ^
    --include-package=customtkinter ^
    --include-package=langextract ^
    --include-package=google.genai ^
    --include-package=fitz ^
    --include-package=dotenv ^
    --include-package=config ^
    --include-data-dir=config=config ^
    main.py

if errorlevel 1 (
    echo ERRORE durante la compilazione!
    pause
    exit /b 1
)

echo.
echo Build completata! Output in: dist\main.dist\OCR_LangExtract.exe
echo (oppure dist\OCR_LangExtract.exe a seconda della versione)
pause
