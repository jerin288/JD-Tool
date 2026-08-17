# Installation

## Ready-built Windows application

Copy the complete `dist\BankStatementToTally` folder to the target Windows 10 or 11 computer and run `BankStatementToTally.exe`. Keep every file in that folder together. Application data is written to `%LOCALAPPDATA%\BankStatementToTally`; statement processing remains local.

Install Tesseract separately only if scanned/image-only PDFs must be processed. See [TESSERACT_SETUP.md](TESSERACT_SETUP.md).

## Run from source

1. Install 64-bit Python 3.12 and enable **Add Python to PATH**.
2. Open PowerShell in the project directory.
3. Run:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

If `py` reports “No suitable Python runtime found”, install Python 3.12 from python.org and reopen PowerShell. Do not use the Microsoft Store launcher alias as a substitute for a complete development installation.

## Local data

Source runs use `data`, `config`, `exports`, `logs`, and `backups` inside the project. The packaged app uses the equivalent folders under `%LOCALAPPDATA%\BankStatementToTally`.
