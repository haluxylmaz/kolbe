"""Controller input data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ControllerType(str, Enum):
    GENERIC = "generic"
    XBOX = "xbox"
    PLAYSTATION = "playstation"
    DUALSENSE = "dualsense"


class InputSource(str, Enum):
    """Canonical input identifiers used across backends."""

    # Face buttons
    CROSS = "cross"
    CIRCLE = "circle"
    SQUARE = "square"
    TRIANGLE = "triangle"
    # Xbox aliases
    A = "a"
    B = "b"
    X = "x"
    Y = "y"

    # Shoulder / triggers
    L1 = "l1"
    R1 = "r1"
    L2 = "l2"
    R2 = "r2"

    # Stick clicks
    L3 = "l3"
    R3 = "r3"

    # System buttons
    SHARE = "share"
    OPTIONS = "options"
    PS = "ps"
    TOUCHPAD_CLICK = "touchpad_click"
    MICROPHONE = "microphone"

    # D-Pad
    DPAD_UP = "dpad_up"
    DPAD_DOWN = "dpad_down"
    DPAD_LEFT = "dpad_left"
    DPAD_RIGHT = "dpad_right"

    # Analog axes (-1.0 to 1.0 unless noted)
    LEFT_STICK_X = "left_stick_x"
    LEFT_STICK_Y = "left_stick_y"
    RIGHT_STICK_X = "right_stick_x"
    RIGHT_STICK_Y = "right_stick_y"

    # Touchpad (0.0–1.0 normalized)
    TOUCHPAD_0_X = "touchpad_0_x"
    TOUCHPAD_0_Y = "touchpad_0_y"
    TOUCHPAD_1_X = "touchpad_1_x"
    TOUCHPAD_1_Y = "touchpad_1_y"

    # Motion sensors (raw device units)
    GYRO_PITCH = "gyro_pitch"
    GYRO_YAW = "gyro_yaw"
    GYRO_ROLL = "gyro_roll"
    ACCEL_X = "accel_x"
    ACCEL_Y = "accel_y"
    ACCEL_Z = "accel_z"


@dataclass
class TouchPoint:
    active: bool = False
    x: float = 0.0
    y: float = 0.0
    finger_id: int = 0


@dataclass
class ControllerDevice:
    """Metadata for a detected controller."""

    id: str
    name: str
    controller_type: ControllerType
    backend: str  # "pygame" | "dualsense"
    pygame_index: Optional[int] = None
    guid: Optional[str] = None
    num_buttons: int = 0
    num_axes: int = 0
    num_hats: int = 0


@dataclass
class ControllerState:
    """Unified snapshot of all controller inputs."""

    device: ControllerDevice
    buttons: dict[str, bool] = field(default_factory=dict)
    axes: dict[str, float] = field(default_factory=dict)
    touchpad: list[TouchPoint] = field(default_factory=lambda: [TouchPoint(), TouchPoint()])
    gyro: dict[str, float] = field(default_factory=dict)
    accelerometer: dict[str, float] = field(default_factory=dict)
    battery_percent: Optional[int] = None

    def active_buttons(self) -> list[str]:
        return [name for name, pressed in self.buttons.items() if pressed]

    def non_zero_axes(self, threshold: float = 0.05) -> dict[str, float]:
        return {name: val for name, val in self.axes.items() if abs(val) > threshold}

    def significant_change_from(
        self,
        other: Optional["ControllerState"],
        *,
        axis_epsilon: float = 0.012,
    ) -> bool:
        """Return True if buttons/axes differ enough to warrant a UI/MIDI update."""
        if other is None or other.device.id != self.device.id:
            return True
        if self.buttons != other.buttons:
            return True

        keys = set(self.axes) | set(other.axes)
        for key in keys:
            a = self.axes.get(key, 0.0)
            b = other.axes.get(key, 0.0)
            # Zero transitions must always emit (trigger release → CC 0).
            if (a <= 0.0) != (b <= 0.0):
                return True
            if abs(a - b) > axis_epsilon:
                return True

        # Advanced sensors (HID backends) — cheap length/key checks first.
        if self.gyro != other.gyro or self.accelerometer != other.accelerometer:
            return True
        if self.touchpad != other.touchpad:
            return True
        if self.battery_percent != other.battery_percent:
            return True
        return False
