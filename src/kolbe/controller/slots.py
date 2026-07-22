"""Logical controller slots (1–4) with manual hardware assignment."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from kolbe.controller.types import ControllerDevice

MAX_CONTROLLER_SLOTS = 4
SLOT_NUMBERS = tuple(range(1, MAX_CONTROLLER_SLOTS + 1))

# UI accents stay in sync with ``ps_led.SLOT_LED_RGB`` (single source of truth for LEDs).
def _accent_hex_from_led() -> tuple[str, ...]:
    try:
        from kolbe.controller.ps_led import SLOT_LED_RGB

        out: list[str] = []
        for number in SLOT_NUMBERS:
            r, g, b = SLOT_LED_RGB[number]
            out.append(f"#{r:02X}{g:02X}{b:02X}")
        return tuple(out)
    except Exception:
        return ("#00E5FF", "#E91E63", "#FF9800", "#4CAF50")


SLOT_ACCENT_COLORS = _accent_hex_from_led()


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
    colors = _accent_hex_from_led()
    return colors[index % len(colors)]


def led_color_for_slot(slot: int) -> tuple[int, int, int]:
    """Physical lightbar RGB for a logical slot (from ``ps_led.SLOT_LED_RGB``)."""
    from kolbe.controller.ps_led import led_rgb_for_slot

    return led_rgb_for_slot(slot)


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


def _clear_slot_fields(slot: ControllerSlot) -> None:
    slot.hardware_id = None
    slot.device = None
    slot.connected = False
    slot.battery_percent = None
    slot.battery_text = "—"


def _copy_binding(dst: ControllerSlot, src: ControllerSlot) -> None:
    dst.hardware_id = src.hardware_id
    dst.device = src.device
    dst.connected = src.connected
    dst.battery_percent = src.battery_percent
    dst.battery_text = src.battery_text


@dataclass
class SlotRegistry:
    """
    Maps logical slots 1–4 ↔ hardware device ids.

    Manual assignments are authoritative: users may place pads in any slot
    (including gaps). ``sync_live_devices`` only updates live/connected state
    and auto-fills *empty* slots — it never forces a 1..N pack that undoes moves.
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
            _clear_slot_fields(self.slots[number])
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
        """
        Manually assign hardware to any slot (1–4).

        - Move into an empty slot: source slot is cleared.
        - Move onto an occupied slot: the two pads **swap**.
        - Assign untracked hardware onto an occupied slot: target takes it;
          the previous occupant becomes unassigned (no error).
        - Unassign (None): target is cleared.
        """
        slot = int(slot)
        if slot not in self.slots:
            raise ValueError(f"Invalid slot {slot}")

        target = self.slots[slot]

        if not hardware_id:
            _clear_slot_fields(target)
            return

        hardware_id = str(hardware_id)
        source_num = self.slot_for_hardware(hardware_id)
        if source_num == slot:
            return

        # Snapshot incoming binding (from its current slot, if any).
        incoming = ControllerSlot(number=0, hardware_id=hardware_id)
        if source_num is not None:
            _copy_binding(incoming, self.slots[source_num])
            incoming.hardware_id = hardware_id

        displaced = ControllerSlot(number=0)
        has_displaced = bool(target.hardware_id and target.hardware_id != hardware_id)
        if has_displaced:
            _copy_binding(displaced, target)

        if source_num is not None and has_displaced:
            # Swap: previous target occupant ↔ source.
            _copy_binding(self.slots[source_num], displaced)
        elif source_num is not None:
            # Move into empty (or self-cleared) target.
            _clear_slot_fields(self.slots[source_num])
        # else: fresh assign — displaced occupant (if any) is simply vacated.

        _copy_binding(target, incoming)
        target.hardware_id = hardware_id

    def sync_live_devices(self, devices: dict[str, ControllerDevice]) -> list[int]:
        """
        Refresh connected/device pointers for assigned slots; auto-fill empties.

        Does **not** compact or reorder existing manual assignments — that was
        blocking Slot 2→4 moves (everything got packed back to 1..N).
        """
        changed: list[int] = []
        live_ids = set(devices.keys())

        for number in SLOT_NUMBERS:
            slot = self.slots[number]
            was_connected = slot.connected
            hid = slot.hardware_id
            if hid and hid in devices:
                slot.device = devices[hid]
                slot.connected = True
                if not was_connected:
                    changed.append(number)
                if slot.battery_text in ("—", "Disconnected"):
                    slot.battery_text = "…"
            else:
                slot.device = None
                if was_connected:
                    changed.append(number)
                slot.connected = False
                if hid:
                    slot.battery_text = "Disconnected"
                    slot.battery_percent = None
                else:
                    slot.battery_text = "—"
                    slot.battery_percent = None

        assigned_ids = {s.hardware_id for s in self.slots.values() if s.hardware_id}
        free_slots = [n for n in SLOT_NUMBERS if not self.slots[n].hardware_id]

        def _stable_key(hardware_id: str) -> tuple:
            device = devices.get(hardware_id)
            guid = (device.guid if device else None) or ""
            if hardware_id.startswith("guid:"):
                guid = guid or hardware_id[5:]
            return (guid.lower(), hardware_id)

        for hardware_id in sorted(live_ids, key=_stable_key):
            if hardware_id in assigned_ids:
                continue
            if not free_slots:
                break
            number = free_slots.pop(0)
            slot = self.slots[number]
            slot.hardware_id = hardware_id
            slot.device = devices[hardware_id]
            slot.connected = True
            slot.battery_text = "…"
            slot.battery_percent = None
            assigned_ids.add(hardware_id)
            changed.append(number)

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
