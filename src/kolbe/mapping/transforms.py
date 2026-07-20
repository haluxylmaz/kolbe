"""Analog value transforms for MIDI output."""

from __future__ import annotations

import math

from kolbe.mapping.models import ResponseCurve


def apply_deadzone(value: float, deadzone: float) -> float:
    """Zero out values inside deadzone and rescale the remainder."""
    deadzone = max(0.0, min(0.95, deadzone))
    magnitude = abs(value)
    if magnitude <= deadzone:
        return 0.0
    sign = 1.0 if value >= 0 else -1.0
    scaled = (magnitude - deadzone) / (1.0 - deadzone)
    return sign * min(scaled, 1.0)


def normalize_analog_raw(source_key: str, value: float) -> float:
    """Normalize heterogeneous sensor ranges to 0..1 for MIDI mapping."""
    gyro_keys = ("gyro_pitch", "gyro_yaw", "gyro_roll")
    accel_keys = ("accel_x", "accel_y", "accel_z")

    if source_key in gyro_keys:
        return max(0.0, min(1.0, (value + 2000.0) / 4000.0))
    if source_key in accel_keys:
        return max(0.0, min(1.0, (value + 32768.0) / 65536.0))
    if source_key in ("l2", "r2") or source_key.startswith("touchpad"):
        return max(0.0, min(1.0, value))
    return max(0.0, min(1.0, (value + 1.0) / 2.0))


def apply_response_curve(normalized: float, curve: ResponseCurve) -> float:
    """Apply response curve to a 0..1 normalized value."""
    value = max(0.0, min(1.0, normalized))
    if curve == ResponseCurve.EXPONENTIAL:
        return value * value
    if curve == ResponseCurve.LOGARITHMIC:
        return math.sqrt(value)
    return value


def scale_split_side(centered: float, deadzone: float, side: str) -> float:
    """Map centered axis value to 0..1 for one split side."""
    if side == "neg":
        if centered >= -deadzone:
            return 0.0
        return min(1.0, (abs(centered) - deadzone) / max(1.0 - deadzone, 1e-6))
    if centered <= deadzone:
        return 0.0
    return min(1.0, (centered - deadzone) / max(1.0 - deadzone, 1e-6))


def transform_to_midi(
    normalized: float,
    min_value: int,
    max_value: int,
    offset: float,
    invert: bool,
    invert_output: bool = False,
    curve: ResponseCurve = ResponseCurve.LINEAR,
) -> int:
    """Map normalized 0..1 input to MIDI integer range."""
    value = apply_response_curve(normalized, curve)
    value = value + offset
    value = max(0.0, min(1.0, value))
    if invert or invert_output:
        value = 1.0 - value
    lo = min(min_value, max_value)
    hi = max(min_value, max_value)
    midi = int(round(lo + value * (hi - lo)))
    return max(0, min(127, midi))


def transform_to_pitch_bend(
    normalized: float,
    min_value: int,
    max_value: int,
    offset: float,
    invert: bool,
    invert_output: bool = False,
    curve: ResponseCurve = ResponseCurve.LINEAR,
) -> int:
    """Map normalized 0..1 input to pitch bend via 0–127 range."""
    midi = transform_to_midi(normalized, min_value, max_value, offset, invert, invert_output, curve)
    return int(round(-8192 + (midi / 127.0) * 16383))
