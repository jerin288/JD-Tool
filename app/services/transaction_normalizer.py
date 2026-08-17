"""Consistent debit/credit normalization for heterogeneous bank layouts."""

from __future__ import annotations

import re
from decimal import Decimal

from app.utils.amounts import parse_decimal


class TransactionNormalizer:
    """Normalize split or single-column amounts without losing decimal precision."""

    @staticmethod
    def normalize(
        debit_raw: str = "",
        credit_raw: str = "",
        amount_raw: str = "",
        direction_raw: str = "",
    ) -> tuple[Decimal, Decimal]:
        debit = parse_decimal(debit_raw)
        credit = parse_decimal(credit_raw)
        if debit or credit:
            debit, credit = abs(debit), abs(credit)
        elif amount_raw.strip():
            amount = parse_decimal(amount_raw)
            embedded = re.search(r"(DR|CR)\s*$", amount_raw.upper().replace(".", ""))
            direction = (direction_raw or (embedded.group(1) if embedded else "")).upper().replace(".", "").strip()
            explicit_sign = re.match(r"\s*(?:[^0-9+\-]*\s*)?([+\-])", amount_raw)
            sign = explicit_sign.group(1) if explicit_sign else ""
            if direction.startswith("D") or amount < 0 or sign == "-":
                debit = abs(amount)
            elif direction.startswith("C") or sign == "+":
                credit = abs(amount)
            else:
                raise ValueError("amount direction is neither DR nor CR")
        if debit and credit:
            raise ValueError("both debit and credit have values")
        if not debit and not credit:
            raise ValueError("transaction has no amount")
        return debit, credit
