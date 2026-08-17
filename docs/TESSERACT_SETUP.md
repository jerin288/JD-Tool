# Tesseract OCR setup

OCR is invoked only for pages with no useful selectable text. Digital PDFs continue through the faster text/table extractor.

1. Install a current 64-bit Tesseract 5 build for Windows and include English trained data.
2. Confirm `C:\Program Files\Tesseract-OCR\tesseract.exe` exists.
3. In the app, open **Settings & Tools > App**.
4. Enter the full executable path, set the language (`eng` by default) and use 300 DPI.
5. Save settings and import the scanned PDF again.

Additional languages require the matching `.traineddata` file in Tesseract's `tessdata` directory. Multiple languages may be entered using Tesseract notation such as `eng+hin`. OCR images are rendered in memory and are not uploaded or retained.

The official Tesseract documentation explains Windows binaries and trained-data placement: https://tesseract-ocr.github.io/tessdoc/Installation.html
