from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

import updater_main
from main import _write_health_marker


class FakeProcess:
    def __init__(self) -> None:
        self.returncode = None

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.returncode = 1

    def kill(self) -> None:
        self.returncode = 1

    def wait(self, timeout: int):
        del timeout
        self.returncode = 1
        return self.returncode


def create_layout(root: Path) -> tuple[Path, Path, Path]:
    install = root / "Portable App" / "BankStatementToTally"
    data = root / "Local App Data" / "BankStatementToTally"
    staging = data / "updates" / "0.6.1" / "BankStatementToTally"
    install.mkdir(parents=True)
    staging.mkdir(parents=True)
    (install / "BankStatementToTally.exe").write_text("old", encoding="utf-8")
    (install / "old.txt").write_text("old-data", encoding="utf-8")
    (staging / "BankStatementToTally.exe").write_text("new", encoding="utf-8")
    (staging / "new.txt").write_text("new-data", encoding="utf-8")
    (data / "config").mkdir()
    (data / "config" / "settings.json").write_text("user settings", encoding="utf-8")
    return install, data, staging


def test_validate_copied_staging_rejects_truncated_dll() -> None:
    import sys

    with TemporaryDirectory() as directory:
        root = Path(directory)
        staging = root / "staging" / "_internal"
        incoming = root / "incoming" / "_internal"
        staging.mkdir(parents=True)
        incoming.mkdir(parents=True)
        dll_name = f"python3{sys.version_info.minor}.dll"
        (staging / dll_name).write_bytes(b"x" * 5000)
        # Simulate a copy that "succeeded" (file exists) but was truncated mid-write.
        (incoming / dll_name).write_bytes(b"")
        with pytest.raises(updater_main.UpdaterError, match="corrupt"):
            updater_main._validate_copied_staging(staging.parent, incoming.parent)


def test_validate_copied_staging_accepts_matching_dll_size() -> None:
    import sys

    with TemporaryDirectory() as directory:
        root = Path(directory)
        staging = root / "staging" / "_internal"
        incoming = root / "incoming" / "_internal"
        staging.mkdir(parents=True)
        incoming.mkdir(parents=True)
        dll_name = f"python3{sys.version_info.minor}.dll"
        (staging / dll_name).write_bytes(b"x" * 5000)
        (incoming / dll_name).write_bytes(b"x" * 5000)
        updater_main._validate_copied_staging(staging.parent, incoming.parent)


def test_validate_paths_rejects_staging_outside_user_update_folder() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        install, data, _staging = create_layout(root)
        outside = root / "outside"
        outside.mkdir()
        (outside / "BankStatementToTally.exe").write_text("new", encoding="utf-8")
        with pytest.raises(updater_main.UpdaterError):
            updater_main.validate_paths(install, outside, data, "BankStatementToTally.exe")


def test_successful_swap_preserves_one_previous_version_and_user_data() -> None:
    with TemporaryDirectory() as directory:
        install, data, staging = create_layout(Path(directory))
        previous = install.with_name(f"{install.name}.previous")
        previous.mkdir()
        (previous / "obsolete.txt").write_text("obsolete", encoding="utf-8")
        with (
            patch("updater_main.wait_for_process", return_value=True),
            patch("updater_main.run_self_test"),
            patch("updater_main.wait_for_health", return_value=True),
            patch("updater_main.launch_application", return_value=FakeProcess()),
        ):
            result = updater_main.apply_update(
                pid=123,
                install_dir=install,
                staging_dir=staging,
                data_root=data,
                launch_exe="BankStatementToTally.exe",
                version="0.6.1",
            )
        assert result == 0
        assert (install / "new.txt").read_text(encoding="utf-8") == "new-data"
        assert (previous / "old.txt").read_text(encoding="utf-8") == "old-data"
        assert not (previous / "obsolete.txt").exists()
        assert (data / "config" / "settings.json").read_text(encoding="utf-8") == "user settings"


