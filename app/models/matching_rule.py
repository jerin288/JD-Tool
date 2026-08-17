"""Saved description-to-ledger rule model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4

from app.models.enums import RuleMatchType, VoucherType
from app.utils.ledger_names import is_numeric_ledger_reference


@dataclass(slots=True)
class MatchingRule:
    """A reusable rule applied before automatic ledger-name matching."""

    pattern: str
    ledger_name: str
    match_type: RuleMatchType = RuleMatchType.CONTAINS
    voucher_type: VoucherType = VoucherType.UNASSIGNED
    priority: int = 100
    enabled: bool = True
    use_count: int = 0
    legacy_ledger_reference: str = ""
    id: str = field(default_factory=lambda: str(uuid4()))
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.pattern.strip():
            errors.append("Rule pattern is required.")
        if not self.ledger_name.strip():
            errors.append("Ledger name is required.")
        elif is_numeric_ledger_reference(self.ledger_name):
            errors.append("Ledger must be an actual Tally ledger name, not a numeric index.")
        if not 0 <= self.priority <= 9999:
            errors.append("Priority must be between 0 and 9999.")
        return errors
