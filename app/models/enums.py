"""Enumerations used by transaction records."""

from __future__ import annotations

from enum import StrEnum


class VoucherType(StrEnum):
    PAYMENT = "Payment"
    RECEIPT = "Receipt"
    CONTRA = "Contra"
    UNASSIGNED = "Unassigned"


class ImportStatus(StrEnum):
    NOT_EXPORTED = "Not exported"
    EXPORTED = "Exported"
    IMPORTED = "Imported"
    FAILED = "Failed"


class ValidationStatus(StrEnum):
    UNCHECKED = "Unchecked"
    VALID = "Valid"
    WARNING = "Warning"
    INVALID = "Invalid"


class DuplicateStatus(StrEnum):
    NONE = "None"
    SUSPECTED = "Suspected"
    CONFIRMED_DUPLICATE = "Confirmed duplicate"
    CONFIRMED_UNIQUE = "Confirmed unique"


class RuleMatchType(StrEnum):
    CONTAINS = "Contains"
    EXACT = "Exact"
    STARTS_WITH = "Starts with"
    REGEX = "Regular expression"
