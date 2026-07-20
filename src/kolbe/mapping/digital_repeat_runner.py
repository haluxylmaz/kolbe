"""Background-thread continuous Note On while a digital button or stick zone is held."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from kolbe.mapping.models import Mapping

logger = logging.getLogger(__name__)

DEFAULT_HOLD_INTERVAL_SEC = 0.05


def hold_session_key(mapping_id: str, zone: str = "") -> str:
    return f"{mapping_id}:{zone}" if zone else mapping_id


@dataclass
class _HoldSession:
    mapping: Mapping
    zone: str = ""
    is_holding: bool = True
    thread: Optional[threading.Thread] = None


class DigitalRepeatRunner(QObject):
    """Repeated Note On via a daemon thread; MIDI output is dispatched on the Qt main thread."""

    fire_requested = pyqtSignal(object, str)

    def __init__(
        self,
        fire: Callable[[Mapping, str], None],
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._fire = fire
        self.fire_requested.connect(self._on_fire_requested)
        self._sessions: dict[str, _HoldSession] = {}
        self._lock = threading.Lock()
        self._fire_blocked = False

    def is_active(self, mapping_id: str, *, zone: str = "") -> bool:
        key = hold_session_key(mapping_id, zone)
        with self._lock:
            session = self._sessions.get(key)
            return session is not None and session.is_holding

    def start(self, mapping: Mapping, *, zone: str = "") -> None:
        key = hold_session_key(mapping.id, zone)
        if self.is_active(mapping.id, zone=zone):
            return

        self.stop(mapping.id, zone=zone)

        session = _HoldSession(mapping=mapping, zone=zone, is_holding=True)
        thread = threading.Thread(
            target=self._hold_loop,
            args=(session,),
            name=f"kolbe-hold-{key[:12]}",
            daemon=True,
        )
        session.thread = thread

        with self._lock:
            self._sessions[key] = session

        self._fire(mapping, zone)
        thread.start()

    def stop(self, mapping_id: str, *, zone: str = "") -> None:
        key = hold_session_key(mapping_id, zone)
        with self._lock:
            session = self._sessions.pop(key, None)

        if session is None:
            return

        session.is_holding = False
        thread = session.thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=1.0)

    def stop_zones_for_mapping(self, mapping_id: str) -> None:
        for zone in ("neg", "pos"):
            self.stop(mapping_id, zone=zone)
        self.stop(mapping_id)

    def stop_all(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()

        for session in sessions:
            session.is_holding = False
            thread = session.thread
            if thread is not None and thread.is_alive() and thread is not threading.current_thread():
                thread.join(timeout=1.0)

    def block_fires(self, blocked: bool = True) -> None:
        self._fire_blocked = blocked

    def _on_fire_requested(self, mapping: Mapping, zone: str) -> None:
        if self._fire_blocked:
            return
        self._fire(mapping, zone)

    def _hold_loop(self, session: _HoldSession) -> None:
        while session.is_holding:
            time.sleep(DEFAULT_HOLD_INTERVAL_SEC)
            if not session.is_holding:
                break
            with self._lock:
                key = hold_session_key(session.mapping.id, session.zone)
                still_active = session.is_holding and key in self._sessions
            if still_active and not self._fire_blocked:
                self.fire_requested.emit(session.mapping, session.zone)
