import unittest
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from app.database.manager import DatabaseManager
from app.models.enums import DuplicateStatus
from app.models.transaction import Transaction
from app.repositories.transaction_repository import TransactionRepository


class RepositoryTests(unittest.TestCase):
    def test_transaction_round_trip_and_update(self) -> None:
        with TemporaryDirectory() as directory:
            temporary_path = Path(directory)
            database = DatabaseManager(temporary_path / "test.db")
            database.initialize()
            repository = TransactionRepository(database)
            session_id = repository.create_session(temporary_path / "sample.pdf", "Automatic")
            original = Transaction(
                session_id=session_id, row_number=2, transaction_date=date(2026, 7, 1),
                description="Sample payment", debit_amount=Decimal("42.15"), balance=Decimal("1000.00"),
                matching_confidence=Decimal("94"), matching_method="Keyword",
                import_message="Previous error", imported_at=datetime(2026, 8, 7, 10, 30),
            )
            repository.save(original)
            loaded = repository.list_for_session(session_id)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].debit_amount, Decimal("42.15"))
            self.assertEqual(loaded[0].balance, Decimal("1000.00"))
            self.assertEqual(loaded[0].duplicate_status, DuplicateStatus.NONE)
            self.assertEqual(loaded[0].matching_confidence, Decimal("94"))
            self.assertEqual(loaded[0].matching_method, "Keyword")
            self.assertEqual(loaded[0].import_message, "Previous error")
            self.assertEqual(loaded[0].imported_at, datetime(2026, 8, 7, 10, 30))
            loaded[0].description = "Corrected payment"
            repository.save(loaded[0])
            self.assertEqual(repository.list_for_session(session_id)[0].description, "Corrected payment")

    def test_delete_transaction(self) -> None:
        with TemporaryDirectory() as directory:
            temporary_path = Path(directory)
            database = DatabaseManager(temporary_path / "test.db")
            database.initialize()
            repository = TransactionRepository(database)
            session_id = repository.create_session(temporary_path / "sample.pdf", "Automatic")
            item = Transaction(session_id=session_id, transaction_date=date.today(), description="Test", debit_amount=Decimal("1"))
            repository.save(item)
            repository.delete(item.id)
            self.assertEqual(repository.list_for_session(session_id), [])


if __name__ == "__main__":
    unittest.main()
