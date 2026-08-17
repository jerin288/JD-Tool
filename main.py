"""Application entry point for Bank Statement PDF to Tally Prime XML Converter."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import __version__  # noqa: E402
from app.bootstrap import build_application  # noqa: E402
from app.services.settings_service import SettingsService  # noqa: E402
from app.utils.logging_config import configure_logging  # noqa: E402
from app.utils.runtime_paths import RuntimePaths  # noqa: E402


def main() -> int:
    """Configure services and start the desktop application."""
    if len(sys.argv) >= 2 and sys.argv[1] == "--self-test":
        return _self_test(Path(sys.argv[2]) if len(sys.argv) >= 3 else PROJECT_ROOT / "self-test.json")
    health_marker = _health_marker_argument(sys.argv[1:])
    paths = RuntimePaths.discover(PROJECT_ROOT)
    paths.prepare()
    settings = SettingsService(paths.data_root / "config" / "settings.json")
    settings.load()
    configure_logging(paths.data_root, settings.get("logging_level", "INFO"))
    application = build_application(paths.data_root)
    if health_marker is not None:
        _write_health_marker(health_marker, paths.data_root)
    application.run()
    return 0


def _self_test(output_path: Path) -> int:
    """Verify frozen imports and Tcl initialization without opening a window."""
    result: dict[str, object] = {"status": "ok", "frozen": bool(getattr(sys, "frozen", False))}
    try:
        import tkinter
        from tempfile import TemporaryDirectory

        import customtkinter
        import fitz
        import pdfplumber
        import pytesseract

        from app.bootstrap import build_application

        interpreter = tkinter.Tcl()
        result.update(
            {
                "tcl": interpreter.eval("info patchlevel"),
                "customtkinter": customtkinter.__version__,
                "pymupdf": fitz.__version__,
                "pdfplumber": pdfplumber.__version__,
                "pytesseract": pytesseract.__version__,
            }
        )
        with TemporaryDirectory() as directory:
            application = build_application(Path(directory))
            application.root.withdraw()
            application.root.update_idletasks()
            application.root.destroy()
        result["ui_smoke_test"] = True
    except Exception as exc:
        result.update({"status": "failed", "error": f"{type(exc).__name__}: {exc}"})
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 0 if result["status"] == "ok" else 1


def _health_marker_argument(arguments: list[str]) -> Path | None:
    try:
        index = arguments.index("--update-health-check")
    except ValueError:
        return None
    if index + 1 >= len(arguments):
        raise RuntimeError("--update-health-check requires a marker path")
    return Path(arguments[index + 1])


def _write_health_marker(marker_path: Path, data_root: Path) -> None:
    """Signal that runtime preparation, database setup, and UI construction succeeded."""
    updates_root = (data_root / "updates").resolve()
    marker = marker_path.resolve()
    try:
        marker.relative_to(updates_root)
    except ValueError as exc:
        raise RuntimeError("The update health marker is outside the update directory") from exc
    marker.parent.mkdir(parents=True, exist_ok=True)
    temporary = marker.with_suffix(marker.suffix + ".tmp")
    temporary.write_text(
        json.dumps({"status": "ok", "version": __version__, "pid": os.getpid()}),
        encoding="utf-8",
    )
    os.replace(temporary, marker)


if __name__ == "__main__":
    raise SystemExit(main())
