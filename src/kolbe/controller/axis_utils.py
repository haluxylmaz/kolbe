"""Stateless axis helpers — O(1) remaps with no history tracking."""

from __future__ import annotations

# Bottom deadzone for analog triggers (L2/R2). Resting noise below this → exact 0.
TRIGGER_BOTTOM_DEADZONE = 0.12


def apply_trigger_bottom_deadzone(
    raw_01: float,
    deadzone: float = TRIGGER_BOTTOM_DEADZONE,
) -> float:
    """
    Zero-latency trigger remap: clamp rest to 0, linearly rescale the rest to 1.

        if raw < deadzone: 0.0
        else: (raw - deadzone) / (1 - deadzone)
    """
    value = max(0.0, min(1.0, float(raw_01)))
    if value <= deadzone:
        return 0.0
    return (value - deadzone) / (1.0 - deadzone)


def normalize_trigger_axis(raw: float, *, bipolar: bool = False) -> float:
    """
    Map a controller trigger axis into 0..1, then apply bottom deadzone.

    - bipolar=True  (typical Xbox / SDL joystick): raw -1..+1 with rest at -1
    - bipolar=False (typical DualSense 0..1, or HID 0..255 scaled): rest near 0
      If a negative sample appears, fall back to bipolar mapping for that sample.
    """
    value = float(raw)
    if bipolar:
        remapped = (max(-1.0, min(1.0, value)) + 1.0) / 2.0
    elif value < 0.0:
        remapped = (max(-1.0, value) + 1.0) / 2.0
    else:
        remapped = max(0.0, min(1.0, value))
    return apply_trigger_bottom_deadzone(remapped)
