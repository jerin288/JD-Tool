"""Persistence for direct Tally import summaries."""

from __future__ import annotations

import json
from datetime import datetime

from app.database.manager import DatabaseManager
from app.models.export import ImportBatch


class ImportHistoryRepository:
    def __init__(self, database: DatabaseManager) -> None:
        self.database = database

    def save(self, batch: ImportBatch) -> None:
        with self.database.connection() as connection:
            connection.execute(
                """
                INSERT INTO import_history (
                    id, company_name, total_vouchers, created, altered, ignored,
                    errors, failed, messages_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    created=excluded.created, altered=excluded.altered, ignored=excluded.ignored,
                    errors=excluded.errors, failed=excluded.failed,
                    messages_json=excluded.messages_json
                """,
                (
                    batch.id, batch.company_name, batch.total_vouchers, batch.created,
                    batch.altered, batch.ignored, batch.errors, batch.failed,
                    json.dumps(batch.messages, ensure_ascii=False), batch.created_at.isoformat(),
                ),
            )

    def list_recent(self, limit: int = 100) -> list[ImportBatch]:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM import_history ORDER BY created_at DESC LIMIT ?", (max(1, limit),)
            ).fetchall()
        return [ImportBatch(
            id=row["id"], company_name=row["company_name"], total_vouchers=row["total_vouchers"],
            created=row["created"], altered=row["altered"], ignored=row["ignored"],
            errors=row["errors"], failed=row["failed"],
            messages=list(json.loads(row["messages_json"])),
            created_at=datetime.fromisoformat(row["created_at"]),
        ) for row in rows]
