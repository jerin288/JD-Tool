"""Weighted, explainable duplicate transaction detection."""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from app.models.enums import DuplicateStatus
from app.models.transaction import Transaction


@dataclass(frozen=True, slots=True)
class DuplicateMatch:
    original_id: str
    duplicate_id: str
    score: int
    reasons: tuple[str, ...]


class DuplicateDetector:
    """Compare date, amount, direction, reference, narration, and balance."""

    def detect(self, transactions: list[Transaction], threshold: int = 75) -> list[DuplicateMatch]:
        threshold = max(40, min(100, threshold))
        for item in transactions:
            if item.duplicate_status == DuplicateStatus.SUSPECTED:
                item.duplicate_status = DuplicateStatus.NONE
                item.duplicate_of = ""
        matches: list[DuplicateMatch] = []
        active = [item for item in transactions if not item.ignored]
        for index, left in enumerate(active):
            for right in active[index + 1 :]:
                if right.duplicate_status == DuplicateStatus.CONFIRMED_UNIQUE:
                    continue
                score, reasons = self._score(left, right)
                if score >= threshold:
                    matches.append(DuplicateMatch(left.id, right.id, score, tuple(reasons)))
                    if right.duplicate_status != DuplicateStatus.CONFIRMED_DUPLICATE:
                        right.duplicate_status = DuplicateStatus.SUSPECTED
                        right.duplicate_of = left.id
        return matches

    @classmethod
    def _score(cls, left: Transaction, right: Transaction) -> tuple[int, list[str]]:
        score = 0
        reasons: list[str] = []
        if left.transaction_date and left.transaction_date == right.transaction_date:
            score += 30
            reasons.append("same date")
        left_direction = "D" if left.debit_amount else "C"
        right_direction = "D" if right.debit_amount else "C"
        if left.amount == right.amount and left.amount and left_direction == right_direction:
            score += 30
            reasons.append("same amount and direction")
        left_reference = cls._normalize(left.reference_number)
        right_reference = cls._normalize(right.reference_number)
        if left_reference and left_reference == right_reference:
            score += 20
            reasons.append("same reference")
        description_similarity = SequenceMatcher(
            None, cls._normalize(left.description), cls._normalize(right.description)
        ).ratio()
        if description_similarity >= 0.9:
            score += 15
            reasons.append("matching description")
        elif description_similarity >= 0.7:
            score += 10
            reasons.append("similar description")
        if left.balance is not None and left.balance == right.balance:
            score += 5
            reasons.append("same balance")
        return score, reasons

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
