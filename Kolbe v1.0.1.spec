# -*- mode: python ; coding: utf-8 -*-
"""Deprecated alias of Kolbe v1.0.2.spec — builds Kolbe v1.0.2."""

import os

from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

block_cipher = None

SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))
PROJECT_ROOT = SPEC_DIR
ENTRY = os.path.join(PROJECT_ROOT, "src", "kolbe", "__main__.py")
ICON = os.path.join(PROJECT_ROOT, "icon.ico")

kolbe_hidden = collect_submodules("kolbe")

pyqt6_datas, pyqt6_binaries, pyqt6_hidden = collect_all("PyQt6")
pygame_datas, pygame_binaries, pygame_hidden = collect_all("pygame")
mido_datas, mido_binaries, mido_hidden = collect_all("mido")

rtmidi_datas: list = []
rtmidi_binaries: list = []
rtmidi_hidden: list = ["rtmidi", "rtmidi._rtmidi"]
try:
    rtmidi_datas, rtmidi_binaries, rtmidi_hidden = collect_all("rtmidi")
except Exception:
    pass

hid_datas: list = []
hid_binaries: list = []
hid_hidden: list = ["hid"]
try:
    hid_datas, hid_binaries, hid_hidden = collect_all("hid")
except Exception:
    pass

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
    + hid_hidden
    + pydualsense_hidden
    + [
        "pygame",
        "PyQt6",
        "PyQt6.QtCore",
        "PyQt6.QtGui",
        "PyQt6.QtWidgets",
        "mido.backends.rtmidi",
        "mido.backends.rtmidi_python",
    ]
)

datas = (
    pyqt6_datas
    + pygame_datas
    + rtmidi_datas
    + mido_datas
    + hid_datas
    + pydualsense_datas
    + copy_metadata("mido")
)

if os.path.isfile(ICON):
    datas = datas + [(ICON, ".")]

binaries = (
    pyqt6_binaries
    + pygame_binaries
    + rtmidi_binaries
    + mido_binaries
    + hid_binaries
    + pydualsense_binaries
)

a = Analysis(
    [ENTRY],
    pathex=[os.path.join(PROJECT_ROOT, "src")],
    binaries=binaries,
    datas=datas,
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
    name="Kolbe v1.0.2",
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
    icon=ICON if os.path.isfile(ICON) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Kolbe v1.0.2",
)
