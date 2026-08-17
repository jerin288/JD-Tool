"""GitHub Releases backed update checking, verification, and staging."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

import requests
from packaging.version import InvalidVersion, Version

from app import __version__
from app.models.update import PreparedUpdate, UpdateManifest, UpdateRelease
from app.utils.runtime_paths import resource_path

LOGGER = logging.getLogger(__name__)

REPOSITORY = "jerin288/JD-Tool"
LATEST_RELEASE_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
MANIFEST_ASSET = "update-manifest.json"
STABLE_TAG_RE = re.compile(r"^v(?P<version>\d+\.\d+\.\d+)$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
WINDOWS_ASSET_RE = re.compile(r"^JD-Tool-windows-x64-v\d+\.\d+\.\d+\.zip$")
SUCCESS_INTERVAL = timedelta(hours=24)
FAILURE_RETRY_INTERVAL = timedelta(hours=6)


class UpdateError(RuntimeError):
    """Base class for update failures safe to show to the user."""


class UpdateNetworkError(UpdateError):
    """The update server could not be reached or returned an HTTP error."""


class UpdateValidationError(UpdateError):
    """Release metadata or downloaded content failed validation."""


class UpdateNotSupportedError(UpdateError):
    """The current installation cannot safely be updated in place."""


def utc_now() -> datetime:
    return datetime.now(UTC)


def format_utc(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_utc(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


class UpdateService:
    """Checks, downloads, and stages optional portable application updates."""

    def __init__(
        self,
        data_root: Path,
        *,
        current_version: str = __version__,
        session: requests.Session | None = None,
        install_dir: Path | None = None,
        frozen: bool | None = None,
    ) -> None:
        self.data_root = Path(data_root).resolve()
        self.updates_root = self.data_root / "updates"
        self.current_version = current_version
        self.session = session or requests.Session()
        self.frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
        default_install = Path(sys.executable).resolve().parent
        self.install_dir = Path(install_dir or default_install).resolve()

    @staticmethod
    def should_check(
        settings: Mapping[str, object], *, manual: bool = False, now: datetime | None = None
    ) -> bool:
        if manual:
            return True
        if not bool(settings.get("automatic_update_checks", True)):
            return False
        current = (now or utc_now()).astimezone(UTC)
        last_success = parse_utc(settings.get("last_update_check_utc"))
        if last_success is not None and current - last_success < SUCCESS_INTERVAL:
            return False
        last_attempt = parse_utc(settings.get("last_update_attempt_utc"))
        if last_attempt is not None and current - last_attempt < FAILURE_RETRY_INTERVAL:
            return False
        return True

    def check_latest(self) -> UpdateRelease | None:
        """Return the newest validated stable release, or ``None`` if current."""
        release_json = self._get_json(LATEST_RELEASE_API, "GitHub release information")
        if not isinstance(release_json, dict):
            raise UpdateValidationError("GitHub returned malformed release information.")
        tag = release_json.get("tag_name")
        match = STABLE_TAG_RE.fullmatch(tag) if isinstance(tag, str) else None
        if match is None:
            raise UpdateValidationError("The latest release does not use a stable vX.Y.Z tag.")
        if release_json.get("draft") or release_json.get("prerelease"):
            raise UpdateValidationError("The latest release is not a stable published release.")
        version_text = match.group("version")
        release_version = self._version(version_text, "release tag")
        current_version = self._version(self.current_version, "installed application")
        assets = release_json.get("assets")
        if not isinstance(assets, list):
            raise UpdateValidationError("The release has no valid asset list.")
        asset_by_name: dict[str, dict[str, Any]] = {}
        for asset in assets:
            if not isinstance(asset, dict) or not isinstance(asset.get("name"), str):
                raise UpdateValidationError("The release contains malformed asset metadata.")
            name = asset["name"]
            if name in asset_by_name:
                raise UpdateValidationError(f"The release contains duplicate asset {name!r}.")
            asset_by_name[name] = asset
        manifest_asset = asset_by_name.get(MANIFEST_ASSET)
        if manifest_asset is None:
            raise UpdateValidationError(f"The release is missing {MANIFEST_ASSET}.")
        manifest_json = self._get_json(
            self._asset_url(manifest_asset, MANIFEST_ASSET), "the update manifest"
        )
        manifest = self._parse_manifest(manifest_json)
        if manifest.version != version_text:
            raise UpdateValidationError("The manifest version does not match the release tag.")
        expected_asset = f"JD-Tool-windows-x64-v{version_text}.zip"
        if manifest.asset != expected_asset or not WINDOWS_ASSET_RE.fullmatch(manifest.asset):
            raise UpdateValidationError("The manifest names an unexpected application asset.")
        application_asset = asset_by_name.get(manifest.asset)
        if application_asset is None:
            raise UpdateValidationError(f"The release is missing {manifest.asset}.")
        if set(asset_by_name) != {MANIFEST_ASSET, manifest.asset}:
            raise UpdateValidationError("The release contains unexpected downloadable assets.")
        remote_size = application_asset.get("size")
        if not isinstance(remote_size, int) or remote_size != manifest.size_bytes:
            raise UpdateValidationError("The GitHub asset size does not match the manifest.")
        remote_digest = application_asset.get("digest")
        if remote_digest is not None and remote_digest != f"sha256:{manifest.sha256}":
            raise UpdateValidationError("The GitHub asset digest does not match the manifest.")
        if release_version <= current_version:
            return None
        return UpdateRelease(
            version=version_text,
            tag=tag,
            release_url=str(
                release_json.get("html_url")
                or f"https://github.com/{REPOSITORY}/releases/tag/{tag}"
            ),
            notes=str(release_json.get("body") or "No release notes were provided."),
            asset_url=self._asset_url(application_asset, manifest.asset),
            manifest=manifest,
        )

    def prepare_update(
        self,
        release: UpdateRelease,
        progress: Callable[[int, int], None] | None = None,
    ) -> PreparedUpdate:
        """Download, verify, and safely extract a release into LocalAppData."""
        self.updates_root.mkdir(parents=True, exist_ok=True)
        version_root = self._child_path(self.updates_root, release.version)
        version_root.mkdir(parents=True, exist_ok=True)
        archive = version_root / release.manifest.asset
        partial = archive.with_suffix(archive.suffix + ".part")
        partial.unlink(missing_ok=True)
        digest = hashlib.sha256()
        received = 0
        try:
            response = self.session.get(
                release.asset_url,
                headers=self._headers(),
                timeout=(10, 60),
                stream=True,
            )
            response.raise_for_status()
            content_length = response.headers.get("Content-Length")
            if content_length is not None:
                try:
                    advertised = int(content_length)
                except ValueError as exc:
                    raise UpdateValidationError("The update has an invalid Content-Length.") from exc
                if advertised != release.manifest.size_bytes:
                    raise UpdateValidationError("The download size does not match the manifest.")
            with partial.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    received += len(chunk)
                    if received > release.manifest.size_bytes:
                        raise UpdateValidationError("The downloaded update is larger than expected.")
                    digest.update(chunk)
                    handle.write(chunk)
                    if progress is not None:
                        progress(received, release.manifest.size_bytes)
                handle.flush()
                os.fsync(handle.fileno())
        except requests.RequestException as exc:
            partial.unlink(missing_ok=True)
            raise UpdateNetworkError(f"Could not download the update: {exc}") from exc
        except Exception:
            partial.unlink(missing_ok=True)
            raise
        if received != release.manifest.size_bytes:
            partial.unlink(missing_ok=True)
            raise UpdateValidationError("The downloaded update is incomplete.")
        if digest.hexdigest() != release.manifest.sha256:
            partial.unlink(missing_ok=True)
            raise UpdateValidationError("The update SHA-256 checksum does not match.")
        os.replace(partial, archive)
        extraction_temp = version_root / "staging.tmp"
        staging_dir = version_root / "BankStatementToTally"
        self._remove_owned_tree(extraction_temp)
        self._remove_owned_tree(staging_dir)
        extraction_temp.mkdir(parents=True)
        try:
            self._extract_safe(archive, extraction_temp)
            extracted_root = extraction_temp / "BankStatementToTally"
            executable = extracted_root / "BankStatementToTally.exe"
            if not executable.is_file():
                raise UpdateValidationError("The update does not contain BankStatementToTally.exe.")
            os.replace(extracted_root, staging_dir)
        finally:
            self._remove_owned_tree(extraction_temp)
        return PreparedUpdate(release=release, archive_path=archive, staging_dir=staging_dir)

    def launch_updater(self, prepared: PreparedUpdate) -> subprocess.Popen[bytes]:
        """Copy the helper outside the install folder and launch it."""
        if os.name != "nt" or not self.frozen:
            raise UpdateNotSupportedError(
                "Portable updates can only be applied from the packaged Windows application."
            )
        self._ensure_install_is_writable()
        updater_source = resource_path(Path("updater") / "JDToolUpdater.exe")
        if not updater_source.is_file():
            raise UpdateNotSupportedError("The packaged update helper is missing.")
        bin_dir = self.updates_root / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        updater_copy = bin_dir / f"JDToolUpdater-{self.current_version}.exe"
        copy_temp = updater_copy.with_suffix(".exe.part")
        shutil.copy2(updater_source, copy_temp)
        os.replace(copy_temp, updater_copy)
        command = [
            str(updater_copy),
            "apply",
            "--pid",
            str(os.getpid()),
            "--install-dir",
            str(self.install_dir),
            "--staging-dir",
            str(prepared.staging_dir),
            "--data-root",
            str(self.data_root),
            "--launch-exe",
            "BankStatementToTally.exe",
            "--version",
            prepared.release.version,
        ]
        return subprocess.Popen(  # noqa: S603 - arguments are a validated list
            command,
            cwd=bin_dir,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            close_fds=True,
        )

    def _get_json(self, url: str, label: str) -> object:
        try:
            response = self.session.get(url, headers=self._headers(), timeout=(5, 20))
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, json.JSONDecodeError, ValueError) as exc:
            raise UpdateNetworkError(f"Could not read {label}: {exc}") from exc

    @staticmethod
    def _headers() -> dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "User-Agent": f"JD-Tool/{__version__}",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    @staticmethod
    def _asset_url(asset: Mapping[str, object], name: str) -> str:
        value = asset.get("browser_download_url")
        if not isinstance(value, str) or not value.startswith("https://github.com/"):
            raise UpdateValidationError(f"The download URL for {name} is invalid.")
        return value

    @staticmethod
    def _version(value: str, label: str) -> Version:
        try:
            parsed = Version(value)
        except InvalidVersion as exc:
            raise UpdateValidationError(f"The {label} version is invalid.") from exc
        if parsed.is_prerelease or parsed.is_devrelease or parsed.local is not None:
            raise UpdateValidationError(f"The {label} is not a stable version.")
        return parsed

    @classmethod
    def _parse_manifest(cls, value: object) -> UpdateManifest:
        if not isinstance(value, dict):
            raise UpdateValidationError("The update manifest is not a JSON object.")
        expected_keys = {
            "schema_version",
            "version",
            "asset",
            "sha256",
            "size_bytes",
            "published_at",
        }
        if set(value) != expected_keys:
            raise UpdateValidationError("The update manifest has missing or unexpected fields.")
        if value.get("schema_version") != 1:
            raise UpdateValidationError("The update manifest schema is unsupported.")
        version = value.get("version")
        asset = value.get("asset")
        sha256 = value.get("sha256")
        size_bytes = value.get("size_bytes")
        published_at = value.get("published_at")
        if not isinstance(version, str) or STABLE_TAG_RE.fullmatch(f"v{version}") is None:
            raise UpdateValidationError("The manifest version is invalid.")
        if not isinstance(asset, str) or WINDOWS_ASSET_RE.fullmatch(asset) is None:
            raise UpdateValidationError("The manifest asset name is invalid.")
        if not isinstance(sha256, str) or SHA256_RE.fullmatch(sha256) is None:
            raise UpdateValidationError("The manifest SHA-256 is invalid.")
        if not isinstance(size_bytes, int) or isinstance(size_bytes, bool) or size_bytes <= 0:
            raise UpdateValidationError("The manifest size is invalid.")
        if (
            not isinstance(published_at, str)
            or not published_at.endswith("Z")
            or parse_utc(published_at) is None
        ):
            raise UpdateValidationError("The manifest publication timestamp is invalid.")
        return UpdateManifest(1, version, asset, sha256, size_bytes, published_at)

    @classmethod
    def _extract_safe(cls, archive: Path, destination: Path) -> None:
        try:
            with zipfile.ZipFile(archive) as package:
                entries = package.infolist()
                if not entries:
                    raise UpdateValidationError("The update archive is empty.")
                if len(entries) > 100_000:
                    raise UpdateValidationError("The update archive contains too many entries.")
                expanded_limit = min(
                    4 * 1024 * 1024 * 1024,
                    max(1024 * 1024 * 1024, archive.stat().st_size * 30),
                )
                if sum(entry.file_size for entry in entries) > expanded_limit:
                    raise UpdateValidationError("The update archive expands beyond its safe size limit.")
                seen_paths: set[str] = set()
                for entry in entries:
                    raw_name = entry.filename
                    if "\\" in raw_name:
                        raise UpdateValidationError("The update contains an unsafe path separator.")
                    member = PurePosixPath(raw_name)
                    if member.is_absolute() or ".." in member.parts or not member.parts:
                        raise UpdateValidationError("The update contains an unsafe path.")
                    if member.parts[0] != "BankStatementToTally" or any(
                        ":" in part for part in member.parts
                    ):
                        raise UpdateValidationError(
                            "The update contains a file outside its application folder."
                        )
                    if entry.flag_bits & 0x1:
                        raise UpdateValidationError("The update contains an encrypted ZIP entry.")
                    windows_key = "/".join(part.rstrip(" .").casefold() for part in member.parts)
                    if windows_key in seen_paths:
                        raise UpdateValidationError("The update contains duplicate Windows paths.")
                    seen_paths.add(windows_key)
                    unix_mode = (entry.external_attr >> 16) & 0xFFFF
                    if stat.S_ISLNK(unix_mode):
                        raise UpdateValidationError("The update contains a symbolic link.")
                    file_type = stat.S_IFMT(unix_mode)
                    if file_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
                        raise UpdateValidationError("The update contains an unsupported file type.")
                    target = (destination / Path(*member.parts)).resolve()
                    try:
                        target.relative_to(destination.resolve())
                    except ValueError as exc:
                        raise UpdateValidationError("The update contains a path traversal entry.") from exc
                    if entry.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with package.open(entry) as source, target.open("wb") as output:
                        shutil.copyfileobj(source, output, length=1024 * 1024)
        except zipfile.BadZipFile as exc:
            raise UpdateValidationError("The downloaded update is not a valid ZIP archive.") from exc

    @staticmethod
    def _child_path(parent: Path, name: str) -> Path:
        child = (parent / name).resolve()
        try:
            child.relative_to(parent.resolve())
        except ValueError as exc:
            raise UpdateValidationError("An update path escaped its data directory.") from exc
        return child

    def _remove_owned_tree(self, path: Path) -> None:
        resolved = path.resolve()
        try:
            resolved.relative_to(self.updates_root.resolve())
        except ValueError as exc:
            raise UpdateValidationError("Refusing to remove a path outside the update directory.") from exc
        if resolved.is_symlink():
            resolved.unlink()
        elif resolved.exists():
            shutil.rmtree(resolved)

    def _ensure_install_is_writable(self) -> None:
        if not self.install_dir.is_dir():
            raise UpdateNotSupportedError("The application installation folder no longer exists.")
        try:
            with tempfile.NamedTemporaryFile(
                prefix="jdtool-update-", dir=self.install_dir.parent, delete=True
            ):
                pass
        except OSError as exc:
            raise UpdateNotSupportedError(
                "The portable installation folder is not writable. Download the release and extract it "
                "to a writable folder; administrator elevation is not requested."
            ) from exc
