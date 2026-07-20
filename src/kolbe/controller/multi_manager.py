"""Multi-controller manager — polls all connected gamepads."""

from __future__ import annotations

import logging
from typing import Optional

from kolbe.controller.detector import detect_controllers
from kolbe.controller.manager import ControllerManager
from kolbe.controller.types import ControllerDevice, ControllerState

logger = logging.getLogger(__name__)


class MultiControllerManager:
    """Manages multiple controller backends simultaneously."""

    def __init__(self) -> None:
        self._managers: dict[str, ControllerManager] = {}
        self._devices: dict[str, ControllerDevice] = {}

    @property
    def devices(self) -> dict[str, ControllerDevice]:
        return dict(self._devices)

    @property
    def connected_ids(self) -> list[str]:
        return list(self._devices.keys())

    def refresh(self) -> tuple[list[str], list[str]]:
        """Connect new devices and disconnect removed ones. Returns (added, removed) ids."""
        detected = detect_controllers()
        detected_ids = {device.id for device in detected}
        current_ids = set(self._devices.keys())

        added = [device_id for device_id in detected_ids if device_id not in current_ids]
        removed = [device_id for device_id in current_ids if device_id not in detected_ids]

        for device_id in removed:
            self._disconnect_device(device_id)

        id_to_device = {device.id: device for device in detected}
        for device_id in added:
            device = id_to_device[device_id]
            index = next(i for i, d in enumerate(detected) if d.id == device_id)
            manager = ControllerManager(device_index=index)
            try:
                manager.connect(device_index=index)
            except RuntimeError as exc:
                logger.warning("Could not connect %s: %s", device.name, exc)
                continue
            self._managers[device_id] = manager
            self._devices[device_id] = device
            logger.info("Multi-controller connected: %s (%s)", device.name, device_id)

        return added, removed

    def poll_all(self, pump_events: bool = False) -> list[ControllerState]:
        states: list[ControllerState] = []
        for device_id, manager in list(self._managers.items()):
            try:
                states.append(manager.poll(pump_events=pump_events))
            except Exception:
                logger.exception("Poll failed for %s", device_id)
        return states

    def shutdown(self) -> None:
        for device_id in list(self._managers.keys()):
            self._disconnect_device(device_id)

    def _disconnect_device(self, device_id: str) -> None:
        manager = self._managers.pop(device_id, None)
        device = self._devices.pop(device_id, None)
        if manager is not None:
            manager.shutdown()
        if device is not None:
            logger.info("Multi-controller disconnected: %s", device.name)
