# Privacy and data handling

- PDFs, rendered OCR pages, transactions, XML, backups, and logs stay on the local computer.
- OCR uses the configured local Tesseract executable; no web OCR or external API is called.
- PDF passwords are held only for the active extraction and are not stored.
- OCR page images are rendered in memory and discarded.
- Logs contain technical events, not extracted statement text. Account-like numbers and UPI addresses are masked.
- Local backups contain the database and settings, so protect the backup folder like the original accounting data.
- Tally communication is limited to the configured local/private HTTP endpoint.
