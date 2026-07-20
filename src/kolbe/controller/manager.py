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

        devices = detect_controllers()
        if not devices:
            raise RuntimeError("No gamepads detected. Connect a controller and try again.")
        if self._device_index >= len(devices):
            raise RuntimeError(
                f"Controller index {self._device_index} out of range "
                f"(found {len(devices)} device(s))."
            )

        self.disconnect()
        self._device = devices[self._device_index]
        self._backend = self._create_backend(self._device)
        self._backend.open()
        return self._device

    def disconnect(self) -> None:
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
        if isinstance(self._backend, PygameController):
            return self._backend.poll(pump_events=pump_events)
        return self._backend.poll()

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
