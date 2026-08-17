# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


datas = [
    ("config/default_settings.json", "config"),
    ("config/bank_templates", "config/bank_templates"),
    ("app/assets/jd_tool_logo.png", "app/assets"),
    ("app/assets/jd_tool_icon.ico", "app/assets"),
    ("dist/JDToolUpdater.exe", "updater"),
]
datas += collect_data_files("customtkinter")
datas += collect_data_files("tkinterdnd2")
python_root = Path(sys.base_prefix)
datas += [
    (str(python_root / "Lib" / "tkinter"), "tkinter"),
    (str(python_root / "tcl" / "tcl8.6"), "_tcl_data"),
    (str(python_root / "tcl" / "tk8.6"), "_tk_data"),
]
binaries = [
    (str(python_root / "DLLs" / "_tkinter.pyd"), "."),
    (str(python_root / "DLLs" / "tcl86t.dll"), "."),
    (str(python_root / "DLLs" / "tk86t.dll"), "."),
]
hiddenimports = collect_submodules("pdfplumber") + collect_submodules("pytesseract")

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=["packaging_hooks/runtime_tk.py"],
    excludes=["matplotlib", "IPython", "notebook"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="BankStatementToTally",
    icon="app/assets/jd_tool_icon.ico",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="BankStatementToTally",
)
