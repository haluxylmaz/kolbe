"""Standard gamepad input via pygame."""

from __future__ import annotations

import logging
from typing import Optional

import pygame

from kolbe.controller.axis_utils import normalize_trigger_axis
from kolbe.controller.types import (
    ControllerDevice,
    ControllerState,
    ControllerType,
    InputSource,
)

logger = logging.getLogger(__name__)

# PlayStation layout (pygame SDL mapping)
_PS_BUTTON_MAP: dict[int, InputSource] = {
    0: InputSource.CROSS,
    1: InputSource.CIRCLE,
    2: InputSource.SQUARE,
    3: InputSource.TRIANGLE,
    4: InputSource.SHARE,
    5: InputSource.OPTIONS,
    6: InputSource.L3,
    7: InputSource.R3,
    8: InputSource.L1,
    9: InputSource.R1,
    10: InputSource.DPAD_UP,  # often via hat; fallback
    11: InputSource.DPAD_DOWN,
    12: InputSource.DPAD_LEFT,
    13: InputSource.DPAD_RIGHT,
    14: InputSource.PS,
    15: InputSource.TOUCHPAD_CLICK,
}

# Xbox / XInput layout
_XBOX_BUTTON_MAP: dict[int, InputSource] = {
    0: InputSource.A,
    1: InputSource.B,
    2: InputSource.X,
    3: InputSource.Y,
    4: InputSource.L1,
    5: InputSource.R1,
    6: InputSource.SHARE,  # Back / View
    7: InputSource.OPTIONS,  # Start / Menu
    8: InputSource.L3,
    9: InputSource.R3,
}

_PS_AXIS_MAP: dict[int, InputSource] = {
    0: InputSource.LEFT_STICK_X,
    1: InputSource.LEFT_STICK_Y,
    2: InputSource.RIGHT_STICK_X,
    3: InputSource.RIGHT_STICK_Y,
    4: InputSource.L2,
    5: InputSource.R2,
}

_XBOX_AXIS_MAP: dict[int, InputSource] = {
    0: InputSource.LEFT_STICK_X,
    1: InputSource.LEFT_STICK_Y,
    2: InputSource.RIGHT_STICK_X,
    3: InputSource.RIGHT_STICK_Y,
    4: InputSource.L2,
    5: InputSource.R2,
}

# Hardware micro-jitter on high-end sticks is typically well below this band.
# Remaps the remaining range so full deflection still reaches ±1.0.
_DEADZONE = 0.10
_AXIS_CHANGE_EPS = 0.012


def _apply_deadzone(value: float, deadzone: float = _DEADZONE) -> float:
    if abs(value) < deadzone:
        return 0.0
    sign = 1.0 if value > 0 else -1.0
    scaled = (abs(value) - deadzone) / (1.0 - deadzone)
    return sign * min(scaled, 1.0)


def _normalize_trigger(value: float, *, bipolar: bool = False) -> float:
    """Map trigger axis to 0..1 with bottom deadzone snap-to-zero."""
    return normalize_trigger_axis(value, bipolar=bipolar)


class PygameController:
    """Reads standard joystick data through pygame with early-change detection."""

    def __init__(self, device: ControllerDevice) -> None:
        if device.pygame_index is None:
            raise ValueError("PygameController requires a pygame_index on the device")
        self.device = device
        self._joystick: Optional[pygame.joystick.JoystickType] = None
        self._button_map = (
            _PS_BUTTON_MAP
            if device.controller_type in (ControllerType.PLAYSTATION, ControllerType.DUALSENSE)
            else _XBOX_BUTTON_MAP
            if device.controller_type == ControllerType.XBOX
            else {}
        )
        self._axis_map = (
            _PS_AXIS_MAP
            if device.controller_type in (ControllerType.PLAYSTATION, ControllerType.DUALSENSE)
            else _XBOX_AXIS_MAP
            if device.controller_type == ControllerType.XBOX
            else {}
        )
        self._triggers_bipolar = device.controller_type == ControllerType.XBOX
        self._last_button_vals: list[bool] = []
        self._last_axis_vals: list[float] = []
        self._last_hat: tuple[int, int] = (0, 0)
        self._cached_state: Optional[ControllerState] = None

    def open(self) -> None:
        if not pygame.get_init():
            pygame.init()
        if not pygame.joystick.get_init():
            pygame.joystick.init()
        self._joystick = pygame.joystick.Joystick(self.device.pygame_index)
        self._joystick.init()
        self._last_button_vals = []
        self._last_axis_vals = []
        self._last_hat = (0, 0)
        self._cached_state = None
        logger.info("Opened pygame controller: %s", self.device.name)

    def close(self) -> None:
        if self._joystick is not None:
            self._joystick.quit()
            self._joystick = None
        self._cached_state = None

    def poll(self, pump_events: bool = True) -> ControllerState:
        if self._joystick is None:
            raise RuntimeError("Controller not open")

        if pump_events:
            pygame.event.pump()
        joy = self._joystick

        num_buttons = joy.get_numbuttons()
        num_axes = joy.get_numaxes()
        if len(self._last_button_vals) != num_buttons:
            self._last_button_vals = [False] * num_buttons
        if len(self._last_axis_vals) != num_axes:
            self._last_axis_vals = [0.0] * num_axes

        changed = self._cached_state is None

        button_vals = self._last_button_vals
        for btn_id in range(num_buttons):
            pressed = bool(joy.get_button(btn_id))
            if pressed != button_vals[btn_id]:
                button_vals[btn_id] = pressed
                changed = True

        axis_vals = self._last_axis_vals
        for axis_id in range(num_axes):
            raw = joy.get_axis(axis_id)
            source = self._axis_map.get(axis_id)
            if source in (InputSource.L2, InputSource.R2):
                value = _normalize_trigger(raw, bipolar=self._triggers_bipolar)
            else:
                value = _apply_deadzone(raw)
            prev = axis_vals[axis_id]
            # Always accept transitions to/from exact 0 — epsilon filtering otherwise
            # swallows slow trigger releases and leaves CC stuck at Val:21–62.
            crossed_zero = (prev <= 0.0) != (value <= 0.0)
            if crossed_zero or abs(value - prev) > _AXIS_CHANGE_EPS:
                axis_vals[axis_id] = value
                changed = True

        hat = (0, 0)
        if joy.get_numhats() > 0:
            hat = joy.get_hat(0)
            if hat != self._last_hat:
                self._last_hat = hat
                changed = True

        if not changed and self._cached_state is not None:
            return self._cached_state

        buttons: dict[str, bool] = {}
        axes: dict[str, float] = {}

        for btn_id, pressed in enumerate(button_vals):
            source = self._button_map.get(btn_id)
            key = source.value if source else f"button_{btn_id}"
            buttons[key] = pressed

        for axis_id, value in enumerate(axis_vals):
            source = self._axis_map.get(axis_id)
            key = source.value if source else f"axis_{axis_id}"
            axes[key] = value

        hx, hy = self._last_hat
        buttons[InputSource.DPAD_LEFT.value] = hx < 0
        buttons[InputSource.DPAD_RIGHT.value] = hx > 0
        buttons[InputSource.DPAD_UP.value] = hy > 0
        buttons[InputSource.DPAD_DOWN.value] = hy < 0

        state = ControllerState(device=self.device, buttons=buttons, axes=axes)
        self._cached_state = state
        return state
