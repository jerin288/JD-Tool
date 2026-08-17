"""Safe parsing and formatting helpers for monetary values."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

EMPTY_MARKERS = {"", "-", "--", "na", "n/a", "nil", "none"}


def parse_decimal(value: object) -> Decimal:
    """Parse a bank-formatted amount without ever converting through float."""
    if value is None:
        return Decimal("0.00")
    raw = str(value).strip()
    if raw.lower() in EMPTY_MARKERS:
        return Decimal("0.00")
    if any(token in raw.lower() for token in ("nan", "infinity", "inf")):
        raise ValueError(f"Invalid amount: {raw}")
    negative = raw.startswith("(") and raw.endswith(")")
    normalized = re.sub(r"[^0-9.\-]", "", raw.replace(",", ""))
    if normalized in {"", "-", ".", "-."}:
        return Decimal("0.00")
    try:
        amount = Decimal(normalized)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid amount: {raw}") from exc
    if negative:
        amount = -abs(amount)
    if not amount.is_finite():
        raise ValueError(f"Invalid amount: {raw}")
    return amount.quantize(Decimal("0.01"))


def format_decimal(value: Decimal | None) -> str:
    return "" if value is None else f"{value:.2f}"
