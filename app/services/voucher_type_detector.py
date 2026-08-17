"""Conservative bank voucher-type classification."""

from __future__ import annotations

from app.models.enums import VoucherType
from app.models.tally import TallyLedger
from app.models.transaction import Transaction


class VoucherTypeDetector:
    """Classify payments and receipts, using Contra only for own cash/bank transfers."""

    BANK_CHARGE_TERMS = ("bank charge", "service charge", "sms charge", "annual fee", "commission")
    INTEREST_RECEIVED_TERMS = ("interest credit", "interest received", "int paid", "credit interest")
    INTEREST_CHARGED_TERMS = ("interest charged", "debit interest", "loan interest", "od interest")

    def detect(
        self,
        transaction: Transaction,
        opposite_ledger: TallyLedger | None = None,
        bank_ledger: TallyLedger | None = None,
    ) -> VoucherType:
        description = transaction.description.lower()
        if any(term in description for term in self.BANK_CHARGE_TERMS):
            return VoucherType.PAYMENT
        if any(term in description for term in self.INTEREST_RECEIVED_TERMS):
            return VoucherType.RECEIPT
        if any(term in description for term in self.INTEREST_CHARGED_TERMS):
            return VoucherType.PAYMENT
        if opposite_ledger and opposite_ledger.is_bank_or_cash:
            if bank_ledger is None or bank_ledger.is_bank_or_cash:
                return VoucherType.CONTRA
        return VoucherType.PAYMENT if transaction.debit_amount else VoucherType.RECEIPT
