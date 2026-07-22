"""DualShock 4 HID backend — accurate buttons, motion, touchpad."""

from __future__ import annotations

import logging
from typing import Optional

from kolbe.controller.ds4_hid import (
    DS4ConnectionType,
    DS4HidDeviceInfo,
    enable_ds4_input_streaming,
    find_ds4_hid_device,
    has_hidapi,
    parse_ds4_input_report,
    read_ds4_hid_report,
    sony_product_id_from_guid,
)
from kolbe.controller.touchpad_smoother import TouchpadSmoother
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
        self._reenable_attempted = False
        self._empty_polls = 0
        self._lifecycle_closer: Optional[object] = None
        self._last_led: Optional[tuple[int, int, int]] = None

    def open(self) -> None:
        if not has_hidapi():
            raise RuntimeError("hidapi is required for DualShock 4. Install with: pip install hidapi")

        import hid

        preferred = sony_product_id_from_guid(self.device.guid)
        self._hid_info = find_ds4_hid_device(preferred_product_id=preferred)
        if self._hid_info is None:
            raise RuntimeError("DualShock 4 HID device not found. Unplug other Sony tools and retry.")

        self._hid = hid.device()
        self._hid.open_path(self._hid_info.path)
        self._hid.set_nonblocking(True)
        enable_ds4_input_streaming(self._hid, self._hid_info.connection_type)

        from kolbe.controller.hid_lifecycle import register_hid_closer

        self._lifecycle_closer = self.close
        register_hid_closer(self._lifecycle_closer)  # type: ignore[arg-type]

        self.device.backend = "dualshock4"
        logger.info(
            "Opened DualShock 4 HID backend: %s (%s)",
            self._hid_info.product_string,
            self._hid_info.connection_type.value,
        )

    def close(self) -> None:
        if self._closed and self._hid is None:
            return
        self._closed = True
        closer = self._lifecycle_closer
        self._lifecycle_closer = None
        if closer is not None:
            try:
                from kolbe.controller.hid_lifecycle import unregister_hid_closer

                unregister_hid_closer(closer)  # type: ignore[arg-type]
            except Exception:
                pass
        logger.info("Closing DualShock 4 backend")
        hid_dev = self._hid
        self._hid = None
        if hid_dev is not None:
            try:
                hid_dev.close()
            except Exception:
                logger.exception("Error closing DS4 HID device")
        self._hid_info = None
        self._last_report = None

    def set_led(self, r: int, g: int, b: int) -> bool:
        if self._closed or self._hid is None or self._hid_info is None:
            return False
        color = (max(0, min(255, int(r))), max(0, min(255, int(g))), max(0, min(255, int(b))))
        if self._last_led == color:
            return True
        from kolbe.controller.ps_led import set_led_on_device

        ok = set_led_on_device(
            self._hid,
            kind="ds4",
            connection_type=self._hid_info.connection_type,
            r=color[0],
            g=color[1],
            b=color[2],
        )
        if ok:
            self._last_led = color
        return ok

    def shutdown(self) -> None:
        try:
            self.set_led(0, 0, 0)
        except Exception:
            pass
        self.close()

    def poll(self) -> ControllerState:
        if self._closed or self._hid is None:
            return ControllerState(device=self.device)

        report = read_ds4_hid_report(self._hid)
        if report is None:
            self._empty_polls += 1
            if (
                not self._reenable_attempted
                and self._empty_polls >= 10
                and self._hid_info is not None
            ):
                self._reenable_attempted = True
                try:
                    enable_ds4_input_streaming(self._hid, self._hid_info.connection_type)
                except Exception:
                    logger.debug("DS4 backend deferred re-enable failed", exc_info=True)
            if self._last_report is None:
                return ControllerState(device=self.device)
        else:
            self._empty_polls = 0
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

        usb = (
            self._hid_info is not None
            and self._hid_info.connection_type == DS4ConnectionType.USB
        )
        if usb:
            batt_percent = None
            batt_label = "Wired"
        elif parsed.battery_percent is not None:
            batt_percent = parsed.battery_percent
            batt_label = f"{parsed.battery_percent}%"
        else:
            batt_percent = None
            batt_label = "Wired"

        return ControllerState(
            device=self.device,
            buttons=dict(parsed.buttons),
            axes=axes,
            touchpad=touchpad,
            gyro=dict(parsed.gyro),
            accelerometer=dict(parsed.accelerometer),
            battery_percent=batt_percent,
            battery_label=batt_label,
        )
