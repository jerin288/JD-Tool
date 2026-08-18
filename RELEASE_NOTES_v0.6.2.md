# JD Tool v0.6.2

Improves extraction and template detection for Union Bank of India (Finacle) bank statements.

## Fixes & improvements
- Bank template detection now prioritizes the bank name found in the statement header, so statements that mention other banks in narration or beneficiary fields are detected correctly.
- Added gridless, date-anchored table extraction for Union Bank Finacle PDFs, including:
  - two logical statement pages on a single PDF page
  - multiline transaction narration
- Expanded Union Bank column aliases for Date, Particulars, Chq.No., Withdrawals, Deposits, and Balance.

## Tests
- Added coverage for repeated sections and multiline rows in date-anchored table extraction.
- Added coverage ensuring the header bank name outranks beneficiary bank names during detection.

## Update notes
- In-app updates require a published GitHub Release tagged `v0.6.2` with the Windows ZIP asset and `update-manifest.json`.