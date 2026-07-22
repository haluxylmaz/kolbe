"""Global registry of open HID handles — guarantees release on app exit.

A leaked hidapi handle (or a hung controller worker thread that keeps
open/close cycling) will make Windows play USB connect/disconnect sounds
even after the Kolbe window is closed. Every companion / DS4 HID opener
must register here so ``force_close_all_hid_handles`` can tear them down.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_closers: set[Callable[[], None]] = set()
_forced = False


def register_hid_closer(closer: Callable[[], None]) -> None:
    with _lock:
        _closers.add(closer)


def unregister_hid_closer(closer: Callable[[], None]) -> None:
    with _lock:
        _closers.discard(closer)


def force_close_all_hid_handles() -> None:
    """Best-effort close of every registered HID handle. Safe to call repeatedly."""
    global _forced
    with _lock:
        closers = list(_closers)
        _closers.clear()
        _forced = True
    if not closers:
        return
    logger.info("Force-closing %d HID handle(s)", len(closers))
    for closer in closers:
        try:
            closer()
        except Exception:
            logger.debug("HID closer failed during force shutdown", exc_info=True)


def was_force_closed() -> bool:
    return _forced
