# JD Tool v0.6.3

Fixes multi-page bank statement extraction and adds New Ledger creation for Tally Prime.

## Fixes & improvements
- Multi-page PDF extraction now keeps page-1 column mapping for borderless continuation pages, so transactions from page 2 onward are no longer skipped.
- Added a New Ledger action to create ledgers in Tally Prime directly from the workspace.
- Creation results, including Tally duplicate/validation messages, are shown in the status bar.

## Tests
- Added regression coverage for coordinate-column projection and statement header detection.
- Added controller/client coverage for Tally ledger creation.
