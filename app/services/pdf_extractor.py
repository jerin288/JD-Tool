"""Password-aware text and table extraction for bank statement PDFs."""

from __future__ import annotations

import logging
import re
from bisect import bisect_right
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.services.ocr_service import OcrService, TesseractNotFoundError

LOGGER = logging.getLogger(__name__)


class PdfExtractionError(RuntimeError):
    """A safe, user-facing PDF extraction error."""


class PdfPasswordRequiredError(PdfExtractionError):
    pass


class IncorrectPdfPasswordError(PdfExtractionError):
    pass


@dataclass(slots=True)
class ExtractedPage:
    page_number: int
    text: str
    tables: list[list[list[str]]] = field(default_factory=list)


@dataclass(slots=True)
class PdfExtractionResult:
    source_path: Path
    pages: list[ExtractedPage]
    rows: list[list[str]]
    warnings: list[str] = field(default_factory=list)

    @property
    def page_count(self) -> int:
        return len(self.pages)


class PdfExtractor:
    """Extract selectable text and selectively OCR scanned pages."""

    STATEMENT_COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
        "SlNo": ("slno", "sno", "serial", "serial no"),
        "Transaction Date": ("date", "transaction date", "txn date", "tran date", "posting date", "transaction"),
        "Value Date": ("value date", "val date", "value"),
        "Particulars": ("particulars", "description", "narration", "remarks", "transaction details", "details"),
        "Cheque Number": ("cheque number", "cheque no", "chq no", "chq ref no", "cheque", "chq", "instrument no"),
        "Withdrawals": ("withdrawals", "withdrawal", "debit", "debit amount", "withdrawal amount", "withdrawal amt", "dr"),
        "Deposits": ("deposits", "deposit", "credit", "credit amount", "deposit amount", "deposit amt", "cr"),
        "Balance Amount": ("balance amount", "balance", "closing balance", "available balance", "running balance"),
    }

    def __init__(self, ocr_service: OcrService | None = None) -> None:
        self.ocr_service = ocr_service

    def extract(
        self,
        path: Path,
        password: str = "",
        progress: Callable[[int, int, str], None] | None = None,
    ) -> PdfExtractionResult:
        if not path.exists() or path.suffix.lower() != ".pdf":
            raise PdfExtractionError("Select an existing PDF file.")
        try:
            return self._extract_with_pdfplumber(path, password, progress)
        except (PdfPasswordRequiredError, IncorrectPdfPasswordError):
            raise
        except Exception as primary_error:
            LOGGER.warning("pdfplumber failed for %s: %s", path.name, primary_error)
            try:
                return self._extract_with_pymupdf(path, password, str(primary_error), progress)
            except (PdfPasswordRequiredError, IncorrectPdfPasswordError):
                raise
            except PdfExtractionError:
                raise
            except Exception as fallback_error:
                LOGGER.exception("Both PDF extraction engines failed for %s", path.name)
                raise PdfExtractionError(
                    "The PDF could not be read. It may be damaged or use an unsupported encoding."
                ) from fallback_error

    def _extract_with_pdfplumber(
        self,
        path: Path,
        password: str,
        progress: Callable[[int, int, str], None] | None,
    ) -> PdfExtractionResult:
        import pdfplumber

        pages: list[ExtractedPage] = []
        all_rows: list[list[str]] = []
        warnings: list[str] = []
        try:
            document_context = pdfplumber.open(path, password=password or None)
        except Exception as exc:
            self._raise_password_error(exc, password)
            raise
        with document_context as document:
            if not document.pages:
                raise PdfExtractionError("The selected PDF contains no pages.")
            coordinate_headers: list[str] | None = None
            coordinate_starts: list[float] | None = None
            primary_headers: list[str] | None = None
            for page_number, page in enumerate(document.pages, start=1):
                if progress:
                    progress(page_number - 1, len(document.pages), f"Reading page {page_number}")
                try:
                    text = page.extract_text(x_tolerance=2, y_tolerance=3) or ""
                    page_words = page.extract_words(
                        x_tolerance=2, y_tolerance=3, keep_blank_chars=False
                    ) or []
                    detected_header = self._detect_statement_header(page_words)
                    if detected_header is not None:
                        coordinate_headers, coordinate_starts, _ = detected_header
                    found_tables = page.find_tables() or []
                    tables: list[list[list[str]]] = []
                    for found_table in found_tables:
                        raw_table = found_table.extract() or []
                        cleaned_table = self._clean_table(raw_table)
                        expanded_table = self._expand_stacked_table(
                            page, found_table, raw_table, cleaned_table
                        )
                        if expanded_table:
                            tables.append(expanded_table)
                        elif cleaned_table:
                            tables.append(cleaned_table)
                    gridless_table = self._extract_gridless_serial_table(page, found_tables)
                    date_table = self._extract_gridless_date_table(page)
                    page_used_coordinate_table = False
                    if gridless_table:
                        tables = [gridless_table]
                    elif date_table:
                        tables = [date_table]
                    elif not self._has_useful_table(tables):
                        coordinate_table, coordinate_headers, coordinate_starts = self._extract_coordinate_table(
                            page, coordinate_headers, coordinate_starts
                        )
                        if coordinate_table:
                            tables = [coordinate_table]
                            page_used_coordinate_table = True
                    if primary_headers is None:
                        for table in tables:
                            if table and self._is_statement_header_row(table[0]):
                                primary_headers = table[0]
                                break
                    if (
                        page_used_coordinate_table
                        and primary_headers is not None
                        and coordinate_headers is not None
                        and not self._statement_headers_match(coordinate_headers, primary_headers)
                    ):
                        tables = [
                            self._project_rows_to_headers(table, coordinate_headers, primary_headers)
                            for table in tables
                        ]
                    page_rows = [row for table in tables for row in table]
                    if not page_rows and text:
                        page_rows = self._text_to_rows(text)
                    all_rows.extend(page_rows)
                    pages.append(ExtractedPage(page_number, text, tables))
                except Exception:
                    LOGGER.exception("Page %d extraction failed", page_number)
                    pages.append(ExtractedPage(page_number, "", []))
                    warnings.append(f"Page {page_number} could not be extracted and was skipped.")

        pages, ocr_warnings = self._ocr_empty_pages(path, password, pages, progress)
        warnings.extend(ocr_warnings)
        all_rows = []
        for page in pages:
            page_rows = [row for table in page.tables for row in table]
            if not page_rows:
                page_rows = self._text_to_rows(page.text)
            all_rows.extend(page_rows)
        if not any(page.text.strip() for page in pages):
            raise PdfExtractionError("No readable text was found in this statement, including after OCR.")
        return PdfExtractionResult(path, pages, self._rectangularize(all_rows), warnings)

    def _extract_with_pymupdf(
        self,
        path: Path,
        password: str,
        reason: str,
        progress: Callable[[int, int, str], None] | None,
    ) -> PdfExtractionResult:
        import fitz

        pages: list[ExtractedPage] = []
        rows: list[list[str]] = []
        with fitz.open(path) as document:
            if document.needs_pass:
                if not password:
                    raise PdfPasswordRequiredError("This PDF is password-protected.")
                if not document.authenticate(password):
                    raise IncorrectPdfPasswordError("The PDF password is incorrect.")
            if document.page_count == 0:
                raise PdfExtractionError("The selected PDF contains no pages.")
            for page_index in range(document.page_count):
                if progress:
                    progress(page_index, document.page_count, f"Reading page {page_index + 1}")
                text = document[page_index].get_text("text") or ""
                pages.append(ExtractedPage(page_index + 1, text))
                rows.extend(self._text_to_rows(text))
        pages, warnings = self._ocr_empty_pages(path, password, pages, progress)
        rows = []
        for page in pages:
            page_rows = [row for table in page.tables for row in table]
            if not page_rows:
                page_rows = self._text_to_rows(page.text)
            rows.extend(page_rows)
        if not any(page.text.strip() for page in pages):
            raise PdfExtractionError("No readable text was found in this statement, including after OCR.")
        return PdfExtractionResult(
            path,
            pages,
            self._rectangularize(rows),
            [f"Used fallback extractor: {reason}", *warnings],
        )

    def _ocr_empty_pages(
        self,
        path: Path,
        password: str,
        pages: list[ExtractedPage],
        progress: Callable[[int, int, str], None] | None,
    ) -> tuple[list[ExtractedPage], list[str]]:
        empty_pages = [page.page_number for page in pages if not page.text.strip() and not page.tables]
        if not empty_pages:
            return pages, []
        if self.ocr_service is None:
            raise PdfExtractionError("This appears to be a scanned statement, but OCR is not configured.")
        try:
            ocr_pages, warnings = self.ocr_service.extract_pages(path, empty_pages, password, progress)
        except TesseractNotFoundError as exc:
            raise PdfExtractionError(str(exc)) from exc
        by_number = {page.page_number: page for page in ocr_pages}
        for index, page in enumerate(pages):
            recognized = by_number.get(page.page_number)
            if recognized is None:
                continue
            ocr_rows = self._ocr_words_to_rows(recognized.words, recognized.text)
            pages[index] = ExtractedPage(page.page_number, recognized.text, [ocr_rows] if ocr_rows else [])
            warnings.append(
                f"Page {page.page_number} was read with OCR (average confidence {recognized.mean_confidence:.0f}%)."
            )
        return pages, warnings

    @classmethod
    def _ocr_words_to_rows(cls, words: list[dict[str, object]], text: str) -> list[list[str]]:
        if not words:
            return cls._text_to_rows(text)
        detected = cls._detect_statement_header(words)
        if detected is None:
            return cls._text_to_rows(text)
        headers, starts, header_top = detected
        lines = [line for line in cls._word_lines(words) if float(line[0]["top"]) > header_top + 2]
        rows: list[list[str]] = [headers]
        for line in lines:
            cells: list[list[dict[str, Any]]] = [[] for _ in headers]
            for word in line:
                column = bisect_right(starts, float(word["x0"]) + 1) - 1
                if 0 <= column < len(cells):
                    cells[column].append(word)
            row = [cls._join_positioned_words(cell) for cell in cells]
            if any(row):
                rows.append(row)
        return rows

    @staticmethod
    def _raise_password_error(error: Exception, supplied_password: str) -> None:
        message = str(error).lower()
        if any(token in message for token in ("password", "encrypted", "decrypt")):
            if supplied_password:
                raise IncorrectPdfPasswordError("The PDF password is incorrect.") from error
            raise PdfPasswordRequiredError("This PDF is password-protected.") from error

    @staticmethod
    def _clean_table(table: list[list[object]]) -> list[list[str]]:
        return [
            [re.sub(r"\s+", " ", str(cell or "").replace("\n", " ")).strip() for cell in row]
            for row in table
            if any(str(cell or "").strip() for cell in row)
        ]

    @staticmethod
    def _has_useful_table(tables: list[list[list[str]]]) -> bool:
        """Reject narrow false-positive tables such as account-address blocks."""
        return any(max((len(row) for row in table), default=0) >= 3 for table in tables)

    @classmethod
    def _expand_stacked_table(
        cls,
        page: Any,
        table: Any,
        raw_table: list[list[object]],
        cleaned_table: list[list[str]],
    ) -> list[list[str]]:
        """Split vertically stacked transactions from a single tall PDF table row.

        Some bank PDFs draw column borders but omit horizontal borders between
        transactions. pdfplumber consequently returns one cell per column with
        every page value separated by newlines. Date positions remain reliable,
        so use each date in the first column as a transaction-row anchor and use
        the detected PDF column geometry to rebuild the individual rows.
        """
        columns = list(getattr(table, "columns", []) or [])
        table_rows = list(getattr(table, "rows", []) or [])
        if len(columns) < 5 or not raw_table or len(raw_table) != len(table_rows):
            return []

        date_pattern = re.compile(r"(?<!\d)\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}(?!\d)")
        body_index = next(
            (
                index
                for index, row in enumerate(raw_table)
                if row and len(date_pattern.findall(str(row[0] or ""))) >= 2
            ),
            None,
        )
        if body_index is None:
            return []

        body_bbox = getattr(table_rows[body_index], "bbox", None)
        if not body_bbox or len(body_bbox) != 4:
            return []
        body_top, body_bottom = float(body_bbox[1]), float(body_bbox[3])

        starts = [float(column.bbox[0]) for column in columns]
        table_left = starts[0]
        table_right = float(columns[-1].bbox[2])
        first_column_right = float(columns[0].bbox[2])
        words = page.extract_words(
            x_tolerance=2, y_tolerance=3, keep_blank_chars=False
        ) or []
        body_words = [
            word
            for word in words
            if body_top - 1 <= float(word["top"]) < body_bottom + 1
            and table_left - 1 <= float(word["x0"]) < table_right + 1
        ]
        date_anchors = sorted(
            (
                word
                for word in body_words
                if table_left - 1 <= float(word["x0"]) < first_column_right
                and cls._looks_like_date(str(word["text"]))
            ),
            key=lambda word: float(word["top"]),
        )
        if len(date_anchors) < 2:
            return []

        def row_for_band(top: float, bottom: float) -> list[str]:
            cells: list[list[dict[str, Any]]] = [[] for _ in columns]
            for word in body_words:
                word_top = float(word["top"])
                if not top <= word_top < bottom:
                    continue
                column_index = bisect_right(starts, float(word["x0"]) + 1) - 1
                if 0 <= column_index < len(cells):
                    cells[column_index].append(word)
            return [cls._join_positioned_words(cell) for cell in cells]

        rebuilt: list[list[str]] = []
        first_top = float(date_anchors[0]["top"])
        leading = row_for_band(body_top - 1, first_top - 2)
        if any(leading):
            rebuilt.append(leading)

        for index, anchor in enumerate(date_anchors):
            top = float(anchor["top"]) - 2
            bottom = (
                float(date_anchors[index + 1]["top"]) - 2
                if index + 1 < len(date_anchors)
                else body_bottom + 1
            )
            row = row_for_band(top, bottom)
            if any(row):
                rebuilt.append(row)

        header_rows = [
            row
            for row in cleaned_table[:body_index]
            if row and cls.normalize_table_header(row[0]) in {"date", "transaction date", "txn date"}
        ]
        return [*header_rows, *rebuilt]

    @staticmethod
    def normalize_table_header(value: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value.lower())).strip()

    @classmethod
    def _canonical_statement_column(cls, value: str) -> str | None:
        normalized = cls.normalize_table_header(value)
        if not normalized:
            return None
        for column, aliases in cls.STATEMENT_COLUMN_ALIASES.items():
            if normalized in aliases:
                return column
        return None

    @classmethod
    def _is_statement_header_row(cls, row: list[str]) -> bool:
        columns = {
            column
            for column in (cls._canonical_statement_column(cell) for cell in row)
            if column is not None
        }
        return (
            "Transaction Date" in columns
            and "Particulars" in columns
            and bool({"Withdrawals", "Deposits", "Balance Amount"} & columns)
        )

    @classmethod
    def _statement_headers_match(cls, left: list[str], right: list[str]) -> bool:
        return [cls._canonical_statement_column(value) for value in left] == [
            cls._canonical_statement_column(value) for value in right
        ]

    @classmethod
    def _project_rows_to_headers(
        cls, rows: list[list[str]], source_headers: list[str], target_headers: list[str]
    ) -> list[list[str]]:
        source_columns = [cls._canonical_statement_column(value) for value in source_headers]
        source_indexes = {
            column: index
            for index, column in enumerate(source_columns)
            if column is not None
        }
        target_columns = [cls._canonical_statement_column(value) for value in target_headers]
        projections = [source_indexes.get(column) for column in target_columns]
        return [
            [row[index] if index is not None and index < len(row) else "" for index in projections]
            for row in rows
        ]

    @classmethod
    def _extract_gridless_serial_table(
        cls, page: Any, found_tables: list[Any]
    ) -> list[list[str]]:
        """Rebuild a gridless transaction body below a bordered header row.

        Kotak statements expose a seven-column header as a real PDF table, but
        draw the transaction body without row or column borders. The serial
        number in the first column is a stable row anchor even when dates,
        narration, and references wrap onto additional lines.
        """
        header_table = None
        header: list[str] = []
        for table in found_tables:
            raw_table = table.extract() or []
            cleaned = cls._clean_table(raw_table)
            columns = list(getattr(table, "columns", []) or [])
            if len(cleaned) != 1 or len(columns) < 6:
                continue
            candidate = cleaned[0]
            normalized = [cls.normalize_table_header(cell) for cell in candidate]
            if (
                normalized
                and normalized[0] in {"", "#", "sl no", "slno", "serial no"}
                and any("transaction date" in cell for cell in normalized)
                and any("balance" in cell for cell in normalized)
            ):
                header_table = table
                header = candidate
                break
        if header_table is None:
            return []

        columns = list(header_table.columns)
        starts = [float(column.bbox[0]) for column in columns]
        table_left = starts[0]
        table_right = float(columns[-1].bbox[2])
        serial_right = float(columns[0].bbox[2])
        body_top = float(header_table.bbox[3])
        words = page.extract_words(
            x_tolerance=2, y_tolerance=3, keep_blank_chars=False
        ) or []

        footer_top = float(page.height)
        for line in cls._word_lines(words):
            line_text = " ".join(str(word["text"]) for word in line)
            normalized_line = cls.normalize_table_header(line_text)
            line_top = min(float(word["top"]) for word in line)
            if line_top > body_top and normalized_line.startswith("statement generated on"):
                footer_top = min(footer_top, line_top - 2)

        body_words = [
            word
            for word in words
            if body_top - 1 <= float(word["top"]) < footer_top
            and table_left - 1 <= float(word["x0"]) < table_right + 1
        ]
        serial_anchors = sorted(
            (
                word
                for word in body_words
                if table_left - 1 <= float(word["x0"]) < serial_right
                and re.fullmatch(r"\d+", str(word["text"]).strip())
            ),
            key=lambda word: float(word["top"]),
        )
        if not serial_anchors:
            return []

        def row_for_band(top: float, bottom: float) -> list[str]:
            cells: list[list[dict[str, Any]]] = [[] for _ in columns]
            for word in body_words:
                word_top = float(word["top"])
                if not top <= word_top < bottom:
                    continue
                column_index = bisect_right(starts, float(word["x0"]) + 1) - 1
                if 0 <= column_index < len(cells):
                    cells[column_index].append(word)
            return [cls._join_positioned_words(cell) for cell in cells]

        rows = [header]
        for index, anchor in enumerate(serial_anchors):
            top = float(anchor["top"]) - 2
            bottom = (
                float(serial_anchors[index + 1]["top"]) - 2
                if index + 1 < len(serial_anchors)
                else footer_top
            )
            row = row_for_band(top, bottom)
            if any(row):
                rows.append(row)
        return rows

    @classmethod
    def _extract_gridless_date_table(cls, page: Any) -> list[list[str]]:
        """Rebuild fixed-width statements whose transaction date anchors each row.

        Finacle printouts from Union Bank can contain two logical statement pages
        on one PDF page. They have no table borders or serial-number column, but
        repeat a stable DATE/PARTICULARS/CHQ.NO./WITHDRAWALS/DEPOSITS/BALANCE
        header. Split each repeated section independently and use transaction
        dates as row boundaries so multiline narration remains attached.
        """
        words = page.extract_words(
            x_tolerance=2, y_tolerance=3, keep_blank_chars=False
        ) or []
        specifications = (
            ("Date", {"date", "transactiondate", "trandate", "txndate"}),
            ("Particulars", {"particulars", "description", "narration", "remarks"}),
            ("Cheque Number", {"chqno", "chq", "chequeno", "chequenumber", "instrumentno"}),
            ("Withdrawals", {"withdrawal", "withdrawals", "debit"}),
            ("Deposits", {"deposit", "deposits", "credit"}),
            ("Balance Amount", {"balance", "closingbalance"}),
        )
        sections: list[tuple[float, float, list[str], list[float]]] = []
        lines = cls._word_lines(words)
        for line in lines:
            anchors: list[tuple[float, str]] = []
            for label, aliases in specifications:
                match = next(
                    (
                        word
                        for word in line
                        if re.sub(r"[^a-z0-9]+", "", str(word["text"]).casefold())
                        in aliases
                    ),
                    None,
                )
                if match is not None:
                    anchors.append((float(match["x0"]), label))
            labels = {label for _, label in anchors}
            required = {"Date", "Particulars", "Withdrawals", "Deposits", "Balance Amount"}
            if required.issubset(labels):
                ordered = sorted(anchors)
                labels_in_order = [label for _, label in ordered]
                positions = [position for position, _ in ordered]
                column_starts: list[float] = []
                for index, (position, label) in enumerate(ordered):
                    if label == "Date":
                        column_starts.append(position - 10)
                    elif label == "Particulars":
                        column_starts.append(position - 2)
                    elif label == "Cheque Number":
                        column_starts.append(position - 15)
                    else:
                        column_starts.append((positions[index - 1] + position) / 2)
                sections.append(
                    (
                        min(float(word["top"]) for word in line),
                        max(float(word.get("bottom", word["top"])) for word in line),
                        labels_in_order,
                        column_starts,
                    )
                )
        if not sections:
            return []
        sections.sort(key=lambda item: item[0])
        if sections[0][0] > 250:
            sections.insert(0, (0.0, 0.0, sections[0][2].copy(), sections[0][3].copy()))

        rebuilt: list[list[str]] = []
        for section_index, (header_top, header_bottom, headers, starts) in enumerate(sections):
            section_bottom = (
                sections[section_index + 1][0] - 2
                if section_index + 1 < len(sections)
                else float(page.height)
            )
            for line in lines:
                line_top = min(float(word["top"]) for word in line)
                if not header_bottom < line_top < section_bottom:
                    continue
                normalized = cls.normalize_table_header(
                    " ".join(str(word["text"]) for word in line)
                )
                raw_line = " ".join(str(word["text"]) for word in line).casefold()
                if normalized.startswith("cumulative totals") or "finacle.ubi.com" in raw_line:
                    section_bottom = min(section_bottom, line_top - 2)
                    break

            body_start = header_bottom
            for line in lines:
                line_top = min(float(word["top"]) for word in line)
                if not body_start <= line_top < section_bottom:
                    continue
                normalized = cls.normalize_table_header(
                    " ".join(str(word["text"]) for word in line)
                )
                if normalized.startswith("transaction details page"):
                    body_start = max(
                        body_start,
                        max(float(word.get("bottom", word["top"])) for word in line),
                    )

            body_words = [
                word
                for word in words
                if body_start < float(word["top"]) < section_bottom
                and starts[0] - 2 <= float(word["x0"])
            ]
            first_column_right = starts[1]
            date_anchors = sorted(
                (
                    word
                    for word in body_words
                    if starts[0] - 2 <= float(word["x0"]) < first_column_right
                    and cls._looks_like_date(str(word["text"]))
                ),
                key=lambda word: float(word["top"]),
            )
            if not date_anchors:
                continue

            def row_for_band(top: float, bottom: float) -> list[str]:
                cells: list[list[dict[str, Any]]] = [[] for _ in headers]
                for word in body_words:
                    word_top = float(word["top"])
                    if not top <= word_top < bottom:
                        continue
                    column_index = bisect_right(starts, float(word["x0"]) + 1) - 1
                    if 0 <= column_index < len(cells):
                        cells[column_index].append(word)
                return [cls._join_positioned_words(cell) for cell in cells]

            rebuilt.append(headers.copy())
            leading = row_for_band(body_start + 1, float(date_anchors[0]["top"]) - 2)
            particulars_index = headers.index("Particulars")
            if leading[particulars_index] and (section_index > 0 or header_top == 0):
                rebuilt.append(leading)
            for anchor_index, anchor in enumerate(date_anchors):
                top = float(anchor["top"]) - 2
                bottom = (
                    float(date_anchors[anchor_index + 1]["top"]) - 2
                    if anchor_index + 1 < len(date_anchors)
                    else section_bottom
                )
                row = row_for_band(top, bottom)
                if any(row):
                    rebuilt.append(row)
        return rebuilt

    @classmethod
    def _extract_coordinate_table(
        cls,
        page: Any,
        headers: list[str] | None,
        starts: list[float] | None,
    ) -> tuple[list[list[str]], list[str] | None, list[float] | None]:
        """Reconstruct gridless statement tables from word and shaded-row coordinates."""
        words = page.extract_words(x_tolerance=2, y_tolerance=3, keep_blank_chars=False) or []
        header_top: float | None = None
        if not headers or not starts:
            detected = cls._detect_statement_header(words)
            if detected is None:
                return [], headers, starts
            headers, starts, header_top = detected
        else:
            detected = cls._detect_statement_header(words)
            if detected is not None:
                headers, starts, header_top = detected

        assert headers is not None and starts is not None
        page_width = float(page.width)
        row_bands: list[tuple[float, float]] = []
        for rectangle in page.rects or []:
            x0 = float(rectangle.get("x0", 0))
            x1 = float(rectangle.get("x1", 0))
            top = float(rectangle.get("top", 0))
            bottom = float(rectangle.get("bottom", 0))
            if (
                x1 - x0 >= page_width * 0.65
                and x0 <= starts[0] + 10
                and x1 >= starts[-1] + 20
                and 10 <= bottom - top <= 120
                and not (header_top is not None and top <= header_top <= bottom)
                and (header_top is None or top > header_top)
            ):
                row_bands.append((top, bottom))

        rows: list[list[str]] = []
        serial_index = headers.index("SlNo") if "SlNo" in headers else 0
        date_index = headers.index("Transaction Date") if "Transaction Date" in headers else 1
        for top, bottom in sorted(set(row_bands)):
            cells: list[list[dict[str, Any]]] = [[] for _ in headers]
            for word in words:
                word_top = float(word["top"])
                x0 = float(word["x0"])
                if top - 1 <= word_top < bottom + 1:
                    column = bisect_right(starts, x0 + 1) - 1
                    if 0 <= column < len(cells):
                        cells[column].append(word)
            row = [cls._join_positioned_words(cell) for cell in cells]
            if re.fullmatch(r"\d+", row[serial_index]) and cls._looks_like_date(row[date_index]):
                rows.append(row)

        if not rows:
            return [], headers, starts
        if header_top is not None:
            rows.insert(0, headers.copy())
        return rows, headers, starts

    @classmethod
    def _detect_statement_header(cls, words: list[dict[str, Any]]) -> tuple[list[str], list[float], float] | None:
        specifications = (
            ("SlNo", {"slno", "sno", "serial"}),
            ("Transaction Date", {"transaction", "txn"}),
            ("Value Date", {"value"}),
            ("Particulars", {"particulars", "description", "narration"}),
            ("Cheque Number", {"cheque", "chq"}),
            ("Withdrawals", {"withdrawal", "withdrawals", "debit"}),
            ("Deposits", {"deposit", "deposits", "credit"}),
            ("Balance Amount", {"balance"}),
        )
        for line in cls._word_lines(words):
            anchors: list[tuple[float, str]] = []
            for label, aliases in specifications:
                match = next(
                    (word for word in line if re.sub(r"[^a-z0-9]+", "", str(word["text"]).casefold()) in aliases),
                    None,
                )
                if match is not None:
                    anchors.append((float(match["x0"]), label))
            labels = {label for _, label in anchors}
            if (
                len(anchors) >= 5
                and "Transaction Date" in labels
                and "Particulars" in labels
                and "Balance Amount" in labels
            ):
                ordered = sorted(anchors)
                return (
                    [label for _, label in ordered],
                    [position for position, _ in ordered],
                    min(float(word["top"]) for word in line),
                )
        return None

    @staticmethod
    def _word_lines(words: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
        lines: list[list[dict[str, Any]]] = []
        for word in sorted(words, key=lambda item: (float(item["top"]), float(item["x0"]))):
            line = next(
                (candidate for candidate in lines if abs(float(candidate[0]["top"]) - float(word["top"])) <= 2),
                None,
            )
            if line is None:
                lines.append([word])
            else:
                line.append(word)
        return lines

    @staticmethod
    def _join_positioned_words(words: list[dict[str, Any]]) -> str:
        return " ".join(
            str(word["text"]).strip()
            for word in sorted(words, key=lambda item: (float(item["top"]), float(item["x0"])))
            if str(word["text"]).strip()
        )

    @staticmethod
    def _looks_like_date(value: str) -> bool:
        return bool(
            re.fullmatch(
                r"(?:\d{1,2}[-/.][A-Za-z]{3}[-/.]\d{2,4}|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4})",
                value.strip(),
            )
        )

    @staticmethod
    def _text_to_rows(text: str) -> list[list[str]]:
        rows: list[list[str]] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            cells = [cell.strip() for cell in re.split(r"\s{2,}|\t+", line) if cell.strip()]
            rows.append(cells or [line])
        return rows

    @staticmethod
    def _rectangularize(rows: list[list[str]]) -> list[list[str]]:
        if not rows:
            return []
        width = max(len(row) for row in rows)
        return [row + [""] * (width - len(row)) for row in rows]
