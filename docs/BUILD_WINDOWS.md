# Build the Windows application

The build must run on Windows because PyInstaller bundles for the operating system on which it runs.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\build_windows.bat
```

The script runs Ruff and the full test suite, builds the standalone `JDToolUpdater.exe`, bundles it into `dist\BankStatementToTally`, and runs the frozen self-test from a path containing spaces. Distribute the complete application folder. Tesseract is intentionally not bundled; install it separately on machines that process scanned PDFs.

For a clean manual build:

```powershell
.\.venv\Scripts\pyinstaller.exe --noconfirm --clean JDToolUpdater.spec
.\.venv\Scripts\pyinstaller.exe --noconfirm --clean BankStatementToTally.spec
```

## Tagged releases

`app.__version__` is the sole version source. Push a stable matching tag such as `v0.6.0`; `.github/workflows/release.yml` rejects a mismatch, tests and builds both executables, creates `JD-Tool-windows-x64-v0.6.0.zip`, generates `update-manifest.json`, and publishes both files to GitHub Releases.

The application checks only the public stable release endpoint for `jerin288/JD-Tool`. Downloads are accepted only when the manifest size and SHA-256 match and every ZIP path passes the safe-extraction rules.

PyInstaller's current usage documentation is at https://pyinstaller.org/en/stable/usage.html.
