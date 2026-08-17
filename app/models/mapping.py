"""Column mapping configuration for parsed statement rows."""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any


@dataclass(slots=True)
class ColumnMapping:
    """Maps normalized transaction fields to zero-based source column indexes."""

    transaction_date: int | None = None
    value_date: int | None = None
    description: int | None = None
    reference_number: int | None = None
    cheque_number: int | None = None
    debit: int | None = None
    credit: int | None = None
    amount: int | None = None
    dr_cr: int | None = None
    balance: int | None = None
    header_row: int = 0
    date_format: str = "AUTO"

    COLUMN_FIELDS = (
        "transaction_date",
        "value_date",
        "description",
        "reference_number",
        "cheque_number",
        "debit",
        "credit",
        "amount",
        "dr_cr",
        "balance",
    )

    def validate(self) -> list[str]:
        """Return user-facing mapping problems."""
        errors: list[str] = []
        if self.transaction_date is None:
            errors.append("Transaction Date must be mapped.")
        if self.description is None:
            errors.append("Description must be mapped.")
        has_split_amount = self.debit is not None or self.credit is not None
        if not has_split_amount and self.amount is None:
            errors.append("Map Debit/Credit columns or a single Amount column.")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return {field.name: getattr(self, field.name) for field in fields(self)}

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> ColumnMapping:
        known = {field.name for field in fields(cls)}
        return cls(**{key: value for key, value in values.items() if key in known})
