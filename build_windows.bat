@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo ERROR: .venv is missing. Run the installation steps in docs\INSTALLATION.md first.
  exit /b 1
)

call ".venv\Scripts\python.exe" -m pip --disable-pip-version-check install -r requirements-lock.txt
if errorlevel 1 exit /b 1

call ".venv\Scripts\python.exe" -m pytest -q
if errorlevel 1 exit /b 1

call ".venv\Scripts\python.exe" -m ruff check .
if errorlevel 1 exit /b 1

call ".venv\Scripts\pyinstaller.exe" --noconfirm --clean JDToolUpdater.spec
if errorlevel 1 exit /b 1

call ".venv\Scripts\pyinstaller.exe" --noconfirm --clean BankStatementToTally.spec
if errorlevel 1 exit /b 1

powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\frozen_self_test.ps1"
if errorlevel 1 (
  echo ERROR: Frozen runtime self-test failed.
  exit /b 1
)

echo Build complete: dist\BankStatementToTally\BankStatementToTally.exe
echo Updater complete: dist\JDToolUpdater.exe
endlocal
