"""Transaction validation and statement reconciliation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.models.enums import DuplicateStatus, ValidationStatus, VoucherType
from app.models.transaction import Transaction
from app.utils.ledger_names import is_numeric_ledger_reference

INVALID_XML_CHARACTERS = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")


@dataclass(frozen=True, slots=True)
class ValidationSummary:
    valid: int
    warnings: int
    invalid: int


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    opening_balance: Decimal | None
    total_debit: Decimal
    total_credit: Decimal
    expected_closing_balance: Decimal | None
    statement_closing_balance: Decimal | None
    difference: Decimal | None


class ValidationService:
    """Apply row-level checks without preventing correction of other records."""

    def validate_all(
        self,
        transactions: list[Transaction],
        period_start: date | None = None,
        period_end: date | None = None,
        require_ledgers: bool = False,
    ) -> ValidationSummary:
        counts = {ValidationStatus.VALID: 0, ValidationStatus.WARNING: 0, ValidationStatus.INVALID: 0}
        for item in transactions:
            status, message = self.validate(item, period_start, period_end, require_ledgers)
            item.validation_status = status
            item.validation_message = message
            if status in counts:
                counts[status] += 1
        return ValidationSummary(
            counts[ValidationStatus.VALID], counts[ValidationStatus.WARNING], counts[ValidationStatus.INVALID]
        )

    def validate(
        self,
        item: Transaction,
        period_start: date | None = None,
        period_end: date | None = None,
        require_ledgers: bool = False,
    ) -> tuple[ValidationStatus, str]:
        errors: list[str] = []
        warnings: list[str] = []
        if item.ignored:
            return ValidationStatus.WARNING, "Ignored by user"
        if item.transaction_date is None:
            errors.append("Invalid or missing date")
        elif (period_start and item.transaction_date < period_start) or (
            period_end and item.transaction_date > period_end
        ):
            warnings.append("Transaction is outside the selected period")
        if not item.debit_amount.is_finite() or not item.credit_amount.is_finite():
            errors.append("Amount is NaN or Infinity")
        elif item.debit_amount < 0 or item.credit_amount < 0:
            errors.append("Negative amount is in the wrong normalized column")
        if (
            item.debit_amount.is_finite()
            and item.credit_amount.is_finite()
            and item.debit_amount
            and item.credit_amount
        ):
            errors.append("Both debit and credit are entered")
        elif (
            item.debit_amount.is_finite()
            and item.credit_amount.is_finite()
            and not item.debit_amount
            and not item.credit_amount
        ):
            errors.append("Missing amount")
        if item.voucher_type == VoucherType.UNASSIGNED:
            errors.append("Missing voucher type")
        elif item.voucher_type == VoucherType.PAYMENT and not item.debit_amount:
            errors.append("Payment voucher must contain a debit/withdrawal")
        elif item.voucher_type == VoucherType.RECEIPT and not item.credit_amount:
            errors.append("Receipt voucher must contain a credit/deposit")
        if not item.description.strip():
            warnings.append("Missing description")
        if require_ledgers:
            if not item.bank_ledger.strip():
                errors.append("Missing bank ledger")
            elif is_numeric_ledger_reference(item.bank_ledger):
                errors.append("Bank ledger must be a Tally ledger name, not a numeric index")
            if not item.opposite_ledger.strip():
                errors.append("Missing opposite ledger")
            elif is_numeric_ledger_reference(item.opposite_ledger):
                errors.append("Opposite ledger must be a Tally ledger name, not a numeric index")
            elif item.opposite_ledger.strip().casefold() == item.bank_ledger.strip().casefold():
                errors.append("Bank and opposite ledgers cannot be the same")
        elif not item.opposite_ledger.strip():
            warnings.append("Opposite ledger is unmatched")
        if item.opposite_ledger.strip() and (
            item.matching_confidence == 0 or "suspense" in item.opposite_ledger.casefold()
        ):
            warnings.append("Unmatched ledger uses Suspense a/c")
        if item.duplicate_status == DuplicateStatus.SUSPECTED:
            warnings.append("Possible duplicate")
        elif item.duplicate_status == DuplicateStatus.CONFIRMED_DUPLICATE:
            warnings.append("Confirmed duplicate")
        if any(
            INVALID_XML_CHARACTERS.search(value) for value in (item.description, item.narration, item.reference_number)
        ):
            errors.append("Contains an invalid XML control character")
        if errors:
            return ValidationStatus.INVALID, "; ".join(errors + warnings)
        if warnings:
            return ValidationStatus.WARNING, "; ".join(warnings)
        return ValidationStatus.VALID, "Ready"

    @staticmethod
    def reconcile(
        transactions: list[Transaction],
        opening_balance: Decimal | None = None,
        statement_closing_balance: Decimal | None = None,
    ) -> ReconciliationResult:
        active = [item for item in transactions if not item.ignored]
        total_debit = sum((item.debit_amount for item in active), Decimal("0.00"))
        total_credit = sum((item.credit_amount for item in active), Decimal("0.00"))
        inferred_closing = statement_closing_balance
        if inferred_closing is None:
            balances = [item.balance for item in active if item.balance is not None]
            inferred_closing = balances[-1] if balances else None
        expected = opening_balance + total_credit - total_debit if opening_balance is not None else None
        difference = inferred_closing - expected if inferred_closing is not None and expected is not None else None
        return ReconciliationResult(opening_balance, total_debit, total_credit, expected, inferred_closing, difference)
