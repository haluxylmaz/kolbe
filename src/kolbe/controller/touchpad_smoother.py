"""Stable DualSense/DS4 touchpad tracking: normalize, isolate fingers, reject ghosts."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from kolbe.controller.types import TouchPoint

DEFAULT_SMOOTHING_ALPHA = 0.40
# Instant jump to near-origin while still "active" is a common pre-lift garbage frame.
_GHOST_ORIGIN_EPS = 0.03
_JUMP_REJECT = 0.40
_SLOT_COUNT = 2


def normalize_touch_axis(raw: float, max_value: float) -> float:
    """Map absolute touchpad pixels into clamped [0.0, 1.0]."""
    if max_value <= 0:
        return 0.0
    return max(0.0, min(1.0, float(raw) / float(max_value)))


@dataclass
class _SlotState:
    hw_id: Optional[int] = None
    active: bool = False
    x: float = 0.0
    y: float = 0.0


class TouchpadSmoother:
    """Sticky finger-ID → output-slot tracker with lift-safe coordinate hold."""

    def __init__(self, alpha: float = DEFAULT_SMOOTHING_ALPHA) -> None:
        self._alpha = max(0.05, min(1.0, alpha))
        self._slots: list[_SlotState] = [_SlotState() for _ in range(_SLOT_COUNT)]
        self._id_to_slot: dict[int, int] = {}

    def reset(self) -> None:
        self._slots = [_SlotState() for _ in range(_SLOT_COUNT)]
        self._id_to_slot.clear()

    def process(self, finger_id: int, active: bool, x: float, y: float) -> TouchPoint:
        """Legacy single-finger API — routes through the sticky slot tracker."""
        points = [(active, x, y, finger_id)]
        # Pad a second inactive contact so process_pair stays consistent.
        points.append((False, 0.0, 0.0, (finger_id + 1) & 0x7F))
        return self.process_pair(points)[0]

    def process_pair(
        self,
        points: list[tuple[bool, float, float, int]],
    ) -> list[TouchPoint]:
        """
        Convert up to two hardware contact slots into stable Finger 1 / Finger 2 outputs.

        Hardware packs contacts into report slots and may reorder them when a finger
        lifts. Tracking by hardware finger ID keeps each live contact stuck to the
        same output slot so the other finger does not jump.
        """
        active_contacts = self._collect_active_contacts(points)

        # Release slots whose hardware IDs are no longer touching.
        for hw_id in list(self._id_to_slot.keys()):
            if hw_id not in active_contacts:
                slot_index = self._id_to_slot.pop(hw_id)
                slot = self._slots[slot_index]
                slot.active = False
                # Keep last good x/y — do not pull inactive report zeros.
                slot.hw_id = hw_id

        # Update / assign remaining live contacts.
        for hw_id, (x, y) in active_contacts.items():
            slot_index = self._id_to_slot.get(hw_id)
            if slot_index is None:
                slot_index = self._allocate_slot()
                if slot_index is None:
                    continue
                self._id_to_slot[hw_id] = slot_index
                slot = self._slots[slot_index]
                slot.hw_id = hw_id
                slot.x = x
                slot.y = y
                slot.active = True
                continue

            slot = self._slots[slot_index]
            if self._is_ghost_origin_sample(slot, x, y):
                # Keep prior position; often the frame before isActive clears.
                slot.active = True
                slot.hw_id = hw_id
                continue

            if slot.active:
                slot.x = self._alpha * x + (1.0 - self._alpha) * slot.x
                slot.y = self._alpha * y + (1.0 - self._alpha) * slot.y
            else:
                # Fresh press into a previously free/recycled slot — snap, no lag from 0,0.
                slot.x = x
                slot.y = y
            slot.active = True
            slot.hw_id = hw_id

        return [
            TouchPoint(
                active=slot.active,
                x=slot.x,
                y=slot.y,
                finger_id=slot.hw_id if slot.hw_id is not None else index,
            )
            for index, slot in enumerate(self._slots)
        ]

    def _collect_active_contacts(
        self,
        points: list[tuple[bool, float, float, int]],
    ) -> dict[int, tuple[float, float]]:
        contacts: dict[int, tuple[float, float]] = {}
        for active, x, y, finger_id in points[:_SLOT_COUNT]:
            if not active:
                continue
            hw_id = int(finger_id) & 0x7F
            nx = max(0.0, min(1.0, float(x)))
            ny = max(0.0, min(1.0, float(y)))
            # Prefer first occurrence of an ID (hardware shouldn't duplicate live IDs).
            contacts.setdefault(hw_id, (nx, ny))
        return contacts

    def _allocate_slot(self) -> Optional[int]:
        for index, slot in enumerate(self._slots):
            if not slot.active and index not in self._id_to_slot.values():
                return index
        for index, slot in enumerate(self._slots):
            if not slot.active:
                # Recycle stale hw_id binding.
                stale = [hid for hid, s in self._id_to_slot.items() if s == index]
                for hid in stale:
                    self._id_to_slot.pop(hid, None)
                return index
        return None

    @staticmethod
    def _is_ghost_origin_sample(slot: _SlotState, x: float, y: float) -> bool:
        if not slot.active:
            return False
        near_origin = x <= _GHOST_ORIGIN_EPS and y <= _GHOST_ORIGIN_EPS
        if not near_origin:
            return False
        previous_away = math.hypot(slot.x, slot.y) > _JUMP_REJECT
        jump = math.hypot(x - slot.x, y - slot.y)
        return previous_away and jump > _JUMP_REJECT
