"""Dynamic JSON bank-template discovery, detection, and persistence."""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.models.bank_template import BankTemplate
from app.models.mapping import ColumnMapping


class BankTemplateService:
    """Loads every template JSON document in a directory at runtime."""

    def __init__(self, template_directory: Path) -> None:
        self.template_directory = template_directory
        self.template_directory.mkdir(parents=True, exist_ok=True)
        self._templates: dict[str, BankTemplate] = {}
        self.reload()

    def reload(self) -> list[BankTemplate]:
        templates: dict[str, BankTemplate] = {}
        for path in sorted(self.template_directory.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(payload, dict) and "templates" in payload:
                    defaults = payload.get("defaults", {})
                    documents = []
                    for entry in payload.get("templates", []):
                        document = dict(defaults)
                        document.update(entry)
                        if isinstance(defaults.get("mapping"), dict):
                            document["mapping"] = {**defaults["mapping"], **entry.get("mapping", {})}
                        documents.append(document)
                else:
                    documents = [payload]
                for document in documents:
                    if isinstance(document, dict):
                        template = BankTemplate.from_dict(document, str(path))
                        templates[template.template_id] = template
            except (OSError, ValueError, TypeError):
                continue
        self._templates = templates
        return self.list_templates()

    def list_templates(self) -> list[BankTemplate]:
        return sorted(self._templates.values(), key=lambda item: item.bank_name.lower())

    def get_by_bank(self, bank_name: str) -> BankTemplate | None:
        normalized = bank_name.strip().lower()
        return next((item for item in self._templates.values() if item.bank_name.lower() == normalized), None)

    def detect(self, statement_text: str) -> BankTemplate | None:
        normalized = re.sub(r"\s+", " ", statement_text.lower())
        statement_header = normalized[:2000]
        scored: list[tuple[int, int, int, BankTemplate]] = []
        for template in self._templates.values():
            matches = [
                keyword
                for keyword in template.detection_keywords
                if self._keyword_matches(keyword, normalized)
            ]
            if matches:
                header_score = sum(
                    1 for keyword in matches if self._keyword_matches(keyword, statement_header)
                )
                scored.append(
                    (header_score, len(matches), max(len(keyword) for keyword in matches), template)
                )
        return max(scored, key=lambda item: item[:3])[3] if scored else None

    @staticmethod
    def _keyword_matches(keyword: str, normalized_text: str) -> bool:
        normalized_keyword = re.sub(r"\s+", " ", keyword.strip().lower())
        if not normalized_keyword:
            return False
        if len(normalized_keyword) <= 3 and normalized_keyword.isalnum():
            return bool(
                re.search(
                    rf"(?<![a-z0-9]){re.escape(normalized_keyword)}(?![a-z0-9])",
                    normalized_text,
                )
            )
        return normalized_keyword in normalized_text

    def save_mapping(
        self,
        bank_name: str,
        mapping: ColumnMapping,
        ignore_phrases: list[str] | None = None,
        multiline_enabled: bool = True,
    ) -> BankTemplate:
        """Persist the current mapping as a standalone, editable JSON template."""
        name = bank_name.strip()
        if not name or name in {"Automatic", "Other / Generic"}:
            raise ValueError("Enter a specific bank name before saving a template.")
        mapping_errors = mapping.validate()
        if mapping_errors:
            raise ValueError("Complete the required mapping first. " + " ".join(mapping_errors))
        template_id = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
        existing = self.get_by_bank(name)
        template = BankTemplate(
            bank_name=name,
            template_id=template_id,
            detection_keywords=existing.detection_keywords if existing else [name],
            mapping=mapping,
            column_aliases=existing.column_aliases if existing else {},
            cleanup_rules=existing.cleanup_rules if existing else [],
            ignore_phrases=ignore_phrases if ignore_phrases is not None else (existing.ignore_phrases if existing else []),
            multiline_enabled=multiline_enabled,
            multiline_joiner=existing.multiline_joiner if existing else " ",
        )
        target = self.template_directory / f"{template_id}.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(template.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(target)
        self.reload()
        return self._templates[template_id]

    def delete(self, template_id: str) -> None:
        template = self._templates.get(template_id)
        if template is None:
            return
        path = Path(template.source_path)
        if not path.name.startswith("user_") and path.name == "common_indian_banks.json":
            raise ValueError("Built-in bank templates cannot be deleted.")
        if path.exists():
            path.unlink()
        self.reload()
