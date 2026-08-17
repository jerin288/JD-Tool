from __future__ import annotations

import hashlib
import io
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
import requests

from app.models.update import UpdateManifest, UpdateRelease
from app.services.update_service import (
    FAILURE_RETRY_INTERVAL,
    SUCCESS_INTERVAL,
    UpdateNetworkError,
    UpdateService,
    UpdateValidationError,
    format_utc,
)


class FakeResponse:
    def __init__(
        self,
        *,
        payload: object | None = None,
        content: bytes = b"",
        headers: dict[str, str] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.payload = payload
        self.content = content
        self.headers = headers or {}
        self.error = error

    def raise_for_status(self) -> None:
        if self.error:
            raise self.error

    def json(self) -> object:
        return self.payload

    def iter_content(self, chunk_size: int):
        del chunk_size
        yield self.content


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses

    def get(self, *_args, **_kwargs) -> FakeResponse:
        return self.responses.pop(0)


def manifest_payload(version: str = "0.6.1", *, size: int = 20, sha256: str | None = None):
    return {
        "schema_version": 1,
        "version": version,
        "asset": f"JD-Tool-windows-x64-v{version}.zip",
        "sha256": sha256 or "a" * 64,
        "size_bytes": size,
        "published_at": "2026-08-17T00:00:00Z",
    }


def release_payload(version: str = "0.6.1", *, size: int = 20, sha256: str | None = None):
    asset_name = f"JD-Tool-windows-x64-v{version}.zip"
    return {
        "tag_name": f"v{version}",
        "draft": False,
        "prerelease": False,
        "html_url": f"https://github.com/jerin288/JD-Tool/releases/tag/v{version}",
        "body": "Release notes",
        "assets": [
            {
                "name": "update-manifest.json",
                "browser_download_url": "https://github.com/jerin288/JD-Tool/releases/download/manifest",
                "size": 200,
            },
            {
                "name": asset_name,
                "browser_download_url": f"https://github.com/jerin288/JD-Tool/releases/download/{asset_name}",
                "size": size,
                "digest": f"sha256:{sha256 or 'a' * 64}",
            },
        ],
    }


def make_archive() -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as package:
        package.writestr("BankStatementToTally/BankStatementToTally.exe", b"executable")
        package.writestr("BankStatementToTally/_internal/library.txt", b"runtime")
    return stream.getvalue()


def make_release_for_content(content: bytes) -> UpdateRelease:
    digest = hashlib.sha256(content).hexdigest()
    manifest = UpdateManifest(
        schema_version=1,
        version="0.6.1",
        asset="JD-Tool-windows-x64-v0.6.1.zip",
        sha256=digest,
        size_bytes=len(content),
        published_at="2026-08-17T00:00:00Z",
    )
    return UpdateRelease(
        version="0.6.1",
        tag="v0.6.1",
        release_url="https://github.com/jerin288/JD-Tool/releases/tag/v0.6.1",
        notes="notes",
        asset_url="https://github.com/jerin288/JD-Tool/releases/download/update.zip",
        manifest=manifest,
    )


def test_update_cadence_tracks_success_and_failed_attempts() -> None:
    now = datetime(2026, 8, 17, 12, tzinfo=UTC)
    assert UpdateService.should_check({}, now=now)
    assert not UpdateService.should_check(
        {"last_update_check_utc": format_utc(now - SUCCESS_INTERVAL + timedelta(minutes=1))}, now=now
    )
    assert UpdateService.should_check(
        {"last_update_check_utc": format_utc(now - SUCCESS_INTERVAL)}, now=now
    )
    assert not UpdateService.should_check(
        {"last_update_attempt_utc": format_utc(now - FAILURE_RETRY_INTERVAL + timedelta(minutes=1))}, now=now
    )
    assert UpdateService.should_check({"automatic_update_checks": False}, manual=True, now=now)


def test_check_latest_accepts_valid_new_stable_release() -> None:
    session = FakeSession(
        [FakeResponse(payload=release_payload()), FakeResponse(payload=manifest_payload())]
    )
    with TemporaryDirectory() as directory:
        release = UpdateService(Path(directory), session=session, current_version="0.6.0").check_latest()
    assert release is not None
    assert release.version == "0.6.1"


def test_check_latest_returns_none_for_installed_version() -> None:
    session = FakeSession(
        [
            FakeResponse(payload=release_payload("0.6.0")),
            FakeResponse(payload=manifest_payload("0.6.0")),
        ]
    )
    with TemporaryDirectory() as directory:
        release = UpdateService(Path(directory), session=session, current_version="0.6.0").check_latest()
    assert release is None


@pytest.mark.parametrize(
    "change",
    [
        {"schema_version": 2},
        {"sha256": "ABC"},
        {"asset": "other.zip"},
        {"extra": "field"},
    ],
)
def test_rejects_malformed_manifest(change: dict[str, object]) -> None:
    manifest = manifest_payload()
    manifest.update(change)
    session = FakeSession([FakeResponse(payload=release_payload()), FakeResponse(payload=manifest)])
    with TemporaryDirectory() as directory, pytest.raises(UpdateValidationError):
        UpdateService(Path(directory), session=session).check_latest()


def test_network_failure_is_classified() -> None:
    session = FakeSession([FakeResponse(error=requests.ConnectionError("offline"))])
    with TemporaryDirectory() as directory, pytest.raises(UpdateNetworkError):
        UpdateService(Path(directory), session=session).check_latest()


def test_prepare_update_verifies_and_extracts_archive() -> None:
    content = make_archive()
    session = FakeSession(
        [FakeResponse(content=content, headers={"Content-Length": str(len(content))})]
    )
    with TemporaryDirectory() as directory:
        prepared = UpdateService(Path(directory), session=session).prepare_update(
            make_release_for_content(content)
        )
        assert (prepared.staging_dir / "BankStatementToTally.exe").read_bytes() == b"executable"
        assert prepared.archive_path.read_bytes() == content
        assert not prepared.archive_path.with_suffix(".zip.part").exists()


def test_prepare_update_rejects_checksum_mismatch() -> None:
    content = make_archive()
    release = make_release_for_content(content)
    bad_manifest = UpdateManifest(
        **{**release.manifest.__dict__, "sha256": "0" * 64}
    )
    bad_release = UpdateRelease(**{**release.__dict__, "manifest": bad_manifest})
    session = FakeSession([FakeResponse(content=content)])
    with TemporaryDirectory() as directory, pytest.raises(UpdateValidationError, match="checksum"):
        UpdateService(Path(directory), session=session).prepare_update(bad_release)


@pytest.mark.parametrize(
    "unsafe_name",
    [
        "../outside.txt",
        "/absolute.txt",
        "BankStatementToTally/../../outside.txt",
        "OtherFolder/file.txt",
    ],
)
def test_safe_extraction_rejects_unsafe_paths(unsafe_name: str) -> None:
    with TemporaryDirectory() as directory:
        archive = Path(directory) / "unsafe.zip"
        with zipfile.ZipFile(archive, "w") as package:
            package.writestr(unsafe_name, b"bad")
        with pytest.raises(UpdateValidationError):
            UpdateService._extract_safe(archive, Path(directory) / "output")


def test_safe_extraction_rejects_symlink() -> None:
    with TemporaryDirectory() as directory:
        archive = Path(directory) / "symlink.zip"
        entry = zipfile.ZipInfo("BankStatementToTally/link")
        entry.create_system = 3
        entry.external_attr = 0o120777 << 16
        with zipfile.ZipFile(archive, "w") as package:
            package.writestr(entry, "target")
        with pytest.raises(UpdateValidationError, match="symbolic link"):
            UpdateService._extract_safe(archive, Path(directory) / "output")
