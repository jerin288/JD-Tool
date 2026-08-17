@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
    echo The project environment is missing.
    echo Create it and install requirements before running this launcher.
    pause
    exit /b 1
)

start "Bank Statement to Tally" ".venv\Scripts\pythonw.exe" "main.py"
endlocal
