"""Logical controller slots (1–4) with manual hardware assignment."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from kolbe.controller.types import ControllerDevice

MAX_CONTROLLER_SLOTS = 4
SLOT_NUMBERS = tuple(range(1, MAX_CONTROLLER_SLOTS + 1))

# Fixed accent per logical slot (Controller 1–4).
SLOT_ACCENT_COLORS = (
    "#00E5FF",  # 1 — cyan
    "#FF2D95",  # 2 — magenta
    "#FF9F1C",  # 3 — orange
    "#44FF88",  # 4 — green
)


def slot_id(slot: int) -> str:
    """Canonical mapping device_slot key for a logical slot (\"1\"…\"4\")."""
    return str(int(slot))


def parse_slot_id(value: str) -> Optional[int]:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number in SLOT_NUMBERS:
        return number
    return None


def accent_for_slot(slot: int) -> str:
    index = max(0, int(slot) - 1)
    return SLOT_ACCENT_COLORS[index % len(SLOT_ACCENT_COLORS)]


def slot_label(slot: int) -> str:
    return f"Controller {int(slot)}"


@dataclass
class ControllerSlot:
    """One logical pad slot and its optional hardware binding."""

    number: int
    hardware_id: Optional[str] = None
    device: Optional[ControllerDevice] = None
    connected: bool = False
    battery_percent: Optional[int] = None
    battery_text: str = "—"

    @property
    def slot_key(self) -> str:
        return slot_id(self.number)

    @property
    def accent(self) -> str:
        return accent_for_slot(self.number)

    @property
    def display_name(self) -> str:
        if self.device is not None:
            return self.device.name
        if self.hardware_id:
            return "Disconnected"
        return "Empty"


@dataclass
class SlotRegistry:
    """
    Maps logical slots 1–4 ↔ hardware device ids.

    Mappings / MIDI use slot keys (\"1\"…\"4\"). Hardware ids stay GUID-stable.
    """

    slots: dict[int, ControllerSlot] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for number in SLOT_NUMBERS:
            self.slots.setdefault(number, ControllerSlot(number=number))

    def to_assignments(self) -> dict[str, str]:
        """Persistable map: slot_key → hardware_id (only assigned)."""
        out: dict[str, str] = {}
        for number, slot in self.slots.items():
            if slot.hardware_id:
                out[slot_id(number)] = slot.hardware_id
        return out

    def load_assignments(self, assignments: dict[str, str]) -> None:
        for number in SLOT_NUMBERS:
            self.slots[number].hardware_id = None
            self.slots[number].device = None
            self.slots[number].connected = False
            self.slots[number].battery_percent = None
            self.slots[number].battery_text = "—"
        for key, hardware_id in (assignments or {}).items():
            number = parse_slot_id(str(key))
            if number is None or not hardware_id:
                continue
            self.slots[number].hardware_id = str(hardware_id)

    def slot_for_hardware(self, hardware_id: str) -> Optional[int]:
        for number, slot in self.slots.items():
            if slot.hardware_id == hardware_id:
                return number
        return None

    def hardware_for_slot(self, slot: int) -> Optional[str]:
        return self.slots[int(slot)].hardware_id

    def assign(self, slot: int, hardware_id: Optional[str]) -> None:
        """Manually assign hardware to a slot; clears the id from other slots."""
        slot = int(slot)
        if slot not in self.slots:
            raise ValueError(f"Invalid slot {slot}")
        if hardware_id:
            for other in self.slots.values():
                if other.number != slot and other.hardware_id == hardware_id:
                    other.hardware_id = None
                    other.device = None
                    other.connected = False
                    other.battery_percent = None
                    other.battery_text = "—"
        target = self.slots[slot]
        target.hardware_id = hardware_id or None
        if not hardware_id:
            target.device = None
            target.connected = False
            target.battery_percent = None
            target.battery_text = "—"

    def sync_live_devices(self, devices: dict[str, ControllerDevice]) -> list[int]:
        """
        Update live device pointers; auto-fill empty slots for new hardware.

        Returns list of slot numbers that changed connectivity/binding.
        """
        changed: list[int] = []

        for slot in self.slots.values():
            was_connected = slot.connected
            if slot.hardware_id and slot.hardware_id in devices:
                slot.device = devices[slot.hardware_id]
                slot.connected = True
                if not was_connected:
                    changed.append(slot.number)
            else:
                slot.device = None
                if was_connected:
                    changed.append(slot.number)
                slot.connected = False
                if slot.hardware_id:
                    slot.battery_text = "Disconnected"
                    slot.battery_percent = None
                else:
                    slot.battery_text = "—"
                    slot.battery_percent = None

        assigned_ids = {s.hardware_id for s in self.slots.values() if s.hardware_id}
        free_slots = [n for n in SLOT_NUMBERS if not self.slots[n].hardware_id]
        for hardware_id, device in devices.items():
            if hardware_id in assigned_ids:
                continue
            if not free_slots:
                break
            number = free_slots.pop(0)
            slot = self.slots[number]
            slot.hardware_id = hardware_id
            slot.device = device
            slot.connected = True
            slot.battery_text = "…"
            changed.append(number)
            assigned_ids.add(hardware_id)

        return sorted(set(changed))

    def update_battery(self, hardware_id: str, percent: Optional[int], text: str) -> Optional[int]:
        number = self.slot_for_hardware(hardware_id)
        if number is None:
            return None
        slot = self.slots[number]
        if not slot.connected:
            return number
        slot.battery_percent = percent
        slot.battery_text = text
        return number

    def snapshot(self) -> list[ControllerSlot]:
        return [self.slots[n] for n in SLOT_NUMBERS]
