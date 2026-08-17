"""SQLite connection and migration management."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = 5


class DatabaseManager:
    """Creates short-lived SQLite connections and applies idempotent migrations."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        database_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_info (
                    version INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS import_sessions (
                    id TEXT PRIMARY KEY,
                    source_filename TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    bank_name TEXT NOT NULL DEFAULT 'Automatic',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS transactions (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    row_number INTEGER NOT NULL DEFAULT 0,
                    transaction_date TEXT,
                    value_date TEXT,
                    description TEXT NOT NULL,
                    reference_number TEXT NOT NULL DEFAULT '',
                    cheque_number TEXT NOT NULL DEFAULT '',
                    debit_amount TEXT NOT NULL DEFAULT '0.00',
                    credit_amount TEXT NOT NULL DEFAULT '0.00',
                    balance TEXT,
                    voucher_type TEXT NOT NULL DEFAULT 'Unassigned',
                    bank_ledger TEXT NOT NULL DEFAULT '',
                    opposite_ledger TEXT NOT NULL DEFAULT '',
                    narration TEXT NOT NULL DEFAULT '',
                    tally_voucher_number TEXT NOT NULL DEFAULT '',
                    matching_confidence TEXT NOT NULL DEFAULT '0.00',
                    matching_method TEXT NOT NULL DEFAULT '',
                    matching_rule_id TEXT NOT NULL DEFAULT '',
                    import_status TEXT NOT NULL DEFAULT 'Not exported',
                    import_message TEXT NOT NULL DEFAULT '',
                    imported_at TEXT,
                    validation_status TEXT NOT NULL DEFAULT 'Unchecked',
                    validation_message TEXT NOT NULL DEFAULT '',
                    duplicate_status TEXT NOT NULL DEFAULT 'None',
                    duplicate_of TEXT NOT NULL DEFAULT '',
                    ignored INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES import_sessions(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_transactions_session
                    ON transactions(session_id, row_number);

                CREATE TABLE IF NOT EXISTS matching_rules (
                    id TEXT PRIMARY KEY,
                    pattern TEXT NOT NULL,
                    match_type TEXT NOT NULL DEFAULT 'Contains',
                    ledger_name TEXT NOT NULL,
                    voucher_type TEXT NOT NULL DEFAULT 'Unassigned',
                    priority INTEGER NOT NULL DEFAULT 100,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    use_count INTEGER NOT NULL DEFAULT 0,
                    legacy_ledger_reference TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_matching_rules_priority
                    ON matching_rules(enabled, priority, pattern);

                CREATE TABLE IF NOT EXISTS import_history (
                    id TEXT PRIMARY KEY,
                    company_name TEXT NOT NULL,
                    total_vouchers INTEGER NOT NULL DEFAULT 0,
                    created INTEGER NOT NULL DEFAULT 0,
                    altered INTEGER NOT NULL DEFAULT 0,
                    ignored INTEGER NOT NULL DEFAULT 0,
                    errors INTEGER NOT NULL DEFAULT 0,
                    failed INTEGER NOT NULL DEFAULT 0,
                    messages_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL
                );
                """
            )
            row = connection.execute("SELECT version FROM schema_info LIMIT 1").fetchone()
            if row is None:
                connection.execute("INSERT INTO schema_info(version) VALUES (?)", (SCHEMA_VERSION,))
            elif row["version"] == 1:
                existing_columns = {
                    column["name"] for column in connection.execute("PRAGMA table_info(transactions)").fetchall()
                }
                if "duplicate_status" not in existing_columns:
                    connection.execute(
                        "ALTER TABLE transactions ADD COLUMN duplicate_status TEXT NOT NULL DEFAULT 'None'"
                    )
                if "duplicate_of" not in existing_columns:
                    connection.execute(
                        "ALTER TABLE transactions ADD COLUMN duplicate_of TEXT NOT NULL DEFAULT ''"
                    )
                if "matching_method" not in existing_columns:
                    connection.execute(
                        "ALTER TABLE transactions ADD COLUMN matching_method TEXT NOT NULL DEFAULT ''"
                    )
                if "matching_rule_id" not in existing_columns:
                    connection.execute(
                        "ALTER TABLE transactions ADD COLUMN matching_rule_id TEXT NOT NULL DEFAULT ''"
                    )
                if "import_message" not in existing_columns:
                    connection.execute(
                        "ALTER TABLE transactions ADD COLUMN import_message TEXT NOT NULL DEFAULT ''"
                    )
                if "imported_at" not in existing_columns:
                    connection.execute("ALTER TABLE transactions ADD COLUMN imported_at TEXT")
                connection.execute("UPDATE schema_info SET version = ?", (SCHEMA_VERSION,))
            elif row["version"] == 2:
                existing_columns = {
                    column["name"] for column in connection.execute("PRAGMA table_info(transactions)").fetchall()
                }
                if "matching_method" not in existing_columns:
                    connection.execute(
                        "ALTER TABLE transactions ADD COLUMN matching_method TEXT NOT NULL DEFAULT ''"
                    )
                if "matching_rule_id" not in existing_columns:
                    connection.execute(
                        "ALTER TABLE transactions ADD COLUMN matching_rule_id TEXT NOT NULL DEFAULT ''"
                    )
                if "import_message" not in existing_columns:
                    connection.execute(
                        "ALTER TABLE transactions ADD COLUMN import_message TEXT NOT NULL DEFAULT ''"
                    )
                if "imported_at" not in existing_columns:
                    connection.execute("ALTER TABLE transactions ADD COLUMN imported_at TEXT")
                connection.execute("UPDATE schema_info SET version = ?", (SCHEMA_VERSION,))
            elif row["version"] == 3:
                existing_columns = {
                    column["name"] for column in connection.execute("PRAGMA table_info(transactions)").fetchall()
                }
                if "import_message" not in existing_columns:
                    connection.execute(
                        "ALTER TABLE transactions ADD COLUMN import_message TEXT NOT NULL DEFAULT ''"
                    )
                if "imported_at" not in existing_columns:
                    connection.execute("ALTER TABLE transactions ADD COLUMN imported_at TEXT")
                connection.execute("UPDATE schema_info SET version = ?", (SCHEMA_VERSION,))
            elif row["version"] == 4:
                self._migrate_legacy_ledger_references(connection)
                connection.execute("UPDATE schema_info SET version = ?", (SCHEMA_VERSION,))
            elif row["version"] != SCHEMA_VERSION:
                raise RuntimeError(
                    f"Database schema {row['version']} is unsupported; expected {SCHEMA_VERSION}."
                )

            # New databases and older upgrade paths also pass through this
            # idempotent repair so leaked numeric UI indices can never remain
            # active business data.
            self._migrate_legacy_ledger_references(connection)

    @staticmethod
    def _migrate_legacy_ledger_references(connection: sqlite3.Connection) -> None:
        """Preserve numeric legacy references separately and require reassignment."""

        rule_columns = {
            column["name"] for column in connection.execute("PRAGMA table_info(matching_rules)").fetchall()
        }
        if "legacy_ledger_reference" not in rule_columns:
            connection.execute(
                "ALTER TABLE matching_rules ADD COLUMN legacy_ledger_reference TEXT NOT NULL DEFAULT ''"
            )
        transaction_columns = {
            column["name"] for column in connection.execute("PRAGMA table_info(transactions)").fetchall()
        }
        if "legacy_opposite_ledger_reference" not in transaction_columns:
            connection.execute(
                "ALTER TABLE transactions ADD COLUMN legacy_opposite_ledger_reference TEXT NOT NULL DEFAULT ''"
            )
        numeric_ledger = "TRIM({column}) <> '' AND TRIM({column}) NOT GLOB '*[^0-9]*'"
        connection.execute(
            f"""
            UPDATE matching_rules
               SET legacy_ledger_reference = TRIM(ledger_name),
                   ledger_name = '',
                   updated_at = CURRENT_TIMESTAMP
             WHERE {numeric_ledger.format(column='ledger_name')}
            """
        )
        connection.execute(
            f"""
            UPDATE transactions
               SET legacy_opposite_ledger_reference = TRIM(opposite_ledger),
                   opposite_ledger = '',
                   matching_confidence = '0.00',
                   matching_method = 'Legacy rule needs ledger reassignment',
                   validation_status = 'Unchecked',
                   validation_message = 'Legacy ledger reference needs reassignment',
                   updated_at = CURRENT_TIMESTAMP
             WHERE {numeric_ledger.format(column='opposite_ledger')}
            """
        )
