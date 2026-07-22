"""Four logical controller slots — assign hardware, battery, refresh."""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from kolbe.controller.slots import (
    SLOT_NUMBERS,
    ControllerSlot,
    SlotRegistry,
    accent_for_slot,
    slot_label,
)
from kolbe.controller.types import ControllerDevice


class ControllerSlotsPanel(QFrame):
    """
    Shows Controller 1–4 with:
    - color accent
    - hardware assignment dropdown
    - battery / connection status
    - Refresh / Rescan
    """

    slot_selected = pyqtSignal(int)  # logical slot 1–4
    slot_assignment_changed = pyqtSignal(int, object)  # slot, hardware_id|None
    refresh_requested = pyqtSignal()

    def __init__(
        self,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("controllerSlotsPanel")
        self._registry = SlotRegistry()
        self._hardware: dict[str, ControllerDevice] = {}
        self._rows: dict[int, _SlotRow] = {}
        self._selected_slot = 1

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 8)
        root.setSpacing(6)

        header = QHBoxLayout()
        title = QLabel("Controller Slots")
        title.setStyleSheet("color: #e8eaed; font-weight: 700; font-size: 13px;")
        header.addWidget(title)
        header.addStretch()
        self.refresh_btn = QPushButton("Refresh / Rescan")
        self.refresh_btn.setToolTip("Re-detect plugged / unplugged controllers without restarting")
        self.refresh_btn.clicked.connect(self.refresh_requested.emit)
        header.addWidget(self.refresh_btn)
        root.addLayout(header)

        hint = QLabel(
            "Assign each physical gamepad to a fixed slot (1–4). "
            "Mappings follow the slot — not plug-in order."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #8b93a7; font-size: 11px;")
        root.addWidget(hint)

        for number in SLOT_NUMBERS:
            row = _SlotRow(number)
            row.selected.connect(self._on_row_selected)
            row.assignment_changed.connect(self._on_assignment_changed)
            self._rows[number] = row
            root.addWidget(row)

        self._paint_selection()

    @property
    def registry(self) -> SlotRegistry:
        return self._registry

    def selected_slot(self) -> int:
        return self._selected_slot

    def set_selected_slot(self, slot: int) -> None:
        if slot not in SLOT_NUMBERS:
            return
        self._selected_slot = int(slot)
        self._paint_selection()

    def set_hardware_devices(self, devices: dict[str, ControllerDevice]) -> None:
        self._hardware = dict(devices)
        self._registry.sync_live_devices(self._hardware)
        self._rebuild_combos()
        self._refresh_row_status()

    def apply_assignments(self, assignments: dict[str, str]) -> None:
        self._registry.load_assignments(assignments)
        self._registry.sync_live_devices(self._hardware)
        self._rebuild_combos()
        self._refresh_row_status()

    def assignments(self) -> dict[str, str]:
        return self._registry.to_assignments()

    def update_battery(
        self,
        hardware_id: str,
        percent: Optional[int],
        label: Optional[str] = None,
    ) -> None:
        text = label or _format_battery(percent)
        self._registry.update_battery(hardware_id, percent, text)
        self._refresh_row_status()

    def snapshot_slots(self) -> list[ControllerSlot]:
        return self._registry.snapshot()

    def _rebuild_combos(self) -> None:
        options = [(None, "— Unassigned —")]
        for hardware_id, device in self._hardware.items():
            options.append((hardware_id, device.name))
        # Also keep remembered-but-disconnected assignments visible.
        for slot in self._registry.snapshot():
            if slot.hardware_id and slot.hardware_id not in self._hardware:
                options.append((slot.hardware_id, f"{slot.hardware_id} (offline)"))

        for number, row in self._rows.items():
            current = self._registry.hardware_for_slot(number)
            row.set_options(options, current)

    def _refresh_row_status(self) -> None:
        for slot in self._registry.snapshot():
            self._rows[slot.number].set_status(slot)

    def _on_row_selected(self, slot: int) -> None:
        self._selected_slot = slot
        self._paint_selection()
        self.slot_selected.emit(slot)

    def _on_assignment_changed(self, slot: int, hardware_id: object) -> None:
        hid = str(hardware_id) if hardware_id else None
        self._registry.assign(slot, hid)
        self._registry.sync_live_devices(self._hardware)
        self._rebuild_combos()
        self._refresh_row_status()
        self.slot_assignment_changed.emit(slot, hid)

    def _paint_selection(self) -> None:
        for number, row in self._rows.items():
            row.set_selected(number == self._selected_slot)


class _SlotRow(QFrame):
    selected = pyqtSignal(int)
    assignment_changed = pyqtSignal(int, object)

    def __init__(self, number: int) -> None:
        super().__init__()
        self.number = number
        self._accent = accent_for_slot(number)
        self._suppress = False
        self._is_selected = False
        self._is_connected = False

        self.setObjectName("controllerSlotRow")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(10)

        self.swatch = QLabel("")
        self.swatch.setFixedSize(12, 28)
        self.swatch.setStyleSheet(f"background-color: {self._accent}; border-radius: 2px;")
        layout.addWidget(self.swatch)

        self.title = QLabel(slot_label(number))
        self.title.setStyleSheet(f"color: {self._accent}; font-weight: 700; min-width: 96px;")
        layout.addWidget(self.title)

        self.combo = QComboBox()
        self.combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.combo.currentIndexChanged.connect(self._on_combo)
        layout.addWidget(self.combo, stretch=1)

        self.battery = QLabel("—")
        self.battery.setMinimumWidth(88)
        self.battery.setStyleSheet("color: #c5c8d0;")
        layout.addWidget(self.battery)

        self.status = QLabel("Empty")
        self.status.setMinimumWidth(100)
        self.status.setStyleSheet("color: #8b93a7;")
        layout.addWidget(self.status)

        self.mousePressEvent = self._click  # type: ignore[method-assign]
        self._apply_chrome()

    def set_options(self, options: list[tuple[Optional[str], str]], current: Optional[str]) -> None:
        self._suppress = True
        self.combo.blockSignals(True)
        self.combo.clear()
        for value, label in options:
            self.combo.addItem(label, value)
        idx = self.combo.findData(current)
        self.combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.combo.blockSignals(False)
        self._suppress = False

    def set_status(self, slot: ControllerSlot) -> None:
        self._is_connected = slot.connected
        if slot.connected:
            self.status.setText("Connected")
            self.status.setStyleSheet(f"color: {self._accent}; font-weight: 600;")
            bat = slot.battery_text or _format_battery(slot.battery_percent)
            self.battery.setText(f"Battery: {bat}")
        elif slot.hardware_id:
            self.status.setText("Disconnected")
            self.status.setStyleSheet("color: #FF6B6B; font-weight: 600;")
            self.battery.setText("Battery: —")
        else:
            self.status.setText("Empty")
            self.status.setStyleSheet("color: #8b93a7;")
            self.battery.setText("Battery: —")
        self._apply_chrome()

    def set_selected(self, selected: bool) -> None:
        self._is_selected = selected
        self._apply_chrome()

    def _apply_chrome(self) -> None:
        border = self._accent if self._is_selected else ("#3a3a3a" if self._is_connected else "#2a2a2a")
        bg = "#1e1e1e" if self._is_selected else "#181818"
        self.setStyleSheet(
            f"#controllerSlotRow {{ background-color: {bg}; border: 1px solid {border}; "
            f"border-radius: 6px; }}"
        )

    def _on_combo(self, _index: int) -> None:
        if self._suppress:
            return
        self.assignment_changed.emit(self.number, self.combo.currentData())

    def _click(self, _event) -> None:  # noqa: ANN001
        self.selected.emit(self.number)


def _format_battery(percent: Optional[int]) -> str:
    if percent is None:
        return "Wired"
    if percent >= 70:
        band = "High"
    elif percent >= 35:
        band = "Medium"
    else:
        band = "Low"
    return f"{percent}% ({band})"
