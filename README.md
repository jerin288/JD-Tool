# Bank Statement PDF to Tally Prime XML Converter

Version 0.6.0 adds optional daily GitHub Release checks, verified portable updates, restart health checks, and automatic one-version rollback.

Documentation: [Installation](docs/INSTALLATION.md) | [Tesseract OCR](docs/TESSERACT_SETUP.md) | [User guide](docs/USER_GUIDE.md) | [Tally configuration](docs/TALLY_CONFIGURATION.md) | [Troubleshooting](docs/TROUBLESHOOTING.md) | [Windows build](docs/BUILD_WINDOWS.md) | [Privacy](docs/PRIVACY.md)

A privacy-first Windows desktop application that extracts bank-statement transactions, validates and matches them, generates balanced Tally Prime voucher XML, and can import each voucher into a locally running Tally company. This repository currently contains the complete **Phases 1 through 4** requested in the project specification.

## Unified accounting workspace

The daily workflow now runs in one responsive main window: select or drop a PDF, extract and map columns, review or bulk-edit transactions, connect to Tally, match ledgers, validate, preview XML, export, and import without navigating between separate pages. The transaction table remains the largest area at 1366×768 and above, while transaction details, column mapping, export options, templates, matching rules, history, logs, theme, and backup controls use collapsible in-window panels.

Keyboard shortcuts include `Ctrl+O` open, `Ctrl+E` extract, `Ctrl+F` search, `Ctrl+S` save details, `Ctrl+Z` undo, `Ctrl+Y` redo, `Delete` remove selected rows, `Ctrl+A` select filtered rows while the table is focused, `Ctrl+Shift+V` validate, and `Ctrl+Shift+E` export XML.

## Phase 1 capabilities

- Select a PDF or drag it onto the import screen.
- Open password-protected PDFs without storing the password.
- Extract tables and selectable text with `pdfplumber`, falling back to PyMuPDF.
- Continue past individual page failures and report actionable errors.
- Suggest transaction columns from common Indian bank headings.
- Preview up to 250 extracted rows and manually map columns.
- Parse multiple date formats and both split Debit/Credit and Amount + DR/CR layouts.
- Keep all money as `Decimal`; no monetary value is converted through a float.
- Ignore common opening/closing balance, total, and repeated-header rows.
- Review transactions in an editable, sortable, searchable, paginated table.
- Edit dates, descriptions, references, amounts, balances, voucher types, and opposite ledgers.
- Multi-select, delete, duplicate, undo, and redo edits.
- Auto-save imports and edits to SQLite using transactional writes.
- Use background extraction so the interface remains responsive.
- Switch among System, Light, and Dark themes.
- Mask plausible account numbers in logs and rotate log files.

## Phase 2 capabilities

- Load bank templates dynamically from JSON without application source changes.
- Adapt layouts for SBI, South Indian Bank, Federal Bank, HDFC, ICICI, Axis, Kotak Mahindra, Canara, PNB, Bank of Baroda, Union Bank of India, and Yes Bank.
- Detect a bank from statement text and apply its aliases and cleanup rules.
- Save a corrected column mapping as a reusable bank template.
- Merge continuation rows into multiline descriptions and narrations.
- Normalize Indian-formatted, negative, parenthesized, and DR/CR-suffixed amounts.
- Validate dates, amount direction, voucher types, ledgers, ignored rows, duplicates, and invalid control characters.
- Detect probable duplicates using date, amount, direction, reference, description, and balance.
- Confirm duplicates, mark false positives as unique, and ignore or restore rows.
- Reconcile opening balance, movement, expected closing balance, and statement difference.
- Export an atomic, formatted Excel workbook with Transactions and Summary sheets.
- Migrate existing Phase 1 SQLite databases without deleting saved imports.

## Phase 3 capabilities

- Test the loopback Tally Prime HTTP connection with clear timeout, disabled-server, invalid-response, and not-running errors.
- Discover one or several open Tally companies and let the user select the intended company.
- Download ledger names, parent groups, and voucher types from the selected company.
- Select the statement's bank ledger from Tally bank and cash ledgers.
- Match using saved rules, exact names, keywords, substrings, normalized text, fuzzy similarity, then `Suspense A/c`.
- Remove UPI IDs, UTR and cheque references, dates, long numbers, transfer prefixes, codes, spaces, and punctuation during normalized matching.
- Display matching confidence and the method used for every transaction.
- Create, update, disable, prioritize, count, and delete persistent matching rules.
- Assign Payment and Receipt automatically while using Contra only for transfers involving the business's own cash or bank ledgers.
- Keep NEFT, IMPS, RTGS, and UPI vendor/customer payments out of Contra classification.
- Keep all Tally communication on `localhost` or another loopback address.

## Phase 4 capabilities

