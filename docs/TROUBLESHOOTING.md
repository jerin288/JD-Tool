# Troubleshooting

## No suitable Python runtime found

Install Python 3.12 x64 from python.org, reopen PowerShell, then create `.venv` as shown in the installation guide. Ready-built users do not need Python.

## Tesseract was not found

Install Tesseract 5, verify `tesseract.exe`, and save the path under **Settings & Tools > App**. The Python `pytesseract` package alone is not the OCR engine.

## OCR output has poor columns

Use a 300 or 400 DPI setting, verify the correct OCR language, and prefer the bank's original digital PDF when available. Correct the column mapping before creating the review table.

## Tally returns invalid XML or HTML

Confirm the URL points to Tally Prime's local XML server, normally `http://localhost:9000`, and that a company is open. A browser or unrelated service on port 9000 can return HTML, which is rejected safely.

## Vouchers are reversed

Re-export using the current build. Payment/bank-charge bank entries must be credits; receipt bank entries must be debits. Delete or cancel incorrectly imported test vouchers before importing corrected XML.

## Logs and diagnostics

Open **Settings & Tools > App > Open Logs Folder**. Logs rotate at 2 MB with five retained files. Account-like numbers and UPI addresses are masked; transaction descriptions and extracted statement contents are never deliberately logged.
