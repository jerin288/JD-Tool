"""Ordered Tally ledger matching with saved rules and confidence scores."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from difflib import SequenceMatcher

from app.models.enums import RuleMatchType, VoucherType
from app.models.matching_rule import MatchingRule
from app.models.tally import TallyLedger
from app.models.transaction import Transaction
from app.services.voucher_type_detector import VoucherTypeDetector


@dataclass(frozen=True, slots=True)
class LedgerMatch:
    ledger_name: str
    confidence: Decimal
    method: str
    rule_id: str = ""
    voucher_type_override: VoucherType = VoucherType.UNASSIGNED


class LedgerMatcher:
    """Match in the required rule → exact → keyword → substring → normalized → fuzzy order."""

    NOISE_PATTERNS = (
        r"\b(?:upi|neft|imps|rtgs|ach|ecs|pos|atm|txn|trf|transfer)\b",
        r"\b[a-z0-9._%+-]+@[a-z0-9.-]+\b",
        r"\b(?:utr|rrn|ref|chq|cheque)\s*[:#-]?\s*[a-z0-9-]+\b",
        r"\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b",
        r"\b\d{7,}\b",
        r"[^a-z0-9& ]+",
    )
    STOP_WORDS = {"account", "limited", "ltd", "private", "pvt", "payment", "receipt", "bank"}

    def __init__(self, voucher_detector: VoucherTypeDetector | None = None) -> None:
        self.voucher_detector = voucher_detector or VoucherTypeDetector()

    def match(
        self,
        transaction: Transaction,
        ledgers: list[TallyLedger],
        rules: list[MatchingRule],
        fuzzy_threshold: int = 78,
        suspense_ledger: str = "Suspense A/c",
    ) -> LedgerMatch:
        ledger_by_basic = {self.basic_normalize(item.name): item for item in ledgers}
        for rule in sorted((item for item in rules if item.enabled), key=lambda item: item.priority):
            if self._rule_matches(rule, transaction.description):
                target = ledger_by_basic.get(self.basic_normalize(rule.ledger_name))
                if target:
                    return LedgerMatch(target.name, Decimal("100"), "Saved Rule", rule.id, rule.voucher_type)

        basic_description = self.basic_normalize(transaction.description)
        if basic_description in ledger_by_basic:
            return LedgerMatch(ledger_by_basic[basic_description].name, Decimal("100"), "Exact ledger name")

        keyword_candidates: list[tuple[int, TallyLedger]] = []
        for ledger in ledgers:
            tokens = self._meaningful_tokens(self.basic_normalize(ledger.name))
            if tokens and all(re.search(rf"\b{re.escape(token)}\b", basic_description) for token in tokens):
                keyword_candidates.append((sum(len(token) for token in tokens), ledger))
        if keyword_candidates:
            ledger = max(keyword_candidates, key=lambda item: item[0])[1]
            return LedgerMatch(ledger.name, Decimal("94"), "Keyword")

        substrings = [
            ledger for ledger in ledgers
            if len(self.basic_normalize(ledger.name)) >= 4
            and self.basic_normalize(ledger.name) in basic_description
        ]
        if substrings:
            ledger = max(substrings, key=lambda item: len(self.basic_normalize(item.name)))
            return LedgerMatch(ledger.name, Decimal("88"), "Substring")

        description = self.normalize(transaction.description)
        compact_description = description.replace(" ", "")
        normalized_matches = [
            ledger for ledger in ledgers
            if self.normalize(ledger.name).replace(" ", "") == compact_description
        ]
        if normalized_matches:
            return LedgerMatch(normalized_matches[0].name, Decimal("84"), "Normalized text")

        best_ledger: TallyLedger | None = None
        best_score = 0
        for ledger in ledgers:
            score = round(SequenceMatcher(None, description, self.normalize(ledger.name)).ratio() * 100)
            if score > best_score:
                best_ledger, best_score = ledger, score
        if best_ledger and best_score >= max(1, min(100, fuzzy_threshold)):
            return LedgerMatch(best_ledger.name, Decimal(best_score), "Fuzzy")

        suspense = ledger_by_basic.get(self.basic_normalize(suspense_ledger))
        return LedgerMatch(suspense.name if suspense else suspense_ledger, Decimal("0"), "Default suspense")

    def apply(
        self,
        transactions: list[Transaction],
        ledgers: list[TallyLedger],
        rules: list[MatchingRule],
        bank_ledger_name: str,
        fuzzy_threshold: int = 78,
        suspense_ledger: str = "Suspense A/c",
    ) -> dict[str, int]:
        ledger_lookup = {item.name.lower(): item for item in ledgers}
        bank_ledger = ledger_lookup.get(bank_ledger_name.lower())
        counts = {"matched": 0, "suspense": 0, "rules": 0}
        for item in transactions:
            if item.ignored:
                continue
            result = self.match(item, ledgers, rules, fuzzy_threshold, suspense_ledger)
            item.bank_ledger = bank_ledger_name
            item.opposite_ledger = result.ledger_name
            item.matching_confidence = result.confidence
            item.matching_method = result.method
            item.matching_rule_id = result.rule_id
            opposite = ledger_lookup.get(result.ledger_name.lower())
            item.voucher_type = (
                result.voucher_type_override
                if result.voucher_type_override != VoucherType.UNASSIGNED
                else self.voucher_detector.detect(item, opposite, bank_ledger)
            )
            if result.method == "Default suspense":
                counts["suspense"] += 1
            else:
                counts["matched"] += 1
            if result.rule_id:
                counts["rules"] += 1
        return counts

    @classmethod
    def normalize(cls, value: str) -> str:
        normalized = value.lower()
        for pattern in cls.NOISE_PATTERNS:
            normalized = re.sub(pattern, " ", normalized, flags=re.IGNORECASE)
        return re.sub(r"\s+", " ", normalized).strip()

    @staticmethod
    def basic_normalize(value: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9&]+", " ", value.lower())).strip()

    @classmethod
    def _meaningful_tokens(cls, value: str) -> list[str]:
        return [token for token in value.split() if len(token) >= 3 and token not in cls.STOP_WORDS]

    @classmethod
    def _rule_matches(cls, rule: MatchingRule, description: str) -> bool:
        source = re.sub(r"\s+", " ", description).strip()
        pattern = rule.pattern.strip()
        if rule.match_type == RuleMatchType.EXACT:
            return source.casefold() == pattern.casefold()
        if rule.match_type == RuleMatchType.STARTS_WITH:
            return source.casefold().startswith(pattern.casefold())
        if rule.match_type == RuleMatchType.REGEX:
            try:
                return re.search(pattern, source, flags=re.IGNORECASE) is not None
            except re.error:
                return False
        return pattern.casefold() in source.casefold()
