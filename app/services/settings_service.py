"""Layered JSON settings with safe defaults."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

DEFAULT_SETTINGS: dict[str, Any] = {
    "appearance_mode": "Light",
    "default_pdf_folder": "",
    "default_export_folder": "exports",
    "default_bank": "Automatic",
    "page_size": 100,
    "duplicate_detection_sensitivity": 75,
    "tally_server_url": "http://localhost:9000",
    "default_bank_ledger": "",
    "default_suspense_ledger": "Suspense A/c",
    "fuzzy_matching_threshold": 78,
    "ocr_executable_path": "",
    "ocr_language": "eng",
    "ocr_dpi": 300,
    "ocr_page_segmentation_mode": 6,
    "logging_level": "INFO",
    "automatic_backup": False,
    "backup_folder": "backups",
    "backup_keep": 7,
    "automatic_update_checks": True,
    "last_update_check_utc": "",
    "last_update_attempt_utc": "",
    "window": {"width": 1440, "height": 900},
}


class SettingsService:
    """Loads distributable defaults and user overrides without storing secrets."""

    def __init__(self, settings_path: Path) -> None:
        self.settings_path = settings_path
        self._settings = deepcopy(DEFAULT_SETTINGS)

    def load(self) -> dict[str, Any]:
        if self.settings_path.exists():
            try:
                values = json.loads(self.settings_path.read_text(encoding="utf-8"))
                self._merge(self._settings, values)
            except (OSError, json.JSONDecodeError, TypeError) as exc:
                raise RuntimeError(f"Could not read settings: {exc}") from exc
        return deepcopy(self._settings)

    def get(self, key: str, default: Any = None) -> Any:
        return self._settings.get(key, default)

    def save(self, updates: dict[str, Any]) -> None:
        self._merge(self._settings, updates)
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.settings_path.with_suffix(".tmp")
        temporary_path.write_text(json.dumps(self._settings, indent=2), encoding="utf-8")
        temporary_path.replace(self.settings_path)

    @classmethod
    def _merge(cls, target: dict[str, Any], updates: dict[str, Any]) -> None:
        for key, value in updates.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                cls._merge(target[key], value)
            else:
                target[key] = value