- Validate every voucher before XML generation and present row-specific errors and warnings.
- Generate Tally Envelope, Header, Body, Import Data, Request Description, Request Data, and accounting voucher structures.
- Enforce Tally's negative-debit convention: Payment and bank-charge vouchers debit the counter-ledger and credit the bank; Receipt vouchers debit the bank and credit the counter-ledger; Contra follows the bank transfer direction.
- Guarantee that the two ledger entries balance exactly and block zero, missing, non-finite, or conflicting amounts.
- Generate Payment, Receipt, and Contra vouchers with dates, voucher numbers, narration, persistent view, entry mode, and bank allocations.
- Escape XML special characters through the XML library and reject forbidden control characters.
- Support balanced Double Entry and Single Entry Payment/Receipt modes.
- Export one combined XML file, separate files by voucher type, or separate files by month.
- Restrict exports to an optional date period and retry only transactions whose prior import failed.
- Preview the exact generated XML before writing or importing it.
- Import vouchers into Tally individually so Created, Altered, Ignored, Error, and Failed results can be stored against the correct transaction.
- Continue after voucher-specific Tally errors while stopping safely on a lost server connection.
- Persist direct-import summaries in the Import History screen.

Phase 5 adds selective scanned-page OCR, performance hardening, privacy-safe logging, automatic backups, expanded tests, packaged runtime paths, and the verified Windows build. Version 0.6.0 adds a prompt-and-restart updater backed by public stable GitHub Releases. Update ZIPs are size-checked, SHA-256 verified, and safely extracted before a separate updater swaps the portable folder. User data under `%LOCALAPPDATA%\BankStatementToTally` is not replaced.

## Project layout

```text
.
├── main.py
├── requirements.txt
├── config/
│   ├── settings.json
│   └── bank_templates/generic_indian_bank.json
├── app/
│   ├── models/           # typed transaction and mapping domain objects
│   ├── views/            # CustomTkinter screens and editable table
│   ├── controllers/      # workflow orchestration
│   ├── services/         # PDF extraction, parsing, settings
│   ├── repositories/     # transaction persistence
│   ├── database/         # SQLite schema and connections
│   └── utils/            # amount, privacy, and logging helpers
├── tests/
├── data/                 # generated SQLite database (gitignored)
├── logs/                 # rotating runtime logs (gitignored)
└── exports/
```

## Windows installation

