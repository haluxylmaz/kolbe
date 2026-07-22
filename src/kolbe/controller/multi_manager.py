"""Multi-controller manager — polls all connected gamepads concurrently."""

from __future__ import annotations

import logging
from dataclasses import replace

from kolbe.controller.detector import detect_controllers
from kolbe.controller.manager import ControllerManager
from kolbe.controller.types import ControllerDevice, ControllerState

logger = logging.getLogger(__name__)


class MultiControllerManager:
    """Manages multiple controller backends simultaneously without clobbering each other."""

    def __init__(self) -> None:
        self._managers: dict[str, ControllerManager] = {}
        self._devices: dict[str, ControllerDevice] = {}

    @property
    def devices(self) -> dict[str, ControllerDevice]:
        return dict(self._devices)

    @property
    def connected_ids(self) -> list[str]:
        return list(self._devices.keys())

    def _owned_pygame_indices(self) -> set[int]:
        indices: set[int] = set()
        for device in self._devices.values():
            if device.pygame_index is not None and device.backend == "pygame":
                indices.add(device.pygame_index)
        return indices

    @staticmethod
    def _stabilize_backends(detected: list[ControllerDevice]) -> list[ControllerDevice]:
        """
        With 2+ pads, force pygame for everyone.

        HID backends (pydualsense / exclusive DS4) frequently steal or starve
        sibling devices under Windows multi-controller, which presented as
        DualSense=dead while PS4 input leaked into the DualSense slot.
        """
        if len(detected) <= 1:
            return detected
        stabilized: list[ControllerDevice] = []
        for device in detected:
            if device.backend != "pygame":
                logger.info(
                    "Multi-pad mode: using pygame backend for %s (was %s)",
                    device.name,
                    device.backend,
                )
                device = replace(device, backend="pygame")
            stabilized.append(device)
        return stabilized

    def refresh(self) -> tuple[list[str], list[str]]:
        """
        Connect new devices and disconnect removed ones.

        Critical: never re-probe with ``joy.quit()`` on indices we already own —
        that was the multi-controller bug (second pad connect killed the first).
        """
        detected = detect_controllers(
            release_after_probe=False,
            keep_open_indices=self._owned_pygame_indices(),
        )
        detected = self._stabilize_backends(detected)
        detected_by_id = {device.id: device for device in detected}
        detected_ids = set(detected_by_id)
        current_ids = set(self._devices.keys())

        added = sorted(detected_ids - current_ids)
        removed = sorted(current_ids - detected_ids)

        for device_id in removed:
            self._disconnect_device(device_id)

        for device_id in sorted(current_ids & detected_ids):
            device = detected_by_id[device_id]
            self._devices[device_id] = device
            manager = self._managers.get(device_id)
            if manager is not None:
                # If backend kind changed (HID → pygame), reconnect that pad only.
                current = manager.device
                if current is not None and current.backend != device.backend:
                    logger.info("Rebinding %s to backend %s", device.name, device.backend)
                    try:
                        manager.connect_device(device)
                    except Exception:
                        logger.exception("Failed to rebind %s", device.name)
                        self._disconnect_device(device_id)
                        continue
                else:
                    manager.update_device_metadata(device)

        for device_id in added:
            device = detected_by_id[device_id]
            manager = ControllerManager()
            try:
                manager.connect_device(device)
            except Exception as exc:
                logger.warning("Could not connect %s: %s", device.name, exc)
                continue
            self._managers[device_id] = manager
            self._devices[device_id] = device
            logger.info(
                "Multi-controller connected: %s (%s, backend=%s, guid=%s, instance=%s)",
                device.name,
                device_id,
                device.backend,
                device.guid,
                device.instance_id,
            )

        return added, removed

    def poll_all(self, pump_events: bool = False) -> list[ControllerState]:
        """Poll every connected pad independently; one failure does not stop others."""
        states: list[ControllerState] = []
        dead: list[str] = []
        for device_id, manager in list(self._managers.items()):
            try:
                state = manager.poll(pump_events=pump_events)
                # Hard guarantee: emitted hardware id matches the manager key.
                if state.device.id != device_id:
                    logger.error(
                        "State id mismatch: manager=%s state=%s — dropping frame",
                        device_id,
                        state.device.id,
                    )
                    continue
                states.append(state)
            except Exception:
                logger.exception("Poll failed for %s — marking disconnected", device_id)
                dead.append(device_id)
        for device_id in dead:
            self._disconnect_device(device_id)
        return states

    def shutdown(self) -> None:
        for device_id in list(self._managers.keys()):
            self._disconnect_device(device_id)

    def _disconnect_device(self, device_id: str) -> None:
        manager = self._managers.pop(device_id, None)
        device = self._devices.pop(device_id, None)
        if manager is not None:
            try:
                manager.shutdown()
            except Exception:
                logger.exception("Error shutting down %s", device_id)
        if device is not None:
            logger.info("Multi-controller disconnected: %s", device.name)
