"""Standalone portable updater for JD Tool.

This module deliberately depends only on the Python standard library so its
one-file executable stays small and remains independent of the application it
replaces.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import logging
import os
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path

WAIT_TIMEOUT_SECONDS = 60
STABLE_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
LOGGER = logging.getLogger("jdtool.updater")


class UpdaterError(RuntimeError):
    pass


def _contained(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def validate_paths(
    install_dir: Path, staging_dir: Path, data_root: Path, launch_exe: str
) -> tuple[Path, Path, Path, Path, Path]:
    install = install_dir.resolve()
    staging = staging_dir.resolve()
    data = data_root.resolve()
    if not install.is_dir() or not (install / launch_exe).is_file():
        raise UpdaterError("The installed application folder is invalid.")
    if not staging.is_dir() or not (staging / launch_exe).is_file():
        raise UpdaterError("The staged application folder is invalid.")
    if staging.is_symlink() or any(item.is_symlink() for item in staging.rglob("*")):
        raise UpdaterError("The staged application contains a symbolic link.")
    if not data.is_dir() or not _contained(staging, data / "updates"):
        raise UpdaterError("The staging folder is outside the LocalAppData update directory.")
    if _contained(install, data) or _contained(data, install):
        raise UpdaterError("The application folder and user-data folder must remain separate.")
    if Path(launch_exe).name != launch_exe or launch_exe.lower() != "bankstatementtotally.exe":
        raise UpdaterError("The application executable name is invalid.")
    backup = install.with_name(f"{install.name}.previous")
    incoming = install.with_name(f"{install.name}.incoming")
    if backup == install or incoming == install:
        raise UpdaterError("The backup path is invalid.")
    return install, staging, data, backup, incoming


def wait_for_process(pid: int, timeout_seconds: int = WAIT_TIMEOUT_SECONDS) -> bool:
    if pid <= 0 or pid == os.getpid():
        raise UpdaterError("The application process identifier is invalid.")
    if os.name != "nt":
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return True
            time.sleep(0.1)
        return False
    synchronize = 0x00100000
    wait_object_0 = 0x00000000
    wait_timeout = 0x00000102
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(synchronize, False, pid)
    if not handle:
        error = ctypes.get_last_error()
        if error == 87:  # ERROR_INVALID_PARAMETER: the PID has already exited.
            return True
        raise UpdaterError(f"Could not wait for JD Tool to close (Windows error {error}).")
    try:
        result = kernel32.WaitForSingleObject(handle, timeout_seconds * 1000)
        if result == wait_object_0:
            return True
        if result == wait_timeout:
            return False
        raise UpdaterError(f"Waiting for JD Tool failed (result {result}).")
    finally:
        kernel32.CloseHandle(handle)


def _remove_directory(path: Path, expected_parent: Path) -> None:
    resolved = path.resolve()
    if resolved.parent != expected_parent.resolve():
        raise UpdaterError(f"Refusing to remove unexpected path: {resolved}")
    if resolved.is_symlink():
        resolved.unlink()
    elif resolved.exists():
        shutil.rmtree(resolved)


def run_self_test(executable: Path, data_root: Path) -> None:
    result_path = data_root / "updates" / f"self-test-{uuid.uuid4().hex}.json"
    try:
        completed = subprocess.run(  # noqa: S603
            [str(executable), "--self-test", str(result_path)],
            cwd=executable.parent,
            timeout=WAIT_TIMEOUT_SECONDS,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise UpdaterError("The staged application's self-test did not produce a valid result.") from exc
        if completed.returncode != 0 or result.get("status") != "ok" or not result.get("frozen"):
            raise UpdaterError(f"The staged application's self-test failed: {result.get('error', '')}")
    except subprocess.TimeoutExpired as exc:
        raise UpdaterError("The staged application's self-test timed out.") from exc
    finally:
        result_path.unlink(missing_ok=True)


def launch_application(executable: Path, *arguments: str) -> subprocess.Popen[bytes]:
    return subprocess.Popen(  # noqa: S603
        [str(executable), *arguments],
        cwd=executable.parent,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        close_fds=True,
    )


def wait_for_health(marker: Path, process: subprocess.Popen[bytes]) -> bool:
    deadline = time.monotonic() + WAIT_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if marker.is_file():
            try:
                result = json.loads(marker.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return False
            return result.get("status") == "ok"
        if process.poll() is not None:
            return False
        time.sleep(0.25)
    return False


def stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def write_result(data_root: Path, *, status: str, version: str, message: str) -> None:
    result_path = data_root / "updates" / "last-result.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = result_path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(
            {
                "status": status,
                "version": version,
                "message": message,
                "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    os.replace(temporary, result_path)


def _validate_copied_staging(staging: Path, incoming: Path) -> None:
    """Reject incomplete PyInstaller onedir copies before the folder is swapped."""
    for relative in (Path("_internal") / "python312.dll", Path("_internal") / "python3.dll"):
        if (staging / relative).is_file() and not (incoming / relative).is_file():
            raise UpdaterError(f"The staged application is missing {relative.as_posix()}.")


def apply_update(
    *,
    pid: int,
    install_dir: Path,
    staging_dir: Path,
    data_root: Path,
    launch_exe: str,
    version: str,
) -> int:
    if STABLE_VERSION_RE.fullmatch(version) is None:
        raise UpdaterError("The staged application version is invalid.")
    install, staging, data, backup, incoming = validate_paths(
        install_dir, staging_dir, data_root, launch_exe
    )
    updates_root = data / "updates"
    updates_root.mkdir(parents=True, exist_ok=True)
    if not wait_for_process(pid):
        raise UpdaterError("JD Tool did not close within 60 seconds.")

    installed_executable = install / launch_exe
    try:
        run_self_test(staging / launch_exe, data)
    except Exception as exc:
        write_result(data, status="failed", version=version, message=str(exc))
        launch_application(installed_executable)
        raise

    _remove_directory(incoming, install.parent)
    try:
        shutil.copytree(staging, incoming, symlinks=False)
        if not (incoming / launch_exe).is_file():
            raise UpdaterError("Copying the staged application did not complete successfully.")
        _validate_copied_staging(staging, incoming)
    except Exception as exc:
        _remove_directory(incoming, install.parent)
        write_result(
            data,
            status="failed",
            version=version,
            message=f"Copying the staged application failed: {exc}",
        )
        launch_application(installed_executable)
        raise

    moved_installed = False
    try:
        _remove_directory(backup, install.parent)
        os.replace(install, backup)
        moved_installed = True
        os.replace(incoming, install)
    except Exception as exc:
        if moved_installed and not install.exists() and backup.exists():
            os.replace(backup, install)
        _remove_directory(incoming, install.parent)
        write_result(
            data,
            status="failed",
            version=version,
            message=f"The application folder could not be replaced: {exc}",
        )
        if (install / launch_exe).is_file():
            launch_application(install / launch_exe)
        raise

    marker = updates_root / f"health-{uuid.uuid4().hex}.json"
    updated_process: subprocess.Popen[bytes] | None = None
    try:
        updated_process = launch_application(
            install / launch_exe, "--update-health-check", str(marker)
        )
        if not wait_for_health(marker, updated_process):
            raise UpdaterError("The updated application did not pass its 60-second startup health check.")
        write_result(
            data,
            status="success",
            version=version,
            message=f"JD Tool was updated successfully to v{version}.",
        )
        _remove_directory(staging, staging.parent)
        return 0
    except Exception as exc:
        if updated_process is not None:
            stop_process(updated_process)
        _remove_directory(install, install.parent)
        if backup.exists():
            os.replace(backup, install)
        write_result(
            data,
            status="rolled_back",
            version=version,
            message=f"The v{version} update was rolled back: {exc}",
        )
        launch_application(install / launch_exe)
        raise
    finally:
        marker.unlink(missing_ok=True)


def configure_logging(data_root: Path) -> None:
    log_path = data_root / "updates" / "updater.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=log_path,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        encoding="utf-8",
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply a verified JD Tool portable update.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    apply_parser = subparsers.add_parser("apply")
    apply_parser.add_argument("--pid", required=True, type=int)
    apply_parser.add_argument("--install-dir", required=True, type=Path)
    apply_parser.add_argument("--staging-dir", required=True, type=Path)
    apply_parser.add_argument("--data-root", required=True, type=Path)
    apply_parser.add_argument("--launch-exe", required=True)
    apply_parser.add_argument("--version", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    configure_logging(args.data_root)
    try:
        return apply_update(
            pid=args.pid,
            install_dir=args.install_dir,
            staging_dir=args.staging_dir,
            data_root=args.data_root,
            launch_exe=args.launch_exe,
            version=args.version,
        )
    except Exception:
        LOGGER.exception("The portable update failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
