"""Canonical Tally ledger-name handling shared by UI and business logic."""

from __future__ import annotations

from collections.abc import Iterable

LEGACY_LEDGER_LABEL = "Legacy rule needs ledger reassignment"


def normalize_ledger_name(value: object) -> str:
    """Normalize a ledger name for comparison without changing Tally spelling."""

    return " ".join(str(value).strip().casefold().split())


def is_numeric_ledger_reference(value: object) -> bool:
    """Return True for a leaked UI index/count such as ``169``."""

    text = str(value).strip()
    return bool(text) and text.isdecimal()


def canonical_ledger_name(selected: object, available_names: Iterable[str]) -> str:
    """Resolve a user selection to the exact spelling returned by Tally."""

    raw = str(selected).strip()
    if not raw or raw == LEGACY_LEDGER_LABEL:
        raise ValueError("Select a Tally ledger name.")
    if is_numeric_ledger_reference(raw):
        raise ValueError("A numeric ledger index is invalid. Select the actual Tally ledger name.")
    canonical = {
        normalize_ledger_name(name): name.strip()
        for name in available_names
        if name.strip() and not is_numeric_ledger_reference(name)
    }
    resolved = canonical.get(normalize_ledger_name(raw))
    if resolved is None:
        raise ValueError("The ledger is not present in the selected Tally company.")
    return resolved
