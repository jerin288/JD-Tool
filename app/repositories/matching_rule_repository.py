"""SQLite repository for reusable ledger matching rules."""

from __future__ import annotations

from datetime import datetime

from app.database.manager import DatabaseManager
from app.models.enums import RuleMatchType, VoucherType
from app.models.matching_rule import MatchingRule


class MatchingRuleRepository:
    """Persist ordered matching rules transactionally."""

    def __init__(self, database: DatabaseManager) -> None:
        self.database = database

    def list_enabled(self) -> list[MatchingRule]:
        return self.list_all(enabled_only=True)

    def list_all(self, enabled_only: bool = False) -> list[MatchingRule]:
        where = "WHERE enabled = 1" if enabled_only else ""
        with self.database.connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM matching_rules {where} ORDER BY priority, created_at"  # noqa: S608
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def save(self, rule: MatchingRule) -> None:
        errors = rule.validate()
        if errors:
            raise ValueError(" ".join(errors))
        rule.updated_at = datetime.now()
        with self.database.connection() as connection:
            connection.execute(
                """
                INSERT INTO matching_rules (
                    id, pattern, match_type, ledger_name, voucher_type, priority,
                    enabled, use_count, legacy_ledger_reference, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    pattern=excluded.pattern, match_type=excluded.match_type,
                    ledger_name=excluded.ledger_name, voucher_type=excluded.voucher_type,
                    priority=excluded.priority, enabled=excluded.enabled,
                    use_count=excluded.use_count,
                    legacy_ledger_reference=excluded.legacy_ledger_reference,
                    updated_at=excluded.updated_at
                """,
                (
                    rule.id, rule.pattern.strip(), rule.match_type.value, rule.ledger_name.strip(),
                    rule.voucher_type.value, rule.priority, int(rule.enabled), rule.use_count,
                    rule.legacy_ledger_reference, rule.created_at.isoformat(), rule.updated_at.isoformat(),
                ),
            )

    def delete(self, rule_id: str) -> None:
        with self.database.connection() as connection:
            connection.execute("DELETE FROM matching_rules WHERE id = ?", (rule_id,))

    def increment_use(self, rule_id: str, count: int = 1) -> None:
        with self.database.connection() as connection:
            connection.execute(
                "UPDATE matching_rules SET use_count = use_count + ?, updated_at = ? WHERE id = ?",
                (max(1, count), datetime.now().isoformat(), rule_id),
            )

    @staticmethod
    def _from_row(row: object) -> MatchingRule:
        return MatchingRule(
            id=row["id"], pattern=row["pattern"], match_type=RuleMatchType(row["match_type"]),
            ledger_name=row["ledger_name"], voucher_type=VoucherType(row["voucher_type"]),
            priority=row["priority"], enabled=bool(row["enabled"]), use_count=row["use_count"],
            legacy_ledger_reference=row["legacy_ledger_reference"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
