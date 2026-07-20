"""DualShock 4 HID backend — accurate buttons, motion, touchpad."""

from __future__ import annotations

import logging
import time
from typing import Optional

from kolbe.controller.touchpad_smoother import TouchpadSmoother
from kolbe.controller.ds4_hid import (
    DS4ConnectionType,
    DS4HidDeviceInfo,
    build_bt_enable_report,
    find_ds4_hid_device,
    has_hidapi,
    parse_ds4_input_report,
)
from kolbe.controller.types import (
    ControllerDevice,
    ControllerState,
    InputSource,
)

logger = logging.getLogger(__name__)


class DualShock4Controller:
    """Reads DualShock 4 via raw HID reports (bypasses pygame/SDL on macOS)."""

    def __init__(self, device: ControllerDevice) -> None:
        self.device = device
        self._hid: Optional[object] = None
        self._hid_info: Optional[DS4HidDeviceInfo] = None
        self._last_report: Optional[bytes] = None
        self._touchpad_smoother = TouchpadSmoother()
        self._closed = False

    def open(self) -> None:
        if not has_hidapi():
            raise RuntimeError("hidapi is required for DualShock 4. Install with: pip install hidapi")

        import hid

        self._hid_info = find_ds4_hid_device()
        if self._hid_info is None:
            raise RuntimeError("DualShock 4 HID device not found. Unplug other Sony tools and retry.")

        self._hid = hid.device()
        self._hid.open_path(self._hid_info.path)
        self._hid.set_nonblocking(True)

        if self._hid_info.connection_type == DS4ConnectionType.BLUETOOTH:
            try:
                self._hid.write(build_bt_enable_report())
                time.sleep(0.05)
            except OSError:
                logger.warning("Failed to send DS4 BT enable report", exc_info=True)

        self.device.backend = "dualshock4"
        logger.info(
            "Opened DualShock 4 HID backend: %s (%s)",
            self._hid_info.product_string,
            self._hid_info.connection_type.value,
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        logger.info("Closing DualShock 4 backend")
        hid = self._hid
        self._hid = None
        if hid is not None:
            try:
                hid.close()
            except OSError:
                logger.exception("Error closing DS4 HID device")
        self._hid_info = None
        self._last_report = None

    def shutdown(self) -> None:
        self.close()

    def poll(self) -> ControllerState:
        if self._closed or self._hid is None:
            return ControllerState(device=self.device)

        report = self._read_latest_report()
        if report is None and self._last_report is None:
            return ControllerState(device=self.device)

        if report is not None:
            self._last_report = report

        parsed = parse_ds4_input_report(self._last_report or b"")
        if parsed is None:
            return ControllerState(device=self.device)

        raw_touchpad = parsed.touchpad if parsed.touchpad else []
        touchpad = self._touchpad_smoother.process_pair(raw_touchpad)

        axes = dict(parsed.axes)
        if touchpad[0].active:
            axes[InputSource.TOUCHPAD_0_X.value] = touchpad[0].x
            axes[InputSource.TOUCHPAD_0_Y.value] = touchpad[0].y
        if touchpad[1].active:
            axes[InputSource.TOUCHPAD_1_X.value] = touchpad[1].x
            axes[InputSource.TOUCHPAD_1_Y.value] = touchpad[1].y

        return ControllerState(
            device=self.device,
            buttons=dict(parsed.buttons),
            axes=axes,
            touchpad=touchpad,
            gyro=dict(parsed.gyro),
            accelerometer=dict(parsed.accelerometer),
            battery_percent=parsed.battery_percent,
        )

    def _read_latest_report(self) -> Optional[bytes]:
        if self._hid is None:
            return None
        latest: Optional[bytes] = None
        try:
            while True:
                chunk = self._hid.read(128)
                if not chunk:
                    break
                latest = bytes(chunk)
        except OSError:
            logger.debug("DS4 HID read error", exc_info=True)
        return latest
