"""Writable data and bundled-resource paths for source and frozen builds."""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    data_root: Path
    resource_root: Path
    frozen: bool

    @classmethod
    def discover(cls, source_root: Path) -> RuntimePaths:
        frozen = bool(getattr(sys, "frozen", False))
        if not frozen:
            return cls(source_root.resolve(), source_root.resolve(), False)
        resource_root = Path(sys._MEIPASS).resolve()
        local_app_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return cls(local_app_data / "BankStatementToTally", resource_root, True)

    def prepare(self) -> None:
        for relative in ("config/bank_templates", "data", "exports", "logs", "backups"):
            (self.data_root / relative).mkdir(parents=True, exist_ok=True)
        if self.data_root == self.resource_root:
            return
        for source in (self.resource_root / "config" / "bank_templates").glob("*.json"):
            destination = self.data_root / "config" / "bank_templates" / source.name
            shutil.copy2(source, destination)
        default_settings = self.resource_root / "config" / "default_settings.json"
        user_settings = self.data_root / "config" / "settings.json"
        if default_settings.exists() and not user_settings.exists():
            shutil.copy2(default_settings, user_settings)


def resource_path(relative_path: str | Path) -> Path:
    """Return a bundled resource in both source and PyInstaller builds."""

    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base / Path(relative_path)


def tcl_path(path: Path) -> str:
    """Return a Tcl-safe absolute path, including for Windows spaces/known folders."""
    normalized = path.resolve().as_posix()
    if os.name != "nt":
        return normalized
    if normalized.startswith("//"):
        return f"//?/UNC/{normalized.lstrip('/')}"
    return f"//?/{normalized}"
