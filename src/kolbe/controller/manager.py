"""Unified controller manager — selects backend and polls state."""

from __future__ import annotations

import logging
from typing import Optional, Protocol, runtime_checkable

from kolbe.controller.detector import (
    detect_controllers,
    has_dualsense_backend_available,
    has_dualshock4_backend_available,
)
from kolbe.controller.dualsense_backend import DualSenseController
from kolbe.controller.dualshock4_backend import DualShock4Controller
from kolbe.controller.ps_sensor_companion import PlayStationSensorCompanion
from kolbe.controller.pygame_backend import PygameController
from kolbe.controller.types import ControllerDevice, ControllerState, ControllerType

logger = logging.getLogger(__name__)


@runtime_checkable
class ControllerBackend(Protocol):
    device: ControllerDevice

    def open(self) -> None: ...
    def close(self) -> None: ...
    def poll(self) -> ControllerState: ...


class ControllerManager:
    """Manages controller detection, connection, and polling."""

    def __init__(self, device_index: int = 0) -> None:
        self._device_index = device_index
        self._backend: Optional[ControllerBackend] = None
        self._sensors: Optional[PlayStationSensorCompanion] = None
        self._device: Optional[ControllerDevice] = None

    @property
    def device(self) -> Optional[ControllerDevice]:
        return self._device

    @property
    def is_connected(self) -> bool:
        return self._backend is not None

    @staticmethod
    def list_devices() -> list[ControllerDevice]:
        return detect_controllers()

    def connect(self, device_index: Optional[int] = None) -> ControllerDevice:
        if device_index is not None:
            self._device_index = device_index

        devices = detect_controllers(release_after_probe=False)
        if not devices:
            raise RuntimeError("No gamepads detected. Connect a controller and try again.")
        if self._device_index >= len(devices):
            raise RuntimeError(
                f"Controller index {self._device_index} out of range "
                f"(found {len(devices)} device(s))."
            )
        return self.connect_device(devices[self._device_index])

    def connect_device(self, device: ControllerDevice) -> ControllerDevice:
        """Open a specific detected device without re-enumerating (multi-pad safe)."""
        self.disconnect()
        self._device = device
        if device.pygame_index is not None:
            self._device_index = device.pygame_index
        self._backend = self._create_backend(device)
        self._backend.open()
        # Attach companion AFTER pygame/SDL HIDAPI has claimed the joystick so
        # Windows share modes line up (SDL first, hidapi read-only second).
        self._attach_sensor_companion(device)
        return self._device

    def update_device_metadata(self, device: ControllerDevice) -> None:
        """Refresh pygame index / identity after a hotplug rescan without reopening HID."""
        if self._device is None or self._device.id != device.id:
            return
        prev_guid = self._device.guid
        prev_index = self._device.pygame_index
        self._device = device
        backend = self._backend
        if hasattr(backend, "device"):
            backend.device = device  # type: ignore[union-attr]
        if self._sensors is not None:
            self._sensors.device = device
        if device.pygame_index is not None:
            self._device_index = device.pygame_index
        if isinstance(backend, PygameController):
            # Soft rebind only when the SDL index/GUID actually changed.
            # Forcing open() every 2s re-ran CreateDevice and amplified
            # hotplug thrash while the HID companion was open.
            bound_index = getattr(backend, "_bound_index", None)
            needs_rebind = (
                bound_index is None
                or device.pygame_index != prev_index
                or (device.guid and device.guid != prev_guid)
            )
            if needs_rebind:
                try:
                    backend.open()
                except Exception as exc:
                    logger.warning(
                        "Deferred pygame rebind for %s (keeping prior handle): %s",
                        device.name,
                        exc,
                    )

    def disconnect(self) -> None:
        self._close_sensors()
        if self._backend is not None:
            logger.info("Disconnecting controller backend")
            if hasattr(self._backend, "shutdown"):
                self._backend.shutdown()  # type: ignore[union-attr]
            else:
                self._backend.close()
            self._backend = None
        self._device = None

    def shutdown(self) -> None:
        self.disconnect()

    def poll(self, pump_events: bool = True) -> ControllerState:
        if self._backend is None:
            raise RuntimeError("No controller connected")
        try:
            if isinstance(self._backend, PygameController):
                state = self._backend.poll(pump_events=pump_events)
            else:
                state = self._backend.poll()
        except Exception:
            logger.debug("Backend poll failed for %s", getattr(self._device, "name", "?"), exc_info=True)
            raise
        if self._sensors is not None:
            try:
                state = self._sensors.merge_into(state)
            except Exception:
                # Sensor HID glitches must never tear down button/axis routing.
                logger.debug(
                    "Sensor companion merge failed for %s — keeping pygame state",
                    getattr(self._device, "name", "?"),
                    exc_info=True,
                )
        return state

    def set_led(self, r: int, g: int, b: int) -> bool:
        """Set lightbar RGB on the active companion or HID backend (best-effort)."""
        if self._sensors is not None and hasattr(self._sensors, "set_led"):
            return bool(self._sensors.set_led(r, g, b))
        backend = self._backend
        if backend is not None and hasattr(backend, "set_led"):
            try:
                return bool(backend.set_led(r, g, b))  # type: ignore[attr-defined]
            except Exception:
                logger.debug("Backend set_led failed", exc_info=True)
                return False
        return False

    def _attach_sensor_companion(self, device: ControllerDevice) -> None:
        """
        When pygame is the primary backend for a PlayStation pad, attach a
        sensors-only HID companion so gyro/accel/touch still flow — without
        replacing pygame button/axis routing (multi-pad safe).
        """
        self._close_sensors()
        if not isinstance(self._backend, PygameController):
            return
        from kolbe.controller.ps_sensor_companion import device_wants_ps_sensors

        if not device_wants_ps_sensors(device):
            return
        companion = PlayStationSensorCompanion.try_open(device)
        if companion is not None:
            self._sensors = companion
            logger.info(
                "Sensor companion attached for %s (id=%s, guid=%s, type=%s)",
                device.name,
                device.id,
                device.guid,
                device.controller_type.value,
            )
        else:
            logger.warning(
                "No sensor companion for %s (type=%s, guid=%s) — gyro/accel empty",
                device.name,
                device.controller_type.value,
                device.guid,
            )

    def _close_sensors(self) -> None:
        if self._sensors is not None:
            try:
                if hasattr(self._sensors, "clear_led"):
                    self._sensors.clear_led()
            except Exception:
                pass
            try:
                self._sensors.close()
            except Exception:
                logger.debug("Error closing sensor companion", exc_info=True)
            self._sensors = None

    def _create_backend(self, device: ControllerDevice) -> ControllerBackend:
        if device.backend == "dualshock4" and has_dualshock4_backend_available():
            try:
                return DualShock4Controller(device)
            except Exception:
                logger.warning(
                    "DualShock 4 HID backend unavailable, falling back to pygame for %s",
                    device.name,
                    exc_info=True,
                )

        if (
            device.controller_type == ControllerType.DUALSENSE
            and device.backend == "dualsense"
            and has_dualsense_backend_available()
        ):
            try:
                return DualSenseController(device)
            except Exception:
                logger.warning(
                    "DualSense HID backend unavailable, falling back to pygame for %s",
                    device.name,
                    exc_info=True,
                )

        return PygameController(device)

    def __enter__(self) -> ControllerManager:
        self.connect()
        return self

    def __exit__(self, *args: object) -> None:
        self.disconnect()
