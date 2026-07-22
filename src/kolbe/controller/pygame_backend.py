"""Standard gamepad input via pygame — GUID / instance_id bound."""

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

# SDL2 / hid-sony layout used by pygame for DualSense & DualShock 4 on Windows.
# (NOT the older DirectInput-style map that put L1 at index 8 and Options at 5.)
_PS_SDL_BUTTON_MAP: dict[int, InputSource] = {
    0: InputSource.CROSS,
    1: InputSource.CIRCLE,
    2: InputSource.SQUARE,
    3: InputSource.TRIANGLE,
    4: InputSource.SHARE,
    5: InputSource.PS,  # Guide
    6: InputSource.OPTIONS,
    7: InputSource.L3,
    8: InputSource.R3,
    9: InputSource.L1,
    10: InputSource.R1,
    11: InputSource.DPAD_UP,
    12: InputSource.DPAD_DOWN,
    13: InputSource.DPAD_LEFT,
    14: InputSource.DPAD_RIGHT,
    15: InputSource.MICROPHONE,  # DualSense mute (ignored if absent)
    16: InputSource.TOUCHPAD_CLICK,
}

# Legacy fallback if a pad exposes fewer buttons and no guide at index 5.
_PS_LEGACY_BUTTON_MAP: dict[int, InputSource] = {
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
    10: InputSource.DPAD_UP,
    11: InputSource.DPAD_DOWN,
    12: InputSource.DPAD_LEFT,
    13: InputSource.DPAD_RIGHT,
    14: InputSource.PS,
    15: InputSource.TOUCHPAD_CLICK,
}

_XBOX_BUTTON_MAP: dict[int, InputSource] = {
    0: InputSource.A,
    1: InputSource.B,
    2: InputSource.X,
    3: InputSource.Y,
    4: InputSource.L1,
    5: InputSource.R1,
    6: InputSource.SHARE,
    7: InputSource.OPTIONS,
    8: InputSource.L3,
    9: InputSource.R3,
}

# Sticks + analog triggers (L2/R2) — SDL2 DualSense/DS4.
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

_DPAD_SOURCES = (
    InputSource.DPAD_UP,
    InputSource.DPAD_DOWN,
    InputSource.DPAD_LEFT,
    InputSource.DPAD_RIGHT,
)

_DEADZONE = 0.10
_AXIS_CHANGE_EPS = 0.012


def _apply_deadzone(value: float, deadzone: float = _DEADZONE) -> float:
    if abs(value) < deadzone:
        return 0.0
    sign = 1.0 if value > 0 else -1.0
    scaled = (abs(value) - deadzone) / (1.0 - deadzone)
    return sign * min(scaled, 1.0)


def _normalize_trigger(value: float, *, bipolar: bool = False) -> float:
    return normalize_trigger_axis(value, bipolar=bipolar)


def _joy_guid(joy: pygame.joystick.JoystickType) -> str:
    if hasattr(joy, "get_guid"):
        try:
            return str(joy.get_guid() or "")
        except Exception:
            return ""
    return ""


def _joy_instance_id(joy: pygame.joystick.JoystickType) -> Optional[int]:
    if hasattr(joy, "get_instance_id"):
        try:
            return int(joy.get_instance_id())
        except Exception:
            return None
    return None


def find_joystick_index_for_device(device: ControllerDevice) -> Optional[int]:
    """
    Resolve the current pygame device index for a hardware identity.

    Prefer SDL GUID, then instance_id, then exact name+prior index.
    Never blindly trust a stale pygame_index after hotplug.
    """
    if not pygame.get_init():
        pygame.init()
    if not pygame.joystick.get_init():
        pygame.joystick.init()

    count = pygame.joystick.get_count()
    target_guid = (device.guid or "").strip()
    target_instance = device.instance_id

    # Pass 1: GUID match (authoritative).
    if target_guid:
        for index in range(count):
            joy = pygame.joystick.Joystick(index)
            joy.init()
            if _joy_guid(joy) == target_guid:
                return index

    # Pass 2: instance_id match.
    if target_instance is not None:
        for index in range(count):
            joy = pygame.joystick.Joystick(index)
            joy.init()
            if _joy_instance_id(joy) == target_instance:
                return index

    # Pass 3: prior index only if name still matches.
    if device.pygame_index is not None and 0 <= device.pygame_index < count:
        joy = pygame.joystick.Joystick(device.pygame_index)
        joy.init()
        if joy.get_name() == device.name:
            return device.pygame_index

    return None