1. Install 64-bit [Python 3.12](https://www.python.org/downloads/) and enable **Add python.exe to PATH** in the installer.
2. In PowerShell, from this project directory, create and activate a virtual environment:

   ```powershell
   py -3.12 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```

3. Start the application:

   ```powershell
   python main.py
   ```

   Once `.venv` has been created, Windows users can also double-click `run_app.bat`. The launcher invokes the local environment directly, so it works even when the global `py` command cannot find Python.

Application data is processed locally. PDF passwords exist only for the duration of extraction and are cleared from the password field immediately afterward.

## User guide

1. Open **Import PDF**, browse to a statement, or drop a PDF onto the large drop area.
2. Leave Bank set to **Automatic** unless you want to label the import. Enter a password only for an encrypted PDF.
3. Select **Extract Statement**. The UI remains usable while extraction runs.
4. On **Column Mapping**, check each automatic selection against the raw data preview. Row numbers are one-based. Map either Debit/Credit or Amount plus DR/CR.
5. Choose the statement date format or leave it on `AUTO`, then select **Create Review Table**.
6. Double-click a review-table cell to edit it. Dates must be saved as `YYYY-MM-DD`. Press Enter or click away to save; Escape cancels.
7. Use Search, Debit/Credit filters, sortable column headings, multiple selection, Duplicate, Delete, Undo, Redo, and page controls as needed.
8. Select **Validate & Find Duplicates**. Filter possible duplicates, then confirm each duplicate or mark it unique.
9. Optionally enter opening and closing balances and select **Reconcile**.
10. Select **Export Excel** to save the cleaned table and validation summary.

To reuse a corrected layout, select **Save as Bank Template** on Column Mapping. The new JSON template appears under **Bank Templates** and can be applied to another extracted PDF.

### Tally ledger matching

1. Start Tally Prime, open the required company, and enable its HTTP server on port `9000`.
2. Open **Ledger Matching** and select **Test Tally Connection**.
3. If several companies are open, choose the intended company and select **Download Ledgers**.
4. Select the bank ledger represented by the imported statement.
5. Select **Auto-match Transactions**, then review Confidence and Match Method in Transaction Review.
6. Create reusable description rules under **Saved Rules**. A lower priority number runs first. An optional voucher-type override is applied only when that rule matches.

Connection testing fetches only company metadata, and ledger download fetches only ledger/voucher-type metadata. Bank transactions are sent only after the explicit **Import into Tally** confirmation in Phase 4.

### XML export and direct import

1. Complete ledger matching and correct every invalid or unmatched transaction.
2. Open **XML Export**. Confirm the exact Tally company, voucher mode, grouping, period, and output folder.
3. Select **Validate** and correct all errors shown in the Validation Report.
4. Select **Generate Preview** to inspect the exact XML that will be saved or sent.
5. Select **Export XML Files** for manual Tally import, or **Import into Tally** for direct local import.
6. Review Created, Altered, Ignored, Error, and Failed counts in the Import Report.
7. Use **Import History** for previous reports. After correcting failures, enable **Failed imports only** and retry them separately.

The generated synthetic example is available at `samples/sample_tally_vouchers.xml`.

## PDF behavior and limitations

`pdfplumber` is used first because it can extract text and tables together. PyMuPDF provides a resilient text fallback. Pages without useful selectable text are rendered in memory and passed to the configured local Tesseract engine. Text pages in a mixed PDF are not OCRed. Page-specific OCR failures become review warnings instead of discarding successful pages. No PDF content is sent over the network.

Statement formats vary widely. A saved bank template can preserve a corrected mapping and cleanup rules. Gridless statements with detectable headers and shaded transaction rows are reconstructed from their PDF coordinates, including multiline particulars across pages. Unusual layouts may still require a bank-specific template, and the mapping preview exposes raw extraction before records are committed.

## Running tests

```powershell
python -m unittest discover -s tests -v
```

The suite covers all five phases, including OCR word/column reconstruction, missing-engine guidance, backups, logging redaction, runtime paths, XML structure, exact Payment/Receipt/Contra signs, voucher balance, grouping, validation, Tally response counts, and persistence.

## PyInstaller Windows build

Build and test from the project root:

```powershell
.\build_windows.bat
```

The verified executable is `dist\BankStatementToTally\BankStatementToTally.exe`; distribute its complete folder. The packaged app stores writable data under `%LOCALAPPDATA%\BankStatementToTally`.

## Tesseract OCR setup

Install Tesseract 5 with English trained data, then configure `C:\Program Files\Tesseract-OCR\tesseract.exe`, language, and DPI under **Settings & Tools > App**. The extractor invokes it only for pages without selectable text. See `docs/TESSERACT_SETUP.md`.

## Tally Prime configuration (Phases 3–4)

Open the target company in Tally Prime, enable its HTTP service, and confirm port `9000`. The connection URL defaults to `http://localhost:9000` and rejects non-loopback hosts. Test the connection, download ledgers, validate the XML, and keep the same company open during direct import. Back up the Tally company before the first production import.

## Troubleshooting

- **`py -3.12` not found:** install Python 3.12 from python.org and reopen PowerShell.
- **PowerShell blocks activation:** run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, or use `.venv\Scripts\python.exe main.py` without activating.
- **Tesseract not found:** install the local OCR engine and save its executable path under **Settings & Tools > App**.
- **Password rejected:** verify that it is the PDF document password, not an online-banking login. Passwords are case-sensitive.
- **Mapping produces no transactions:** choose the actual header row, verify the date column, and map either Debit/Credit or Amount plus DR/CR.
- **Rows are split incorrectly:** try OCR at 300 or 400 DPI, verify the language, correct the mapping, and save it as a bank template.
- **The interface opens but drag-and-drop does not work:** file browsing remains available; reinstall `tkinterdnd2` in the active virtual environment.
- **Technical diagnosis:** inspect `logs\application.log`. Account-like numbers are masked before logging.
- **Tally connection refused:** start Tally Prime and enable its HTTP service on port `9000`.
- **Connected but no company:** open the required company in Tally, then test again.
- **Several companies detected:** choose the intended company before downloading ledgers.
- **Invalid Tally response:** confirm that the URL is `http://localhost:9000` and is not another local web service.
- **Tally ledger XML contains invalid characters:** the app repairs XML-forbidden numeric references and raw control bytes before retrying the response. A repair count is written to the privacy-safe application log. If parsing still fails, clean the affected ledger or group name in Tally.
- **Too many Suspense matches:** add a saved rule, reduce the fuzzy threshold carefully in `config/settings.json`, or create the missing ledger in Tally and download ledgers again.
- **XML generation blocked:** open the Validation Report and correct every row marked Error. Warnings do not block export.
- **Tally ignored a voucher:** inspect the row's Import Message and the Import Report, correct its ledger, voucher type, date, or duplicate status, then retry with **Failed imports only**.
- **Connection lost during import:** remaining vouchers are marked Failed without being sent. Restart Tally, test the connection, and retry failed imports.

## Security notes

- Bank data never leaves the computer.
- Bank-statement content and Tally data are never sent externally. The optional updater sends only a standard release request to GitHub.
- PDF passwords are never written to disk or logs.
- Full account-number-like digit sequences are masked in logs.
- SQLite stores normalized transaction data locally in `data\bank_converter.db`; protect or remove that file according to your retention policy.
