# Tally Prime configuration

1. Open the target company in Tally Prime.
2. Enable the local HTTP/XML interface on port 9000.
3. Keep Tally open, enter `http://localhost:9000` in the converter, and select **Test Connection**.
4. Select the open company, download ledgers, and choose the statement's bank ledger.
5. Review unmatched ledgers and validation errors before export or direct import.

Accounting direction used by XML export:

- Payment and bank charges: opposite ledger debit; bank ledger credit.
- Receipt: bank ledger debit; opposite ledger credit.
- Contra: direction follows the statement debit/credit while both entries remain bank/cash ledgers.

The generated XML uses balanced double-entry amounts and matching `ISDEEMEDPOSITIVE` values. Always test a small period in a backup company before a production import.
