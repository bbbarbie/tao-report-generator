# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build for the Windows desktop application.

--onedir, not --onefile: a single-file build unpacks itself to a temporary
directory on every launch, which is slow on a corporate laptop and is a common
trigger for antivirus quarantine. A folder can also be inspected by whoever
approves the software.

Nothing from samples/, tests/ or the developer documentation is bundled — the
end user gets the application and a short guide, and no company data ships
inside the executable.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve().parent
APP_NAME = "TAO Report Generator"

datas = [
    # The seed operator list and report scope must travel with the app; they
    # are read at run time and are meant to be editable.
    (str(ROOT / "config" / "operator_mapping.json"), "config"),
    (str(ROOT / "config" / "report_scope.json"), "config"),
    (str(ROOT / "packaging" / "使用說明.txt"), "."),
]

hiddenimports = [
    *collect_submodules("openpyxl"),
    "app.calculations",
    "app.decisions",
    "app.generator",
    "app.models",
    "app.normalization",
    "app.operators",
    "app.parser",
    "app.report",
    "app.review",
    "app.selection",
    "app.settings",
    "app.voyage_history",
    "desktop.review_view",
    "desktop.selftest",
]

# Qt modules the application never touches. Excluding them keeps the folder to
# a size that can be emailed or copied to a memory stick.
excludes = [
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQuickWidgets",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.Qt3DCore",
    "PySide6.Qt3DRender", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning",
    "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDesigner", "PySide6.QtHelp",
    "streamlit", "altair", "pandas", "numpy", "matplotlib", "pytest",
    "tkinter", "PIL", "IPython", "jupyter",
]

a = Analysis(
    [str(ROOT / "desktop" / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # no console window for the end user
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
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)