def test_failed_health_check_rolls_back_and_relaunches_previous_version() -> None:
    with TemporaryDirectory() as directory:
        install, data, staging = create_layout(Path(directory))
        launch = FakeProcess()
        with (
            patch("updater_main.wait_for_process", return_value=True),
            patch("updater_main.run_self_test"),
            patch("updater_main.wait_for_health", return_value=False),
            patch("updater_main.launch_application", return_value=launch) as launch_mock,
            pytest.raises(updater_main.UpdaterError, match="health check"),
        ):
            updater_main.apply_update(
                pid=123,
                install_dir=install,
                staging_dir=staging,
                data_root=data,
                launch_exe="BankStatementToTally.exe",
                version="0.6.1",
            )
        assert (install / "old.txt").is_file()
        assert not install.with_name(f"{install.name}.previous").exists()
        assert launch_mock.call_count == 2
        result = (data / "updates" / "last-result.json").read_text(encoding="utf-8")
        assert "rolled_back" in result


def test_staged_self_test_failure_keeps_installed_version() -> None:
    with TemporaryDirectory() as directory:
        install, data, staging = create_layout(Path(directory))
        with (
            patch("updater_main.wait_for_process", return_value=True),
            patch("updater_main.run_self_test", side_effect=updater_main.UpdaterError("bad build")),
            patch("updater_main.launch_application", return_value=FakeProcess()) as launch_mock,
            pytest.raises(updater_main.UpdaterError, match="bad build"),
        ):
            updater_main.apply_update(
                pid=123,
                install_dir=install,
                staging_dir=staging,
                data_root=data,
                launch_exe="BankStatementToTally.exe",
                version="0.6.1",
            )
        assert (install / "old.txt").is_file()
        launch_mock.assert_called_once_with(install.resolve() / "BankStatementToTally.exe")


def test_locked_install_folder_keeps_and_relaunches_current_version() -> None:
    with TemporaryDirectory() as directory:
        install, data, staging = create_layout(Path(directory))
        original_replace = updater_main.os.replace

        def locked_replace(source, destination):
            if Path(source) == install.resolve():
                raise PermissionError("locked application file")
            return original_replace(source, destination)

        with (
            patch("updater_main.wait_for_process", return_value=True),
            patch("updater_main.run_self_test"),
            patch("updater_main.os.replace", side_effect=locked_replace),
            patch("updater_main.launch_application", return_value=FakeProcess()) as launch_mock,
            pytest.raises(PermissionError, match="locked"),
        ):
            updater_main.apply_update(
                pid=123,
                install_dir=install,
                staging_dir=staging,
                data_root=data,
                launch_exe="BankStatementToTally.exe",
                version="0.6.1",
            )
        assert (install / "old.txt").is_file()
        assert not install.with_name(f"{install.name}.incoming").exists()
        launch_mock.assert_called_once_with(install.resolve() / "BankStatementToTally.exe")
        assert '"status": "failed"' in (data / "updates" / "last-result.json").read_text(
            encoding="utf-8"
        )


def test_copy_failure_cleans_partial_incoming_and_relaunches_current_version() -> None:
    with TemporaryDirectory() as directory:
        install, data, staging = create_layout(Path(directory))
        incoming = install.with_name(f"{install.name}.incoming")

        def partial_copy(source, destination, **_kwargs):
            del source
            destination.mkdir(parents=True, exist_ok=True)
            (destination / "BankStatementToTally.exe").write_text("partial", encoding="utf-8")
            raise OSError("copy failed")

        with (
            patch("updater_main.wait_for_process", return_value=True),
            patch("updater_main.run_self_test"),
            patch("updater_main.shutil.copytree", side_effect=partial_copy),
            patch("updater_main.launch_application", return_value=FakeProcess()) as launch_mock,
            pytest.raises(OSError, match="copy failed"),
        ):
            updater_main.apply_update(
                pid=123,
                install_dir=install,
                staging_dir=staging,
                data_root=data,
                launch_exe="BankStatementToTally.exe",
                version="0.6.1",
            )
        assert (install / "old.txt").is_file()
        assert not incoming.exists()
        launch_mock.assert_called_once_with(install.resolve() / "BankStatementToTally.exe")
        result = (data / "updates" / "last-result.json").read_text(encoding="utf-8")
        assert '"status": "failed"' in result


def test_application_health_marker_is_atomic_and_scoped_to_updates() -> None:
    with TemporaryDirectory() as directory:
        data = Path(directory)
        marker = data / "updates" / "health.json"
        _write_health_marker(marker, data)
        assert '"status": "ok"' in marker.read_text(encoding="utf-8")
        with pytest.raises(RuntimeError, match="outside"):
            _write_health_marker(data.parent / "outside-health.json", data)
