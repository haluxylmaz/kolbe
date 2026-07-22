# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller onedir spec for Kolbe v1.0.3 (Windows).
Used by: .\\build_win.ps1  (ALWAYS via .\\.venv\\Scripts\\python.exe)

FORCE-INCLUDES hidapi.dll by absolute path (not via hiddenimports).
No copy_metadata() — avoids PackageNotFoundError under mismatched envs.
"""

import os
import shutil
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))
PROJECT_ROOT = os.path.dirname(SPEC_DIR)
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
ENTRY = os.path.join(SRC_DIR, "kolbe", "__main__.py")
ICON = os.path.join(PROJECT_ROOT, "icon.ico")
RTHOOK_HIDAPI = os.path.join(SPEC_DIR, "rthooks", "pyi_rth_hidapi_path.py")
APP_NAME = "Kolbe v1.0.3"

# Absolute path on this machine (.venv / pydualsense).
# Build-time only: locate DLL relative to this project / active .venv (no user home hardcode).
_HIDAPI_CANDIDATES = [
    os.path.join(PROJECT_ROOT, "packaging", "bin", "hidapi.dll"),
    os.path.join(PROJECT_ROOT, ".venv", "Lib", "site-packages", "pydualsense", "hidapi.dll"),
    os.path.join(sys.prefix, "Lib", "site-packages", "pydualsense", "hidapi.dll"),
]

_HIDAPI_DLL = next((p for p in _HIDAPI_CANDIDATES if os.path.isfile(p)), None)
if _HIDAPI_DLL is None:
    raise SystemExit(
        "ERROR: hidapi.dll not found. Looked in:\n  - "
        + "\n  - ".join(_HIDAPI_CANDIDATES)
        + "\nInstall into .venv: .\\.venv\\Scripts\\python.exe -m pip install pydualsense"
    )

_HIDAPI_DLL = os.path.abspath(_HIDAPI_DLL)
print(f"[kolbe.spec] FORCE binaries hidapi.dll = {_HIDAPI_DLL}")
print(f"[kolbe.spec] sys.executable = {sys.executable}")
print(f"[kolbe.spec] sys.version    = {sys.version}")

_vendored = os.path.join(PROJECT_ROOT, "packaging", "bin", "hidapi.dll")
os.makedirs(os.path.dirname(_vendored), exist_ok=True)
if os.path.abspath(_HIDAPI_DLL) != os.path.abspath(_vendored):
    shutil.copy2(_HIDAPI_DLL, _vendored)
    _HIDAPI_DLL = os.path.abspath(_vendored)

hidapi_force_binaries = [
    (_HIDAPI_DLL, "."),
    (_HIDAPI_DLL, "pydualsense"),
]

kolbe_hidden = collect_submodules("kolbe")

pyqt6_datas, pyqt6_binaries, pyqt6_hidden = collect_all("PyQt6")
pygame_datas, pygame_binaries, pygame_hidden = collect_all("pygame")
mido_datas, mido_binaries, mido_hidden = collect_all("mido")

rtmidi_datas, rtmidi_binaries, rtmidi_hidden = [], [], ["rtmidi", "rtmidi._rtmidi"]
try:
    rtmidi_datas, rtmidi_binaries, rtmidi_hidden = collect_all("rtmidi")
except Exception:
    pass

hid_datas, hid_binaries, hid_hidden = [], [], ["hid"]
try:
    hid_datas, hid_binaries, hid_hidden = collect_all("hid")
except Exception:
    pass

hidapi_datas, hidapi_binaries, hidapi_hidden = [], [], ["hidapi", "cffi", "_cffi_backend"]
try:
    hidapi_datas, hidapi_binaries, hidapi_hidden = collect_all("hidapi")
except Exception:
    pass

pydualsense_datas, pydualsense_binaries, pydualsense_hidden = [], [], []
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

hiddenimports = list(
    dict.fromkeys(
        kolbe_hidden
        + pyqt6_hidden
        + pygame_hidden
        + rtmidi_hidden
        + mido_hidden
        + hid_hidden
        + hidapi_hidden
        + pydualsense_hidden
        + [
            "kolbe.hidapi_bootstrap",
            "hid",
            "hidapi",
            "cffi",
            "_cffi_backend",
            "pydualsense",
            "mido.backends.rtmidi",
            "rtmidi",
        ]
    )
)

datas = (
    list(pyqt6_datas)
    + list(pygame_datas)
    + list(rtmidi_datas)
    + list(mido_datas)
    + list(hid_datas)
    + list(hidapi_datas)
    + list(pydualsense_datas)
)

if os.path.isfile(ICON):
    datas = list(datas) + [(ICON, ".")]

binaries = (
    list(pyqt6_binaries)
    + list(pygame_binaries)
    + list(rtmidi_binaries)
    + list(mido_binaries)
    + list(hid_binaries)
    + list(hidapi_binaries)
    + list(pydualsense_binaries)
    + list(hidapi_force_binaries)
)

_runtime_hooks = [RTHOOK_HIDAPI] if os.path.isfile(RTHOOK_HIDAPI) else []

a = Analysis(
    [ENTRY],
    pathex=[SRC_DIR],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=_runtime_hooks,
    excludes=["tkinter", "unittest", "test", "tests"],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

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
    name=APP_NAME,
)

_dist_app = os.path.join(DISTPATH, APP_NAME)
try:
    os.makedirs(_dist_app, exist_ok=True)
    shutil.copy2(_HIDAPI_DLL, os.path.join(_dist_app, "hidapi.dll"))
    print(f"[kolbe.spec] Copied hidapi.dll next to EXE -> {_dist_app}")
except OSError as exc:
    print(f"[kolbe.spec] WARNING: copy next to EXE failed: {exc}")
