"""Reusable, file-backed bank extraction template model."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.models.mapping import ColumnMapping


@dataclass(slots=True)
class BankTemplate:
    """Describes a bank layout without requiring application source changes."""

    bank_name: str
    template_id: str
    detection_keywords: list[str] = field(default_factory=list)
    mapping: ColumnMapping = field(default_factory=ColumnMapping)
    column_aliases: dict[str, list[str]] = field(default_factory=dict)
    cleanup_rules: list[dict[str, str]] = field(default_factory=list)
    ignore_phrases: list[str] = field(default_factory=list)
    multiline_enabled: bool = True
    multiline_joiner: str = " "
    source_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 2,
            "template_id": self.template_id,
            "bank_name": self.bank_name,
            "detection_keywords": self.detection_keywords,
            "mapping": self.mapping.to_dict(),
            "column_aliases": self.column_aliases,
            "cleanup_rules": self.cleanup_rules,
            "ignore_phrases": self.ignore_phrases,
            "multiline_narration": {
                "enabled": self.multiline_enabled,
                "joiner": self.multiline_joiner,
            },
        }

    @classmethod
    def from_dict(cls, values: dict[str, Any], source_path: str = "") -> BankTemplate:
        bank_name = str(values.get("bank_name", "Unnamed Bank")).strip()
        template_id = str(values.get("template_id") or bank_name.lower().replace(" ", "_"))
        multiline = values.get("multiline_narration", {})
        mapping_values = values.get("mapping", {})
        if not mapping_values:
            mapping_values = {
                "date_format": values.get("date_format", "AUTO"),
                "header_row": max(0, int(values.get("header_row", 1)) - 1),
            }
        return cls(
            bank_name=bank_name,
            template_id=template_id,
            detection_keywords=[str(item) for item in values.get("detection_keywords", [bank_name])],
            mapping=ColumnMapping.from_dict(mapping_values),
            column_aliases={
                str(key): [str(alias) for alias in aliases]
                for key, aliases in values.get("column_aliases", {}).items()
            },
            cleanup_rules=[dict(item) for item in values.get("cleanup_rules", []) if isinstance(item, dict)],
            ignore_phrases=[str(item) for item in values.get("ignore_phrases", [])],
            multiline_enabled=bool(multiline.get("enabled", True)),
            multiline_joiner=str(multiline.get("joiner", " ")),
            source_path=source_path,
        )
