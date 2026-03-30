@echo off
setlocal

cd /d "%~dp0"

REM Prefer Windows Python launcher if available
py -3 main.py
if %errorlevel% equ 0 goto :eof

REM Fallback to python on PATH
python main.py
if %errorlevel% equ 0 goto :eof

echo.
echo Errore: impossibile avviare main.py.
echo Assicurati che Python sia installato e disponibile come "py" o "python".
echo.
pause
exit /b 1

