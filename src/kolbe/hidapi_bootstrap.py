"""Preload hidapi.dll relative to the running EXE / package (portable).

Never uses a machine-specific absolute path. Looks next to the executable and
under PyInstaller's ``sys._MEIPASS`` (``_internal``). Safe if the DLL is
missing: logs and returns None — DualSense simply falls back; the app does not
crash.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_DLL_NAMES = ("hidapi.dll", "libhidapi-0.dll")
_MISSING_LOGGED = False


def _exe_dir() -> Path:
    """Directory containing the running executable (frozen) or python.exe (dev)."""
    return Path(sys.executable).resolve().parent


def _bundle_dir() -> Path | None:
    """PyInstaller extract / _internal folder when frozen."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass).resolve()
    return None


def _candidate_files() -> list[Path]:
    """Build portable candidate paths — independent of process CWD."""
    files: list[Path] = []
    exe_dir = _exe_dir()
    bundle = _bundle_dir()

    # Frozen onedir: DLL is shipped next to the EXE and/or under _internal.
    search_roots: list[Path] = [exe_dir]
    if bundle is not None:
        search_roots.append(bundle)
    search_roots.extend(
        [
            exe_dir / "_internal",
            exe_dir / "pydualsense",
            exe_dir / "_internal" / "pydualsense",
        ]
    )
    if bundle is not None:
        search_roots.append(bundle / "pydualsense")

    # Dev / source runs: site-packages and vendored packaging/bin.
    if not getattr(sys, "frozen", False):
        try:
            # src/kolbe/hidapi_bootstrap.py → project root is parents[2]
            project_root = Path(__file__).resolve().parents[2]
            search_roots.append(project_root / "packaging" / "bin")
        except Exception:
            pass
        sp = Path(sys.prefix).resolve() / "Lib" / "site-packages"
        search_roots.extend(
            [
                sp / "pydualsense",
                sp / "hid",
                sp / "hidapi",
                sp,
            ]
        )

    for root in search_roots:
        for name in _DLL_NAMES:
            files.append(root / name)

    # De-dupe, preserve order
    seen: set[str] = set()
    out: list[Path] = []
    for path in files:
        key = os.path.normcase(str(path))
        if key not in seen:
            seen.add(key)
            out.append(path)
    return out


def find_hidapi_dll() -> Path | None:
    for path in _candidate_files():
        try:
            if path.is_file():
                return path.resolve()
        except OSError:
            continue
    return None


def _log_missing(message: str) -> None:
    """Append a non-fatal note to kolbe_crash.log next to the EXE (portable)."""
    global _MISSING_LOGGED
    if _MISSING_LOGGED:
        return
    _MISSING_LOGGED = True
    logger.warning(message)
    try:
        log_path = _exe_dir() / "kolbe_crash.log"
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(f"[hidapi_bootstrap] {message}\n")
    except OSError:
        pass


def ensure_hidapi_loaded() -> Path | None:
    """
    Preload ``hidapi.dll`` by path relative to the EXE / bundle.

    Returns the resolved path on success, or None if unavailable.
    Never raises — missing DLL disables DualSense HID only.
    """
    try:
        dll = find_hidapi_dll()
        if dll is None:
            _log_missing(
                "hidapi.dll not found next to the EXE or under _internal — "
                "DualSense advanced HID disabled (app continues)."
            )
            return None

        parent = str(dll.parent)
        if hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(parent)
            except OSError as exc:
                logger.debug("add_dll_directory(%s) failed: %s", parent, exc)

        path_env = os.environ.get("PATH", "")
        if parent.lower() not in path_env.lower().split(os.pathsep):
            os.environ["PATH"] = parent + os.pathsep + path_env

        ctypes.WinDLL(str(dll))
        logger.debug("Preloaded hidapi DLL: %s", dll)
        return dll
    except Exception as exc:
        _log_missing(f"hidapi preload failed gracefully: {exc!r}")
        return None
