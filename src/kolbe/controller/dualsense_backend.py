"""DualSense advanced sensor access via pydualsense."""

from __future__ import annotations

import logging
from typing import Optional

from kolbe.controller.axis_utils import normalize_trigger_axis
from kolbe.controller.touchpad_smoother import TouchpadSmoother, normalize_touch_axis
from kolbe.controller.types import (
    ControllerDevice,
    ControllerState,
    InputSource,
)

logger = logging.getLogger(__name__)

# DualSense / DS5 HID absolute touchpad resolution (pydualsense / Sony report).
_TOUCHPAD_MAX_X = 1920.0
_TOUCHPAD_MAX_Y = 1080.0


class DualSenseController:
    """Reads DualSense-specific sensors (gyro, accelerometer, touchpad)."""

    def __init__(self, device: ControllerDevice) -> None:
        self.device = device
        self._ds: Optional[object] = None
        self._running = False
        self._touchpad_smoother = TouchpadSmoother()
        self._last_led: Optional[tuple[int, int, int]] = None
        self._lifecycle_closer = None

    def open(self) -> None:
        try:
            from kolbe.hidapi_bootstrap import ensure_hidapi_loaded

            ensure_hidapi_loaded()
            from pydualsense import pydualsense
        except (ImportError, OSError) as exc:
            raise RuntimeError(
                "pydualsense / hidapi.dll is required for DualSense advanced sensors. "
                "Install with: pip install pydualsense"
            ) from exc

        self._ds = pydualsense()
        self._ds.init()
        self._running = True
        from kolbe.controller.hid_lifecycle import register_hid_closer

        self._lifecycle_closer = self.close
        register_hid_closer(self._lifecycle_closer)
        self._last_led = None
        logger.info("Opened DualSense HID backend: %s", self.device.name)

    def set_led(self, r: int, g: int, b: int) -> bool:
        if not self._running or self._ds is None:
            return False
        color = (max(0, min(255, int(r))), max(0, min(255, int(g))), max(0, min(255, int(b))))
        if self._last_led == color:
            return True
        try:
            light = getattr(self._ds, "light", None)
            if light is not None and hasattr(light, "setColorI"):
                light.setColorI(color[0], color[1], color[2])
                self._last_led = color
                return True
        except Exception:
            logger.debug("DualSense set_led failed", exc_info=True)
        return False

    def close(self) -> None:
        try:
            self.set_led(0, 0, 0)
        except Exception:
            pass
        self._running = False
        closer = getattr(self, "_lifecycle_closer", None)
        self._lifecycle_closer = None
        if closer is not None:
            try:
                from kolbe.controller.hid_lifecycle import unregister_hid_closer

                unregister_hid_closer(closer)
            except Exception:
                pass
        ds = self._ds
        self._ds = None
        if ds is not None:
            try:
                ds.close()
            except Exception:
                logger.exception("Error closing DualSense connection")

    def shutdown(self) -> None:
        self.close()

    def poll(self) -> ControllerState:
        if not self._running or self._ds is None:
            return ControllerState(device=self.device)

        state = self._ds.state

        buttons = {
            InputSource.CROSS.value: bool(state.cross),
            InputSource.CIRCLE.value: bool(state.circle),
            InputSource.SQUARE.value: bool(state.square),
            InputSource.TRIANGLE.value: bool(state.triangle),
            InputSource.L1.value: bool(state.L1),
            InputSource.R1.value: bool(state.R1),
            InputSource.L3.value: bool(state.L3),
            InputSource.R3.value: bool(state.R3),
            InputSource.SHARE.value: bool(state.share),
            InputSource.OPTIONS.value: bool(state.options),
            InputSource.PS.value: bool(state.ps),
            InputSource.TOUCHPAD_CLICK.value: bool(state.touchBtn),
            InputSource.MICROPHONE.value: bool(state.micBtn),
            InputSource.DPAD_UP.value: bool(state.DpadUp),
            InputSource.DPAD_DOWN.value: bool(state.DpadDown),
            InputSource.DPAD_LEFT.value: bool(state.DpadLeft),
            InputSource.DPAD_RIGHT.value: bool(state.DpadRight),
        }

        axes = {
            InputSource.LEFT_STICK_X.value: _normalize_stick(state.LX),
            InputSource.LEFT_STICK_Y.value: _normalize_stick(state.LY),
            InputSource.RIGHT_STICK_X.value: _normalize_stick(state.RX),
            InputSource.RIGHT_STICK_Y.value: _normalize_stick(state.RY),
            InputSource.L2.value: normalize_trigger_axis(state.L2_value / 255.0, bipolar=False),
            InputSource.R2.value: normalize_trigger_axis(state.R2_value / 255.0, bipolar=False),
        }

        touch0 = state.trackPadTouch0
        touch1 = state.trackPadTouch1
        raw_points = [
            self._raw_touch_tuple(touch0),
            self._raw_touch_tuple(touch1),
        ]
        touchpad = self._touchpad_smoother.process_pair(raw_points)

        # Only expose live fingers as analog axes. Inactive slots keep last XY on
        # ControllerState.touchpad for UI, without zeroing / spiking MIDI axes.
        if touchpad[0].active:
            axes[InputSource.TOUCHPAD_0_X.value] = touchpad[0].x
            axes[InputSource.TOUCHPAD_0_Y.value] = touchpad[0].y
        if touchpad[1].active:
            axes[InputSource.TOUCHPAD_1_X.value] = touchpad[1].x
            axes[InputSource.TOUCHPAD_1_Y.value] = touchpad[1].y

        gyro = {
            InputSource.GYRO_PITCH.value: float(state.gyro.Pitch),
            InputSource.GYRO_YAW.value: float(state.gyro.Yaw),
            InputSource.GYRO_ROLL.value: float(state.gyro.Roll),
        }

        accelerometer = {
            InputSource.ACCEL_X.value: float(state.accelerometer.X),
            InputSource.ACCEL_Y.value: float(state.accelerometer.Y),
            InputSource.ACCEL_Z.value: float(state.accelerometer.Z),
        }

        battery = None
        battery_label = None
        # Prefer cable/charging state from pydualsense when available.
        state_name = ""
        if hasattr(self._ds, "battery"):
            batt = self._ds.battery
            if hasattr(batt, "State"):
                state_name = str(getattr(batt, "State", "") or "").lower()
            if hasattr(batt, "Level"):
                raw = int(batt.Level)
                # pydualsense reports 0–10 steps; normalize to percent when needed.
                battery = raw * 10 if raw <= 10 else min(raw, 100)
                battery_label = f"{battery}%"
        if any(token in state_name for token in ("charging", "full", "wired", "cable")):
            battery = None
            battery_label = "Wired"
        elif battery is None:
            battery_label = "Wired"

        return ControllerState(
            device=self.device,
            buttons=buttons,
            axes=axes,
            touchpad=touchpad,
            gyro=gyro,
            accelerometer=accelerometer,
            battery_percent=battery,
            battery_label=battery_label,
        )

    @staticmethod
    def _raw_touch_tuple(touch: object) -> tuple[bool, float, float, int]:
        active = bool(getattr(touch, "isActive", False))
        finger_id = int(getattr(touch, "ID", 0)) & 0x7F
        # When inactive the HID report often already cleared X/Y to 0 — ignore those.
        if not active:
            return False, 0.0, 0.0, finger_id
        x = normalize_touch_axis(getattr(touch, "X", 0), _TOUCHPAD_MAX_X)
        y = normalize_touch_axis(getattr(touch, "Y", 0), _TOUCHPAD_MAX_Y)
        return True, x, y, finger_id


def _normalize_stick(value: int) -> float:
    """Map DualSense stick value (-128..127) to -1..1."""
    return max(-1.0, min(1.0, value / 128.0))
