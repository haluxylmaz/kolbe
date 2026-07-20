"""Find and remove Python build/cache junk from the project tree."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

JUNK_DIR_NAMES = frozenset(
    {
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".tox",
        ".eggs",
    }
)

JUNK_FILE_SUFFIXES = (".pyc", ".pyo")

SKIP_DIR_NAMES = frozenset({".git", ".venv", "venv", "node_modules", ".cursor"})

BUILD_ARTIFACT_NAMES = frozenset({"build", "dist"})


def project_root() -> Path:
    """Return the writable app/project root (never the PyInstaller extract tree)."""
    from kolbe.paths import app_dir

    return app_dir()


def find_junk_paths(root: Optional[Path] = None) -> list[Path]:
    """Collect junk directories and files under *root*."""
    root = (root or project_root()).resolve()
    found: list[Path] = []

    for path in root.rglob("*"):
        if any(part in SKIP_DIR_NAMES for part in path.parts):
            continue

        if path.is_dir() and path.name in JUNK_DIR_NAMES:
            found.append(path)
            continue

        if path.is_file() and path.suffix in JUNK_FILE_SUFFIXES:
            found.append(path)

    for path in root.iterdir():
        if path.is_dir() and path.name in BUILD_ARTIFACT_NAMES:
            found.append(path)
        if path.is_dir() and path.name.endswith(".egg-info"):
            found.append(path)

    return sorted(set(found), key=lambda p: (len(p.parts), str(p)))


def cleanup_project(root: Optional[Path] = None) -> list[Path]:
    """Delete junk paths and return the list of removed entries.

    No-op when frozen — scanning ``_MEIPASS`` / Temp as a 'project root' is unsafe.
    """
    from kolbe.paths import is_frozen

    if is_frozen() and root is None:
        logger.info("Skipping project cleanup in frozen build")
        return []

    removed: list[Path] = []
    for path in find_junk_paths(root):
        try:
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
            removed.append(path)
            logger.info("Removed junk: %s", path)
        except OSError as exc:
            logger.warning("Could not remove %s: %s", path, exc)
    return removed
