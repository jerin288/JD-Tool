"""Automatic column discovery and normalized transaction parsing."""

from __future__ import annotations

import re
from datetime import date, datetime

import pandas as pd
from dateutil import parser as date_parser

from app.models.bank_template import BankTemplate
from app.models.enums import ValidationStatus, VoucherType
from app.models.mapping import ColumnMapping
from app.models.transaction import Transaction
from app.services.transaction_normalizer import TransactionNormalizer
from app.utils.amounts import parse_decimal

COLUMN_ALIASES: dict[str, set[str]] = {
    "transaction_date": {"date", "transaction date", "txn date", "tran date", "posting date"},
    "value_date": {"value date", "val date"},
    "description": {"description", "narration", "particulars", "transaction details", "remarks"},
    "reference_number": {"reference", "reference number", "ref no", "transaction id", "utr number", "utr"},
    "cheque_number": {"cheque number", "cheque no", "chq no", "instrument no"},
    "debit": {"debit", "withdrawal", "withdrawals", "debit amount", "withdrawal amount", "dr"},
    "credit": {"credit", "deposit", "deposits", "credit amount", "deposit amount", "cr"},
    "amount": {"amount", "transaction amount", "txn amount"},
    "dr_cr": {"dr cr", "dr/cr", "type", "transaction type"},
    "balance": {"balance", "closing balance", "available balance", "running balance"},
}

IGNORE_TERMS = {
    "opening balance", "closing balance", "brought forward", "carried forward",
    "total", "page total", "statement summary",
}


