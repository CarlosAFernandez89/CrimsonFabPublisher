# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build spec for CrimsonFabPublisher.

Build with:  pyinstaller CrimsonFabPublisher.spec
Produces:    dist/CrimsonFabPublisher.exe  (single-file, windowed)
"""

block_cipher = None

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("app.ico", "."),  # bundled so the app can set its window/taskbar icon
        # The theme degrades to palette-only if this is missing, so a mistake
        # here is invisible in dev — verify the built exe, not just `python main.py`.
        (
            "fabpublisher/ui/theme/crimson.qss",
            "fabpublisher/ui/theme",
        ),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Trim Qt modules we never touch to keep the exe smaller.
    excludes=[
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtQuick3D",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebEngineQuick",
        "PySide6.Qt3DCore",
        "PySide6.QtMultimedia",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtNetwork",
        "tkinter",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="CrimsonFabPublisher",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,   # windowed app; logs stream into the in-app panel
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="app.ico",   # add an .ico here if you want a custom exe icon
)
