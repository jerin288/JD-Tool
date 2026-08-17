"""Immutable data structures used by the portable update workflow."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class UpdateManifest:
    schema_version: int
    version: str
    asset: str
    sha256: str
    size_bytes: int
    published_at: str


@dataclass(frozen=True)
class UpdateRelease:
    version: str
    tag: str
    release_url: str
    notes: str
    asset_url: str
    manifest: UpdateManifest


@dataclass(frozen=True)
class PreparedUpdate:
    release: UpdateRelease
    archive_path: Path
    staging_dir: Path
