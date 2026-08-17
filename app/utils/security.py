"""Privacy helpers used before displaying or logging sensitive identifiers."""

from __future__ import annotations

import re

ACCOUNT_NUMBER_PATTERN = re.compile(r"(?<!\d)(\d{8,18})(?!\d)")
UPI_PATTERN = re.compile(r"(?i)\b([a-z0-9._-]{2,})@([a-z][a-z0-9.-]{1,})\b")


def mask_account_numbers(text: str) -> str:
    """Mask plausible bank-account numbers while preserving the last four digits."""
    return ACCOUNT_NUMBER_PATTERN.sub(lambda match: "•" * (len(match.group()) - 4) + match.group()[-4:], text)


def redact_sensitive_data(text: str) -> str:
    """Mask account-like identifiers and UPI addresses before writing logs."""
    masked = mask_account_numbers(text)
    return UPI_PATTERN.sub(lambda match: f"{match.group(1)[:2]}***@{match.group(2)}", masked)
