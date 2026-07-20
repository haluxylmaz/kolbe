"""Frozen-aware filesystem locations for Kolbe (dev + PyInstaller)."""

from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_dir() -> Path:
    """
    Read-only bundle root.

    - Frozen onedir/onefile: ``sys._MEIPASS`` (``_internal`` or ``_MEIxxxx``)
    - Dev: ``src/kolbe`` package directory
    """
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def app_dir() -> Path:
    """
    Writable directory next to the running app.

    - Frozen: folder containing the ``.exe``
    - Dev: repository root (parent of ``src``)
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # src/kolbe/paths.py → parents[2] == project root
    return Path(__file__).resolve().parents[2]


def project_root() -> Path:
    """Backward-compatible alias for the writable project/app root."""
    return app_dir()


def resource_path(*parts: str) -> Path:
    """
    Resolve a bundled data file (e.g. ``icon.ico``).

    Searches ``_MEIPASS``, the EXE directory, and ``_internal`` next to the EXE.
    """
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        exe_dir = Path(sys.executable).resolve().parent
        if meipass:
            candidates.append(Path(meipass).joinpath(*parts))
        candidates.append(exe_dir.joinpath(*parts))
        candidates.append(exe_dir.joinpath("_internal", *parts))
    else:
        root = app_dir()
        candidates.append(root.joinpath(*parts))
        candidates.append(Path(__file__).resolve().parent.joinpath(*parts))
        candidates.append(Path.cwd().joinpath(*parts))

    for path in candidates:
        if path.is_file() or path.exists():
            return path
    return candidates[0]
