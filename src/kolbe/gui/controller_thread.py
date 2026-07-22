"""Background controller polling for Windows (high-rate SDL timing)."""

from __future__ import annotations

import logging
import time
from typing import Optional

from PyQt6.QtCore import QMutex, QObject, QThread, pyqtSignal

from kolbe.controller.multi_manager import MultiControllerManager
from kolbe.controller.types import ControllerState

logger = logging.getLogger(__name__)

POLL_RATE_HZ = 125
AXIS_EMIT_EPSILON = 0.012
DEVICE_REFRESH_SEC = 2.0


class PygameEventPump(QObject):
    """Initializes pygame/SDL once. Event pumping runs in ControllerWorker (Windows)."""

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)

    def start(self) -> None:
        import pygame

        if not pygame.get_init():
            pygame.init()
        if not pygame.joystick.get_init():
            pygame.joystick.init()
        logger.info("pygame initialized (event pump runs on controller worker thread)")

    def stop(self) -> None:
        return

    @staticmethod
    def shutdown_pygame() -> None:
        import pygame

        try:
            if pygame.joystick.get_init():
                pygame.joystick.quit()
        except pygame.error:
            logger.debug("pygame.joystick.quit failed", exc_info=True)
        try:
            if pygame.get_init():
                pygame.quit()
        except pygame.error:
            logger.debug("pygame.quit failed", exc_info=True)


class ControllerWorker(QObject):
    """Polls all controllers at a fixed Hz and emits per-device state changes."""

    state_updated = pyqtSignal(object)
    devices_changed = pyqtSignal(object)
    error_occurred = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self._running = False
        self._manager: Optional[MultiControllerManager] = None
        self._last_emitted: dict[str, ControllerState] = {}
        self._last_refresh_mono = 0.0
        self._force_refresh = False
        self._lock = QMutex()

    def request_refresh(self) -> None:
        """Ask the worker to rescan hardware on the next poll tick."""
        self._lock.lock()
        try:
            self._force_refresh = True
        finally:
            self._lock.unlock()

    def start_polling(self) -> None:
        import pygame

        self._running = True
        self._manager = MultiControllerManager()
        clock = pygame.time.Clock()
        try:
            self._manager.refresh()
            self.devices_changed.emit(self._manager.devices)
            self._last_refresh_mono = time.monotonic()
            if not self._manager.devices:
                logger.info("No controllers yet — will keep scanning")
        except RuntimeError as exc:
            self.error_occurred.emit(str(exc))
            self._running = False
            return

        while self._running:
            try:
                if self._manager is not None:
                    now = time.monotonic()
                    self._lock.lock()
                    force = self._force_refresh
                    self._force_refresh = False
                    self._lock.unlock()

                    if force or now - self._last_refresh_mono >= DEVICE_REFRESH_SEC:
                        self._last_refresh_mono = now
                        added, removed = self._manager.refresh()
                        if force or added or removed:
                            self._prune_emitted_cache(self._manager.connected_ids)
                            self.devices_changed.emit(self._manager.devices)

                    self._flush_sdl_event_queue()
                    # Each pad is polled independently — concurrent MIDI for all slots.
                    for state in self._manager.poll_all(pump_events=False):
                        self._emit_if_changed(state)
            except Exception as exc:
                logger.exception("Controller poll error")
                self.error_occurred.emit(str(exc))
                break

            clock.tick(POLL_RATE_HZ)

        self._cleanup()

    def stop_polling(self) -> None:
        self._running = False

    def _emit_if_changed(self, state: ControllerState) -> None:
        device_id = state.device.id
        previous = self._last_emitted.get(device_id)
        if previous is state:
            return
        if not state.significant_change_from(previous, axis_epsilon=AXIS_EMIT_EPSILON):
            return
        self._last_emitted[device_id] = state
        self.state_updated.emit(state)

    def _prune_emitted_cache(self, connected_ids: list[str]) -> None:
        keep = set(connected_ids)
        for device_id in list(self._last_emitted):
            if device_id not in keep:
                self._last_emitted.pop(device_id, None)

    @staticmethod
    def _flush_sdl_event_queue() -> None:
        try:
            import pygame

            if not pygame.get_init():
                return
            pygame.event.pump()
            pygame.event.clear()
        except Exception:
            logger.debug("pygame event flush failed", exc_info=True)

    def _cleanup(self) -> None:
        self._last_emitted.clear()
        if self._manager is not None:
            logger.info("Controller worker shutting down hardware")
            self._manager.shutdown()
            self._manager = None


class ControllerThread(QThread):
    """QThread wrapper around multi-device ControllerWorker."""

    state_updated = pyqtSignal(object)
    devices_changed = pyqtSignal(object)
    error_occurred = pyqtSignal(str)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._worker: Optional[ControllerWorker] = None

    def request_refresh(self) -> None:
        if self._worker is not None:
            self._worker.request_refresh()

    def run(self) -> None:
        self._worker = ControllerWorker()
        self._worker.state_updated.connect(self.state_updated.emit)
        self._worker.devices_changed.connect(self.devices_changed.emit)
        self._worker.error_occurred.connect(self.error_occurred.emit)
        self._worker.start_polling()

    def stop(self) -> None:
        logger.info("Stopping controller thread")
        if self._worker is not None:
            self._worker.stop_polling()
        self.quit()
        if not self.wait(8000):
            logger.warning("Controller thread did not finish within 8s")
        else:
            logger.info("Controller thread stopped")
