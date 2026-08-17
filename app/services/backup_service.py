"""Local application-data backups with retention."""

from __future__ import annotations

import json
import zipfile
from datetime import datetime
from pathlib import Path


class BackupService:
    def __init__(self, data_root: Path) -> None:
        self.data_root = data_root

    def create(self, destination: Path | None = None, keep: int = 7) -> Path:
        folder = destination or self.data_root / "backups"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"bank_converter_backup_{datetime.now():%Y%m%d_%H%M%S_%f}.zip"
        temporary = target.with_suffix(".tmp")
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for relative in (Path("data/bank_converter.db"), Path("config/settings.json")):
                source = self.data_root / relative
                if source.is_file():
                    archive.write(source, relative)
            for source in (self.data_root / "config" / "bank_templates").glob("*.json"):
                archive.write(source, source.relative_to(self.data_root))
            archive.writestr(
                "backup_manifest.json",
                json.dumps({"created_at": datetime.now().isoformat(timespec="seconds"), "format": 1}, indent=2),
            )
        temporary.replace(target)
        self._apply_retention(folder, max(1, keep), target)
        return target

    def create_if_due(self, destination: Path | None = None, keep: int = 7) -> Path | None:
        folder = destination or self.data_root / "backups"
        today = datetime.now().strftime("%Y%m%d")
        if folder.exists() and any(folder.glob(f"bank_converter_backup_{today}_*.zip")):
            return None
        return self.create(folder, keep)

    @staticmethod
    def _apply_retention(folder: Path, keep: int, newest: Path) -> None:
        backups = sorted(
            (path for path in folder.glob("bank_converter_backup_*.zip") if path != newest),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for expired in backups[max(0, keep - 1) :]:
            expired.unlink(missing_ok=True)