class PygameController:
    """Reads one gamepad through pygame, rebound by GUID/instance_id every open/poll."""

    def __init__(self, device: ControllerDevice) -> None:
        self.device = device
        self._joystick: Optional[pygame.joystick.JoystickType] = None
        self._bound_index: Optional[int] = None
        self._is_playstation = device.controller_type in (
            ControllerType.PLAYSTATION,
            ControllerType.DUALSENSE,
        )
        # Chosen on open once we know num_buttons (SDL vs legacy).
        self._button_map: dict[int, InputSource] = (
            _PS_SDL_BUTTON_MAP if self._is_playstation else _XBOX_BUTTON_MAP
            if device.controller_type == ControllerType.XBOX
            else {}
        )
        self._axis_map = (
            _PS_AXIS_MAP
            if self._is_playstation
            else _XBOX_AXIS_MAP
            if device.controller_type == ControllerType.XBOX
            else {}
        )
        self._triggers_bipolar = device.controller_type == ControllerType.XBOX
        self._last_button_vals: list[bool] = []
        self._last_axis_vals: list[float] = []
        self._last_hat: tuple[int, int] = (0, 0)
        self._cached_state: Optional[ControllerState] = None
        self._last_battery_label = "—"

    def open(self) -> None:
        if not pygame.get_init():
            pygame.init()
        if not pygame.joystick.get_init():
            pygame.joystick.init()
        self._bind_joystick(force=True)
        if self._joystick is None:
            raise RuntimeError(
                f"Could not bind pygame joystick for {self.device.name} "
                f"(guid={self.device.guid!r} instance={self.device.instance_id!r})"
            )
        self._last_button_vals = []
        self._last_axis_vals = []
        self._last_hat = (0, 0)
        self._cached_state = None
        logger.info(
            "Opened pygame controller: %s (index=%s guid=%s instance=%s)",
            self.device.name,
            self._bound_index,
            self.device.guid,
            self.device.instance_id,
        )

    def close(self) -> None:
        if self._joystick is not None:
            try:
                self._joystick.quit()
            except Exception:
                pass
            self._joystick = None
        self._bound_index = None
        self._cached_state = None

    def _identity_matches(self, joy: pygame.joystick.JoystickType) -> bool:
        target_guid = (self.device.guid or "").strip()
        if target_guid:
            return _joy_guid(joy) == target_guid
        if self.device.instance_id is not None:
            return _joy_instance_id(joy) == self.device.instance_id
        return joy.get_name() == self.device.name

    def _bind_joystick(self, *, force: bool = False) -> None:
        if (
            not force
            and self._joystick is not None
            and self._identity_matches(self._joystick)
        ):
            try:
                if self._joystick.get_init():
                    return
            except Exception:
                pass

        # Do NOT joy.quit() the previous handle before we have a replacement —
        # quitting while a sensor companion shares the HID path causes Windows
        # to emit phantom JOYDEVICEREMOVED and tears down sibling pads.
        previous = self._joystick
        index = find_joystick_index_for_device(self.device)
        if index is None:
            self._bound_index = None
            # Keep previous handle if it still answers — transient scan glitch.
            if previous is not None:
                try:
                    if previous.get_init() and self._identity_matches(previous):
                        self._joystick = previous
                        return
                except Exception:
                    pass
            self._joystick = None
            return

        try:
            joy = pygame.joystick.Joystick(index)
            if not joy.get_init():
                joy.init()
        except Exception:
            logger.debug("pygame Joystick init failed at index %s", index, exc_info=True)
            self._bound_index = None
            if previous is not None:
                try:
                    if previous.get_init():
                        self._joystick = previous
                        return
                except Exception:
                    pass
            self._joystick = None
            return

        if not self._identity_matches(joy):
            logger.warning(
                "Refusing pygame bind for %s — identity mismatch at index %s",
                self.device.name,
                index,
            )
            self._bound_index = None
            if previous is not None:
                self._joystick = previous
            else:
                self._joystick = None
            return

        self._joystick = joy
        self._bound_index = index
        self.device.pygame_index = index
        inst = _joy_instance_id(joy)
        if inst is not None:
            self.device.instance_id = inst
        guid = _joy_guid(joy)
        if guid:
            self.device.guid = guid
        self._select_button_map(joy.get_numbuttons())

    def is_alive(self) -> bool:
        """True if the SDL joystick handle still looks usable."""
        joy = self._joystick
        if joy is None:
            return False
        try:
            return bool(joy.get_init()) and self._identity_matches(joy)
        except Exception:
            return False

    def _select_button_map(self, num_buttons: int) -> None:
        """Pick SDL2 vs legacy PS map from the live button count."""
        if not self._is_playstation:
            return
        # Modern DualSense/DS4 via SDL expose Guide + shoulders at 9/10 (≥11 buttons).
        new_map = _PS_SDL_BUTTON_MAP if num_buttons >= 11 else _PS_LEGACY_BUTTON_MAP
        if new_map is not self._button_map:
            self._button_map = new_map
            logger.info(
                "PS button map for %s: %s (%d buttons)",
                self.device.name,
                "SDL2" if num_buttons >= 11 else "legacy",
                num_buttons,
            )

    def poll(self, pump_events: bool = True) -> ControllerState:
        if pump_events:
            pygame.event.pump()

        # Re-resolve if SDL reshuffled indices or our handle went stale.
        try:
            self._bind_joystick(force=False)
            if self._joystick is None or not self._identity_matches(self._joystick):
                self._bind_joystick(force=True)
        except Exception:
            logger.debug("pygame bind during poll failed", exc_info=True)

        if self._joystick is None:
            # Transient loss (phantom JOYDEVICEREMOVED / shared HID) — keep alive.
            if self._cached_state is not None:
                return self._cached_state
            return ControllerState(device=self.device)

        try:
            return self._read_state_from_joystick(self._joystick)
        except Exception:
            logger.debug("pygame state read failed — returning cache", exc_info=True)
            if self._cached_state is not None:
                return self._cached_state
            return ControllerState(device=self.device)

    def _read_state_from_joystick(
        self, joy: pygame.joystick.JoystickType
    ) -> ControllerState:
        num_buttons = joy.get_numbuttons()
        num_axes = joy.get_numaxes()
        if self._is_playstation:
            self._select_button_map(num_buttons)
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
            crossed_zero = (prev <= 0.0) != (value <= 0.0)
            if crossed_zero or abs(value - prev) > _AXIS_CHANGE_EPS:
                axis_vals[axis_id] = value
                changed = True

        # D-Pad via JOYHAT / get_hat (pygame hat), same logical keys as button d-pad.
        hat = (0, 0)
        if joy.get_numhats() > 0:
            hat = joy.get_hat(0)
            if hat != self._last_hat:
                self._last_hat = hat
                changed = True

        battery_percent, battery_label = self._read_battery(joy)
        if battery_label != self._last_battery_label:
            self._last_battery_label = battery_label
            changed = True

        if not changed and self._cached_state is not None:
            return self._cached_state

        buttons: dict[str, bool] = {}
        axes: dict[str, float] = {}

        for btn_id, pressed in enumerate(button_vals):
            source = self._button_map.get(btn_id)
            if source is None:
                buttons[f"button_{btn_id}"] = pressed
                continue
            # D-pad buttons are merged with hat below — skip duplicate keys here.
            if source in _DPAD_SOURCES:
                continue
            buttons[source.value] = pressed

        # DualSense/DS4: SDL maps touchpad click at 16 (modern) or 15 (legacy).
        # OR both indices so a firmware/SDL mismatch never drops the click.
        if self._is_playstation:
            click = bool(buttons.get(InputSource.TOUCHPAD_CLICK.value, False))
            for idx in (15, 16):
                if idx < len(button_vals):
                    click = click or bool(button_vals[idx])
            buttons[InputSource.TOUCHPAD_CLICK.value] = click

        for axis_id, value in enumerate(axis_vals):
            source = self._axis_map.get(axis_id)
            key = source.value if source else f"axis_{axis_id}"
            axes[key] = value

        # Merge hat + digital d-pad buttons into Kolbe DPAD_* inputs.
        hx, hy = hat
        dpad_from_hat = {
            InputSource.DPAD_LEFT: hx < 0,
            InputSource.DPAD_RIGHT: hx > 0,
            InputSource.DPAD_UP: hy > 0,
            InputSource.DPAD_DOWN: hy < 0,
        }
        dpad_from_buttons = {
            InputSource.DPAD_UP: False,
            InputSource.DPAD_DOWN: False,
            InputSource.DPAD_LEFT: False,
            InputSource.DPAD_RIGHT: False,
        }
        for btn_id, pressed in enumerate(button_vals):
            source = self._button_map.get(btn_id)
            if source in dpad_from_buttons and pressed:
                dpad_from_buttons[source] = True
        for source in _DPAD_SOURCES:
            buttons[source.value] = dpad_from_hat[source] or dpad_from_buttons[source]

        state = ControllerState(
            device=self.device,
            buttons=buttons,
            axes=axes,
            battery_percent=battery_percent,
            battery_label=battery_label,
        )
        self._cached_state = state
        return state

    @staticmethod
    def _read_battery(joy: pygame.joystick.JoystickType) -> tuple[Optional[int], str]:
        """SDL power level → percent + display label (Wired when USB/unknown)."""
        level = None
        if hasattr(joy, "get_power_level"):
            try:
                level = joy.get_power_level()
            except Exception:
                level = None

        if level is None:
            return None, "Wired"

        text = str(level).strip().lower()
        mapping = {
            "empty": (5, "Empty"),
            "low": (25, "Low"),
            "medium": (55, "Medium"),
            "full": (90, "Full"),
            "max": (100, "Full"),
            "wired": (None, "Wired"),
            "charging": (None, "Charging"),
            "unknown": (None, "Wired"),
        }
        if text in mapping:
            return mapping[text]
        return None, "Wired"
