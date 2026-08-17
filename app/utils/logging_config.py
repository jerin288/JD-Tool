"""Rotating, privacy-aware application logging."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.utils.security import redact_sensitive_data


class SensitiveDataFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_sensitive_data(str(record.msg))
        if record.args:
            record.args = tuple(redact_sensitive_data(str(arg)) for arg in record.args)
        return True


def configure_logging(project_root: Path, level: int | str = logging.INFO) -> None:
    """Configure console and 2 MB rotating file logs."""
    log_dir = project_root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    privacy_filter = SensitiveDataFilter()

    file_handler = RotatingFileHandler(
        log_dir / "application.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    file_handler.addFilter(privacy_filter)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.addFilter(privacy_filter)

    resolved_level = logging.getLevelNamesMapping().get(str(level).upper(), logging.INFO) if isinstance(level, str) else level
    logging.basicConfig(level=resolved_level, handlers=[file_handler, console_handler], force=True)
