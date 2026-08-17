"""Tally Prime connection data models."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TallyCompany:
    name: str
    guid: str = ""
    starting_from: str = ""
    ending_at: str = ""


@dataclass(frozen=True, slots=True)
class TallyLedger:
    name: str
    parent_group: str = ""
    guid: str = ""

    @property
    def is_bank_or_cash(self) -> bool:
        parent = re.sub(r"[^a-z0-9]+", "", self.parent_group.lower())
        return any(token in parent for token in ("bankaccounts", "bankod", "cashinhand"))


@dataclass(frozen=True, slots=True)
class TallyCompanyData:
    company: TallyCompany
    ledgers: tuple[TallyLedger, ...]
    voucher_types: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TallyConnectionResult:
    server_url: str
    companies: tuple[TallyCompany, ...]
    response_time_ms: int