class TransactionParser:
    """Converts arbitrary extracted rows into strongly typed transactions."""

    def suggest_mapping(
        self, rows: list[list[str]], template: BankTemplate | None = None
    ) -> ColumnMapping:
        """Score candidate header rows and return the strongest alias mapping."""
        aliases = {key: set(values) for key, values in COLUMN_ALIASES.items()}
        if template:
            for field_name, template_aliases in template.column_aliases.items():
                aliases.setdefault(field_name, set()).update(
                    self.normalize_header(alias) for alias in template_aliases
                )
        best_mapping = ColumnMapping()
        best_score = -1
        for row_index, row in enumerate(rows[:30]):
            candidate = ColumnMapping(header_row=row_index)
            matches = 0
            claimed: set[str] = set()
            for column_index, cell in enumerate(row):
                normalized = self.normalize_header(cell)
                available = [(name, values) for name, values in aliases.items() if name not in claimed]
                exact = next((name for name, values in available if normalized in values), None)
                matched_field = exact
                if matched_field is None:
                    partials = [
                        (len(alias), name)
                        for name, values in available
                        for alias in values
                        if len(alias) > 3 and alias in normalized
                    ]
                    matched_field = max(partials, default=(0, None))[1]
                if matched_field is not None:
                    setattr(candidate, matched_field, column_index)
                    claimed.add(matched_field)
                    matches += 1
            score = matches + (2 if candidate.transaction_date is not None else 0)
            score += 2 if candidate.debit is not None or candidate.credit is not None or candidate.amount is not None else 0
            if score > best_score:
                best_mapping, best_score = candidate, score
        if template:
            stored = template.mapping
            has_saved_columns = False
            for field_name in ColumnMapping.COLUMN_FIELDS:
                stored_index = getattr(stored, field_name)
                if stored_index is not None and stored_index < max((len(row) for row in rows), default=0):
                    setattr(best_mapping, field_name, stored_index)
                    has_saved_columns = True
            if stored.date_format != "AUTO":
                best_mapping.date_format = stored.date_format
            if has_saved_columns and 0 <= stored.header_row < len(rows):
                best_mapping.header_row = stored.header_row
        return best_mapping

    def parse(
        self,
        rows: list[list[str]],
        mapping: ColumnMapping,
        template: BankTemplate | None = None,
    ) -> tuple[list[Transaction], list[str]]:
        """Parse rows independently so one malformed record never stops an import."""
        mapping_errors = mapping.validate()
        if mapping_errors:
            raise ValueError(" ".join(mapping_errors))
        transactions: list[Transaction] = []
        warnings: list[str] = []
        frame = pd.DataFrame(rows, dtype="object").fillna("")
        data_rows = frame.iloc[mapping.header_row + 1 :]
        for source_index, series in data_rows.iterrows():
            source_row_number = int(source_index) + 1
            row = [str(value) for value in series.tolist()]
            if not any(cell.strip() for cell in row):
                continue
            if self._is_ignored_row(row, mapping, template):
                continue
            if template is None or template.multiline_enabled:
                if self._is_multiline_continuation(row, mapping) and transactions:
                    continuation = self._cleanup_text(
                        self._cell(row, mapping.description), template
                    )
                    if continuation:
                        joiner = template.multiline_joiner if template else " "
                        transactions[-1].description = f"{transactions[-1].description}{joiner}{continuation}".strip()
                        transactions[-1].narration = transactions[-1].description
                    reference = self._cell(row, mapping.reference_number)
                    if reference and reference not in transactions[-1].reference_number:
                        transactions[-1].reference_number = f"{transactions[-1].reference_number} {reference}".strip()
                    continue
            try:
                transaction = self._parse_row(row, mapping, source_row_number, template)
                if transaction is not None:
                    transactions.append(transaction)
            except (ValueError, IndexError) as exc:
                warnings.append(f"Row {source_row_number}: {exc}")
        return transactions, warnings

    def _parse_row(
        self,
        row: list[str],
        mapping: ColumnMapping,
        source_row_number: int,
        template: BankTemplate | None = None,
    ) -> Transaction | None:
        description = self._cleanup_text(self._cell(row, mapping.description), template)
        date_text = self._cell(row, mapping.transaction_date)
        transaction_date = self.parse_date(date_text, mapping.date_format)
        if transaction_date is None:
            raise ValueError(f"invalid transaction date {date_text!r}")

        debit, credit = TransactionNormalizer.normalize(
            self._cell(row, mapping.debit),
            self._cell(row, mapping.credit),
            self._cell(row, mapping.amount),
            self._cell(row, mapping.dr_cr),
        )

        balance_text = self._cell(row, mapping.balance)
        balance = parse_decimal(balance_text) if balance_text else None
        value_date_text = self._cell(row, mapping.value_date)
        voucher_type = VoucherType.PAYMENT if debit else VoucherType.RECEIPT
        return Transaction(
            row_number=source_row_number,
            transaction_date=transaction_date,
            value_date=self.parse_date(value_date_text, mapping.date_format) if value_date_text else None,
            description=description or "(No description)",
            reference_number=self._cell(row, mapping.reference_number),
            cheque_number=self._cell(row, mapping.cheque_number),
            debit_amount=debit,
            credit_amount=credit,
            balance=balance,
            voucher_type=voucher_type,
            narration=description,
            validation_status=ValidationStatus.VALID,
        )

    @staticmethod
    def parse_date(value: str, date_format: str = "AUTO") -> date | None:
        raw = value.strip()
        if not raw:
            return None
        if date_format and date_format != "AUTO":
            try:
                return datetime.strptime(raw, date_format).date()
            except ValueError as exc:
                raise ValueError(f"date {raw!r} does not match {date_format}") from exc
        try:
            return date_parser.parse(raw, dayfirst=True, fuzzy=False).date()
        except (ValueError, OverflowError):
            return None

    @staticmethod
    def normalize_header(value: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9/]+", " ", value.lower())).strip()

    @classmethod
    def _is_repeated_header(cls, row: list[str]) -> bool:
        matches = 0
        for cell in row:
            normalized = cls.normalize_header(cell)
            if any(normalized in aliases for aliases in COLUMN_ALIASES.values()):
                matches += 1
        return matches >= 2

    @classmethod
    def _is_ignored_row(
        cls, row: list[str], mapping: ColumnMapping, template: BankTemplate | None
    ) -> bool:
        if cls._is_repeated_header(row):
            return True
        description = re.sub(r"\s+", " ", cls._cell(row, mapping.description).strip().lower())
        terms = set(IGNORE_TERMS)
        if template:
            terms.update(item.strip().lower() for item in template.ignore_phrases)
        return any(description == term or description.startswith(f"{term} ") for term in terms)

    @classmethod
    def _is_multiline_continuation(cls, row: list[str], mapping: ColumnMapping) -> bool:
        if cls._cell(row, mapping.transaction_date):
            return False
        if not cls._cell(row, mapping.description):
            return False
        amount_indexes = (mapping.debit, mapping.credit, mapping.amount)
        return not any(cls._cell(row, index) for index in amount_indexes if index is not None)

    @staticmethod
    def _cleanup_text(value: str, template: BankTemplate | None) -> str:
        cleaned = re.sub(r"\s+", " ", value).strip()
        if template:
            for rule in template.cleanup_rules:
                pattern = rule.get("pattern", "")
                if pattern:
                    cleaned = re.sub(pattern, rule.get("replacement", ""), cleaned).strip()
        return cleaned

    @staticmethod
    def _cell(row: list[str], index: int | None) -> str:
        if index is None or index >= len(row):
            return ""
        return str(row[index] or "").strip()
