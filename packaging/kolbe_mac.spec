# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Kolbe Controller macOS .app bundle."""

import os

from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))
PROJECT_ROOT = os.path.dirname(SPEC_DIR)
LAUNCHER = os.path.join(SPEC_DIR, "mac_launcher.py")

kolbe_hidden = collect_submodules("kolbe")

pyqt6_datas, pyqt6_binaries, pyqt6_hidden = collect_all("PyQt6")
pygame_datas, pygame_binaries, pygame_hidden = collect_all("pygame")
rtmidi_datas, rtmidi_binaries, rtmidi_hidden = collect_all("rtmidi")
mido_datas, mido_binaries, mido_hidden = collect_all("mido")

pydualsense_datas: list = []
pydualsense_binaries: list = []
pydualsense_hidden: list = []
try:
    pydualsense_datas, pydualsense_binaries, pydualsense_hidden = collect_all("pydualsense")
except Exception:
    pydualsense_hidden = [
        "pydualsense",
        "pydualsense.pydualsense",
        "pydualsense.checksum",
        "pydualsense.enums",
        "pydualsense.event_system",
        "pydualsense.hidguardian",
    ]

hiddenimports = (
    kolbe_hidden
    + pyqt6_hidden
    + pygame_hidden
    + rtmidi_hidden
    + mido_hidden
    + pydualsense_hidden
    + [
        "hid",
        "mido.backends.rtmidi",
        "mido.backends.rtmidi_python",
        "rtmidi._rtmidi",
    ]
)

a = Analysis(
    [LAUNCHER],
    pathex=[os.path.join(PROJECT_ROOT, "src")],
    binaries=(
        pyqt6_binaries
        + pygame_binaries
        + rtmidi_binaries
        + mido_binaries
        + pydualsense_binaries
    ),
    datas=(
        pyqt6_datas
        + pygame_datas
        + rtmidi_datas
        + mido_datas
        + pydualsense_datas
    ),
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Kolbe Controller",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
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
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Kolbe Controller",
)

app = BUNDLE(
    coll,
    name="Kolbe Controller.app",
    icon=None,
    bundle_identifier="com.kolbe.controller",
    info_plist={
        "CFBundleName": "Kolbe Controller",
        "CFBundleDisplayName": "Kolbe Controller",
        "CFBundleShortVersionString": "0.1.0",
        "CFBundleVersion": "0.1.0",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "11.0",
        "NSHumanReadableCopyright": "Copyright © 2026 Kolbe",
    },
)
