"""Transaction domain model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from app.models.enums import DuplicateStatus, ImportStatus, ValidationStatus, VoucherType

ZERO = Decimal("0.00")


@dataclass(slots=True)
class Transaction:
    """A normalized bank statement transaction using exact decimal amounts."""

    transaction_date: date | None
    description: str
    value_date: date | None = None
    reference_number: str = ""
    cheque_number: str = ""
    debit_amount: Decimal = ZERO
    credit_amount: Decimal = ZERO
    balance: Decimal | None = None
    voucher_type: VoucherType = VoucherType.UNASSIGNED
    bank_ledger: str = ""
    opposite_ledger: str = ""
    narration: str = ""
    tally_voucher_number: str = ""
    matching_confidence: Decimal = ZERO
    matching_method: str = ""
    matching_rule_id: str = ""
    import_status: ImportStatus = ImportStatus.NOT_EXPORTED
    import_message: str = ""
    imported_at: datetime | None = None
    validation_status: ValidationStatus = ValidationStatus.UNCHECKED
    validation_message: str = ""
    duplicate_status: DuplicateStatus = DuplicateStatus.NONE
    duplicate_of: str = ""
    ignored: bool = False
    row_number: int = 0
    id: str = field(default_factory=lambda: str(uuid4()))
    session_id: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    @property
    def amount(self) -> Decimal:
        """Return the non-zero debit or credit magnitude."""
        return self.debit_amount if self.debit_amount else self.credit_amount

    def clone(self) -> Transaction:
        """Create a new record with copied business values."""
        return Transaction(
            transaction_date=self.transaction_date,
            value_date=self.value_date,
            description=self.description,
            reference_number=self.reference_number,
            cheque_number=self.cheque_number,
            debit_amount=self.debit_amount,
            credit_amount=self.credit_amount,
            balance=self.balance,
            voucher_type=self.voucher_type,
            bank_ledger=self.bank_ledger,
            opposite_ledger=self.opposite_ledger,
            narration=self.narration,
            tally_voucher_number=self.tally_voucher_number,
            matching_confidence=self.matching_confidence,
            matching_method=self.matching_method,
            matching_rule_id=self.matching_rule_id,
            import_status=self.import_status,
            import_message=self.import_message,
            imported_at=self.imported_at,
            validation_status=self.validation_status,
            validation_message=self.validation_message,
            duplicate_status=self.duplicate_status,
            duplicate_of=self.duplicate_of,
            ignored=self.ignored,
            row_number=self.row_number,
            session_id=self.session_id,
        )
