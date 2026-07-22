"""Multi-controller manager — polls all connected gamepads concurrently."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import replace
from typing import Optional

from kolbe.controller.detector import detect_controllers
from kolbe.controller.manager import ControllerManager
from kolbe.controller.pygame_backend import PygameController
from kolbe.controller.types import ControllerDevice, ControllerState

logger = logging.getLogger(__name__)

# Owned pads must be missing from scan AND unhealthy for this many refreshes
# before we tear them down (~2s * 8 = 16s). Prevents phantom HID unplug drops.
_DISCONNECT_MISS_THRESHOLD = 8
# Back off reconnect attempts after Access Denied / CreateDevice failures.
_CONNECT_BACKOFF_SEC = 5.0
# Poll exceptions must persist before a hard disconnect.
_POLL_FAIL_THRESHOLD = 30


class MultiControllerManager:
    """Manages multiple controller backends simultaneously without clobbering each other."""

    def __init__(self) -> None:
        self._managers: dict[str, ControllerManager] = {}
        self._devices: dict[str, ControllerDevice] = {}
        self._miss_counts: dict[str, int] = {}
        self._poll_fail_counts: dict[str, int] = {}
        self._connect_fail_until: dict[str, float] = {}
        self._connect_fail_logged: set[str] = set()
        # Once multi-pad pygame mode has been entered, keep forcing pygame for
        # new PS pads until everything disconnects (avoids dualsense↔pygame thrash).
        self._multi_pad_pygame_sticky = False
        # hardware_id → (r,g,b) or None to dim. Applied on the poll thread.
        self._pending_leds: dict[str, Optional[tuple[int, int, int]]] = {}
        self._led_lock = threading.Lock()

    @property
    def devices(self) -> dict[str, ControllerDevice]:
        return dict(self._devices)

    @property
    def connected_ids(self) -> list[str]:
        return list(self._devices.keys())

    def _owned_pygame_indices(self) -> set[int]:
        indices: set[int] = set()
        for device in self._devices.values():
            # Protect every owned SDL index — never re-init during detect.
            if device.pygame_index is not None:
                indices.add(device.pygame_index)
        return indices

    def _stabilize_backends(self, detected: list[ControllerDevice]) -> list[ControllerDevice]:
        """
        With 2+ pads (or sticky multi-pad mode), force pygame for everyone.

        HID backends (pydualsense / exclusive DS4) frequently steal or starve
        sibling devices under Windows multi-controller.

        Gyro/accel/touch are restored via PlayStationSensorCompanion on pygame
        managers. Already-connected pads keep their live backend (see refresh).
        """
        force_pygame = len(detected) > 1 or self._multi_pad_pygame_sticky
        if not force_pygame:
            return detected

        if len(detected) > 1:
            self._multi_pad_pygame_sticky = True

        stabilized: list[ControllerDevice] = []
        for device in detected:
            if device.backend != "pygame":
                logger.debug(
                    "Multi-pad mode: prefer pygame for %s (detector said %s)",
                    device.name,
                    device.backend,
                )
                device = replace(device, backend="pygame")
            stabilized.append(device)
        return stabilized

    @staticmethod
    def _is_access_denied(exc: BaseException) -> bool:
        text = str(exc).lower()
        return (
            "0x80004005" in text
            or "createdevice" in text
            or "access is denied" in text
            or "access denied" in text
            or "lost pygame binding" in text
        )

    def _find_connected_id(self, device: ControllerDevice) -> Optional[str]:
        """Match an already-connected pad by stable hardware id or GUID."""
        if device.id in self._managers:
            return device.id
        guid = (device.guid or "").strip()
        if not guid:
            return None
        for connected_id, connected in self._devices.items():
            if (connected.guid or "").strip() == guid:
                return connected_id
        return None

    def _manager_is_healthy(self, device_id: str) -> bool:
        manager = self._managers.get(device_id)
        if manager is None or not manager.is_connected:
            return False
        backend = getattr(manager, "_backend", None)
        if isinstance(backend, PygameController):
            return backend.is_alive()
        return True

    def refresh(self) -> tuple[list[str], list[str]]:
        """
        Connect new devices and disconnect removed ones.

        Already-connected pads are NEVER re-initialized on a routine rescan.
        Their SDL indices are not re-init'd (that stole handles and caused
        phantom disconnects). Removal requires sustained absence + unhealthy.
        """
        owned_indices = self._owned_pygame_indices()
        known = list(self._devices.values())
        detected = detect_controllers(
            release_after_probe=False,
            keep_open_indices=owned_indices,
            known_devices=known,
        )
        detected = self._stabilize_backends(detected)
        detected_by_id = {device.id: device for device in detected}

        # Map each detection to an existing manager when GUID matches even if the
        # string id drifted (name localization / index-only ids).
        detected_to_connected: dict[str, str] = {}
        for device in detected:
            existing = self._find_connected_id(device)
            if existing is not None:
                detected_to_connected[device.id] = existing

        connected_seen: set[str] = set(detected_to_connected.values())

        # Healthy owned pads count as present even if the OS scan glitched.
        for device_id in list(self._managers.keys()):
            if device_id in connected_seen:
                continue
            if self._manager_is_healthy(device_id):
                connected_seen.add(device_id)
                logger.debug(
                    "Device %s absent from scan but pygame handle healthy — keeping",
                    device_id,
                )

        for connected_id in connected_seen:
            self._miss_counts.pop(connected_id, None)

        removed: list[str] = []
        for device_id in sorted(set(self._devices.keys()) - connected_seen):
            misses = self._miss_counts.get(device_id, 0) + 1
            self._miss_counts[device_id] = misses
            healthy = self._manager_is_healthy(device_id)
            if healthy or misses < _DISCONNECT_MISS_THRESHOLD:
                logger.debug(
                    "Device %s missing from scan (%d/%d, healthy=%s) — keeping",
                    device_id,
                    misses,
                    _DISCONNECT_MISS_THRESHOLD,
                    healthy,
                )
                continue
            logger.info(
                "Removing %s after %d missed scans and unhealthy handle",
                device_id,
                misses,
            )
            removed.append(device_id)

        for device_id in removed:
            self._disconnect_device(device_id)

        # Soft-update already-connected pads — never reconnect for backend mismatch.
        for detected_id, connected_id in detected_to_connected.items():
            device = detected_by_id[detected_id]
            manager = self._managers.get(connected_id)
            if manager is None:
                continue
            current = manager.device
            if current is not None:
                device = replace(
                    device,
                    id=connected_id,
                    backend=current.backend,
                )
            self._devices[connected_id] = device
            manager.update_device_metadata(device)

        now = time.monotonic()
        added: list[str] = []
        for device_id, device in sorted(detected_by_id.items()):
            if self._find_connected_id(device) is not None:
                continue
            fail_until = self._connect_fail_until.get(device_id, 0.0)
            if now < fail_until:
                continue
            manager = ControllerManager()
            try:
                manager.connect_device(device)
            except Exception as exc:
                if self._is_access_denied(exc):
                    self._connect_fail_until[device_id] = now + _CONNECT_BACKOFF_SEC
                    if device_id not in self._connect_fail_logged:
                        self._connect_fail_logged.add(device_id)
                        logger.warning(
                            "Could not connect %s (HID access clash) — "
                            "backing off %.0fs: %s",
                            device.name,
                            _CONNECT_BACKOFF_SEC,
                            exc,
                        )
                    else:
                        logger.debug(
                            "Still cannot connect %s (backoff active): %s",
                            device.name,
                            exc,
                        )
                else:
                    logger.warning("Could not connect %s: %s", device.name, exc)
                continue
            self._connect_fail_until.pop(device_id, None)
            self._connect_fail_logged.discard(device_id)
            self._managers[device_id] = manager
            self._devices[device_id] = device
            added.append(device_id)
            logger.info(
                "Multi-controller connected: %s (%s, backend=%s, guid=%s, instance=%s)",
                device.name,
                device_id,
                device.backend,
                device.guid,
                device.instance_id,
            )

        if not self._managers:
            self._multi_pad_pygame_sticky = False

        return added, removed

    def apply_slot_leds(
        self, colors_by_hardware_id: dict[str, Optional[tuple[int, int, int]]]
    ) -> None:
        """
        Queue lightbar colors for connected pads (thread-safe).

        Missing connected ids are dimmed to (0,0,0). None value also dims.
        Flushed on the controller poll thread via ``flush_pending_leds``.
        """
        with self._led_lock:
            self._pending_leds = dict(colors_by_hardware_id)
            for device_id in self._managers:
                if device_id not in self._pending_leds:
                    self._pending_leds[device_id] = (0, 0, 0)

    def flush_pending_leds(self) -> None:
        """Apply queued LED colors on the worker thread (non-blocking writes)."""
        with self._led_lock:
            pending = self._pending_leds
            self._pending_leds = {}
        if not pending:
            return
        for device_id, color in pending.items():
            manager = self._managers.get(device_id)
            if manager is None:
                continue
            if color is None:
                r = g = b = 0
            else:
                r, g, b = color
            try:
                manager.set_led(r, g, b)
            except Exception:
                logger.debug("set_led failed for %s", device_id, exc_info=True)

    def poll_all(self, pump_events: bool = False) -> list[ControllerState]:
        """Poll every connected pad independently; one failure does not stop others."""
        self.flush_pending_leds()
        states: list[ControllerState] = []
        dead: list[str] = []
        for device_id, manager in list(self._managers.items()):
            try:
                state = manager.poll(pump_events=pump_events)
                self._poll_fail_counts.pop(device_id, None)
                # Hard guarantee: emitted hardware id matches the manager key.
                if state.device.id != device_id:
                    logger.error(
                        "State id mismatch: manager=%s state=%s — dropping frame",
                        device_id,
                        state.device.id,
                    )
                    continue
                states.append(state)
            except Exception as exc:
                fails = self._poll_fail_counts.get(device_id, 0) + 1
                self._poll_fail_counts[device_id] = fails
                if self._is_access_denied(exc) or fails < _POLL_FAIL_THRESHOLD:
                    logger.debug(
                        "Poll issue for %s (%d/%d) — keeping connection: %s",
                        device_id,
                        fails,
                        _POLL_FAIL_THRESHOLD,
                        exc,
                    )
                    continue
                logger.exception(
                    "Poll failed for %s %d times — marking disconnected",
                    device_id,
                    fails,
                )
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
        self._miss_counts.pop(device_id, None)
        self._poll_fail_counts.pop(device_id, None)
        if manager is not None:
            try:
                manager.shutdown()
            except Exception:
                logger.exception("Error shutting down %s", device_id)
        if device is not None:
            logger.info("Multi-controller disconnected: %s", device.name)
        if not self._managers:
            self._multi_pad_pygame_sticky = False
