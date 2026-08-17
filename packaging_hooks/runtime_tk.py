"""Point a frozen application at its explicitly bundled Tcl/Tk libraries."""

from __future__ import annotations

import os
import sys
from pathlib import Path

bundle_root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)).resolve()


def tcl_windows_path(path: Path) -> str:
    """Avoid Tcl 8.6 legacy normalization bugs for spaces and known folders."""
    normalized = path.resolve().as_posix()
    if os.name != "nt":
        return normalized
    if normalized.startswith("//"):
        return f"//?/UNC/{normalized.lstrip('/')}"
    return f"//?/{normalized}"


os.environ["TCL_LIBRARY"] = tcl_windows_path(bundle_root / "_tcl_data")
os.environ["TK_LIBRARY"] = tcl_windows_path(bundle_root / "_tk_data")
