"""Phase 4 XML export, validation, and import report models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from uuid import uuid4


class VoucherMode(StrEnum):
    DOUBLE_ENTRY = "Double Entry"
    SINGLE_ENTRY = "Single Entry Payment/Receipt"


class ExportGrouping(StrEnum):
    COMBINED = "One Combined XML"
    VOUCHER_TYPE = "Separate by Voucher Type"
    MONTH = "Separate by Month"


@dataclass(frozen=True, slots=True)
class ExportOptions:
    company_name: str
    voucher_mode: VoucherMode = VoucherMode.DOUBLE_ENTRY
    grouping: ExportGrouping = ExportGrouping.COMBINED
    period_start: date | None = None
    period_end: date | None = None
    include_bank_allocations: bool = True
    base_filename: str = "tally_bank_vouchers"


@dataclass(frozen=True, slots=True)
class VoucherValidationIssue:
    transaction_id: str
    row_number: int
    severity: str
    message: str


@dataclass(frozen=True, slots=True)
class ExportValidationReport:
    issues: tuple[VoucherValidationIssue, ...]
    valid_transaction_ids: tuple[str, ...]
    invalid_transaction_ids: tuple[str, ...]

    @property
    def is_valid(self) -> bool:
        return not self.invalid_transaction_ids


@dataclass(frozen=True, slots=True)
class XmlDocument:
    filename: str
    content: bytes
    transaction_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class XmlExportResult:
    files: tuple[Path, ...]
    exported_transaction_ids: tuple[str, ...]
    validation: ExportValidationReport


@dataclass(frozen=True, slots=True)
class TallyImportResponse:
    created: int = 0
    altered: int = 0
    ignored: int = 0
    errors: int = 0
    cancelled: int = 0
    exceptions: int = 0
    last_voucher_id: str = ""
    messages: tuple[str, ...] = ()

    @property
    def succeeded(self) -> bool:
        return (
            self.errors == 0 and self.exceptions == 0
            and self.ignored == 0 and self.cancelled == 0
        )


@dataclass(slots=True)
class ImportBatch:
    company_name: str
    total_vouchers: int
    created: int = 0
    altered: int = 0
    ignored: int = 0
    errors: int = 0
    failed: int = 0
    messages: list[str] = field(default_factory=list)
    id: str = field(default_factory=lambda: str(uuid4()))
    created_at: datetime = field(default_factory=datetime.now)
