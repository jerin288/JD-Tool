"""Transaction and import-session persistence."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from app.database.manager import DatabaseManager
from app.models.enums import DuplicateStatus, ImportStatus, ValidationStatus, VoucherType
from app.models.transaction import Transaction


class TransactionRepository:
    """Persists imports atomically and supports automatic row saves."""

    def __init__(self, database: DatabaseManager) -> None:
        self.database = database

    def create_session(self, source_path: Path, bank_name: str) -> str:
        session_id = str(uuid4())
        with self.database.connection() as connection:
            connection.execute(
                """INSERT INTO import_sessions(id, source_filename, source_path, bank_name)
                   VALUES (?, ?, ?, ?)""",
                (session_id, source_path.name, str(source_path), bank_name),
            )
        return session_id

    def save_many(self, transactions: list[Transaction]) -> None:
        if not transactions:
            return
        with self.database.connection() as connection:
            connection.executemany(self._upsert_sql(), [self._to_row(item) for item in transactions])

    def save(self, transaction: Transaction) -> None:
        transaction.updated_at = datetime.now()
        with self.database.connection() as connection:
            connection.execute(self._upsert_sql(), self._to_row(transaction))

    def delete(self, transaction_id: str) -> None:
        with self.database.connection() as connection:
            connection.execute("DELETE FROM transactions WHERE id = ?", (transaction_id,))

    def delete_many(self, transaction_ids: list[str]) -> None:
        if not transaction_ids:
            return
        with self.database.connection() as connection:
            connection.executemany("DELETE FROM transactions WHERE id = ?", ((item,) for item in transaction_ids))

    def list_for_session(self, session_id: str) -> list[Transaction]:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM transactions WHERE session_id = ? ORDER BY row_number, created_at",
                (session_id,),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    @staticmethod
    def _upsert_sql() -> str:
        return """
            INSERT INTO transactions (
                id, session_id, row_number, transaction_date, value_date, description,
                reference_number, cheque_number, debit_amount, credit_amount, balance,
                voucher_type, bank_ledger, opposite_ledger, narration, tally_voucher_number,
                matching_confidence, matching_method, matching_rule_id,
                import_status, import_message, imported_at, validation_status, validation_message,
                duplicate_status, duplicate_of, ignored, created_at, updated_at
            ) VALUES (
                :id, :session_id, :row_number, :transaction_date, :value_date, :description,
                :reference_number, :cheque_number, :debit_amount, :credit_amount, :balance,
                :voucher_type, :bank_ledger, :opposite_ledger, :narration, :tally_voucher_number,
                :matching_confidence, :matching_method, :matching_rule_id,
                :import_status, :import_message, :imported_at, :validation_status, :validation_message,
                :duplicate_status, :duplicate_of, :ignored, :created_at, :updated_at
            ) ON CONFLICT(id) DO UPDATE SET
                row_number=excluded.row_number, transaction_date=excluded.transaction_date,
                value_date=excluded.value_date, description=excluded.description,
                reference_number=excluded.reference_number, cheque_number=excluded.cheque_number,
                debit_amount=excluded.debit_amount, credit_amount=excluded.credit_amount,
                balance=excluded.balance, voucher_type=excluded.voucher_type,
                bank_ledger=excluded.bank_ledger, opposite_ledger=excluded.opposite_ledger,
                narration=excluded.narration, validation_status=excluded.validation_status,
                validation_message=excluded.validation_message, ignored=excluded.ignored,
                matching_confidence=excluded.matching_confidence,
                matching_method=excluded.matching_method, matching_rule_id=excluded.matching_rule_id,
                import_status=excluded.import_status, import_message=excluded.import_message,
                imported_at=excluded.imported_at,
                duplicate_status=excluded.duplicate_status, duplicate_of=excluded.duplicate_of,
                updated_at=excluded.updated_at
        """

    @staticmethod
    def _to_row(item: Transaction) -> dict[str, object]:
        return {
            "id": item.id,
            "session_id": item.session_id,
            "row_number": item.row_number,
            "transaction_date": item.transaction_date.isoformat() if item.transaction_date else None,
            "value_date": item.value_date.isoformat() if item.value_date else None,
            "description": item.description,
            "reference_number": item.reference_number,
            "cheque_number": item.cheque_number,
            "debit_amount": str(item.debit_amount),
            "credit_amount": str(item.credit_amount),
            "balance": str(item.balance) if item.balance is not None else None,
            "voucher_type": item.voucher_type.value,
            "bank_ledger": item.bank_ledger,
            "opposite_ledger": item.opposite_ledger,
            "narration": item.narration,
            "tally_voucher_number": item.tally_voucher_number,
            "matching_confidence": str(item.matching_confidence),
            "matching_method": item.matching_method,
            "matching_rule_id": item.matching_rule_id,
            "import_status": item.import_status.value,
            "import_message": item.import_message,
            "imported_at": item.imported_at.isoformat() if item.imported_at else None,
            "validation_status": item.validation_status.value,
            "validation_message": item.validation_message,
            "duplicate_status": item.duplicate_status.value,
            "duplicate_of": item.duplicate_of,
            "ignored": int(item.ignored),
            "created_at": item.created_at.isoformat(),
            "updated_at": item.updated_at.isoformat(),
        }

    @staticmethod
    def _from_row(row: object) -> Transaction:
        return Transaction(
            id=row["id"], session_id=row["session_id"], row_number=row["row_number"],
            transaction_date=date.fromisoformat(row["transaction_date"]) if row["transaction_date"] else None,
            value_date=date.fromisoformat(row["value_date"]) if row["value_date"] else None,
            description=row["description"], reference_number=row["reference_number"],
            cheque_number=row["cheque_number"], debit_amount=Decimal(row["debit_amount"]),
            credit_amount=Decimal(row["credit_amount"]),
            balance=Decimal(row["balance"]) if row["balance"] is not None else None,
            voucher_type=VoucherType(row["voucher_type"]), bank_ledger=row["bank_ledger"],
            opposite_ledger=row["opposite_ledger"], narration=row["narration"],
            tally_voucher_number=row["tally_voucher_number"],
            matching_confidence=Decimal(row["matching_confidence"]),
            matching_method=row["matching_method"], matching_rule_id=row["matching_rule_id"],
            import_status=ImportStatus(row["import_status"]),
            import_message=row["import_message"],
            imported_at=datetime.fromisoformat(row["imported_at"]) if row["imported_at"] else None,
            validation_status=ValidationStatus(row["validation_status"]),
            validation_message=row["validation_message"], ignored=bool(row["ignored"]),
            duplicate_status=DuplicateStatus(row["duplicate_status"]), duplicate_of=row["duplicate_of"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
