"""Application top bar — MIDI, devices, pages, presets."""

from __future__ import annotations

from typing import Callable, Optional

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QFontMetrics
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QButtonGroup,
    QSizePolicy,
    QWidget,
)

from kolbe.mapping.preset_manager import PresetManager
from kolbe.midi.virtual_port import DEFAULT_PORT_NAME, list_midi_ports, supports_virtual_midi


def _virtual_port_label() -> str:
    return f"Virtual: {DEFAULT_PORT_NAME}"


class TopBar(QFrame):
    """MIDI output, device/page controls, preset actions, and status."""

    page_selected = pyqtSignal(int)
    device_selected = pyqtSignal(str)

    def __init__(
        self,
        on_midi_port_changed: Optional[Callable[[str], None]] = None,
        on_save_preset: Optional[Callable[[], None]] = None,
        on_load_preset: Optional[Callable[[], None]] = None,
        on_template_selected: Optional[Callable[[str], None]] = None,
        on_cleanup_project: Optional[Callable[[], None]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("topBar")
        self._on_midi_port_changed = on_midi_port_changed
        self._on_save_preset = on_save_preset
        self._on_load_preset = on_load_preset
        self._on_template_selected = on_template_selected
        self._on_cleanup_project = on_cleanup_project
        self._page_buttons: list[QPushButton] = []
        self._page_group = QButtonGroup(self)
        self._page_group.setExclusive(True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(10)

        brand = QLabel("KOLBE")
        brand.setStyleSheet("font-size: 18px; font-weight: 700; color: #00bcd4; letter-spacing: 0.15em;")
        layout.addWidget(brand)
        layout.addSpacing(8)

        device_label = QLabel("Controller")
        device_label.setStyleSheet("color: #8b93a7;")
        layout.addWidget(device_label)
        self.device_combo = QComboBox()
        self._configure_expanding_combo(self.device_combo)
        self.device_combo.currentIndexChanged.connect(self._on_device_changed)
        layout.addWidget(self.device_combo)

        midi_label = QLabel("MIDI Output")
        midi_label.setStyleSheet("color: #8b93a7;")
        layout.addWidget(midi_label)
        self.midi_combo = QComboBox()
        self._configure_expanding_combo(self.midi_combo)
        self.midi_combo.currentTextChanged.connect(self._handle_midi_changed)
        layout.addWidget(self.midi_combo)

        refresh_btn = QPushButton("Refresh Ports")
        refresh_btn.setToolTip("Refresh available MIDI output ports")
        refresh_btn.clicked.connect(self.refresh_midi_ports)
        layout.addWidget(refresh_btn)

        layout.addSpacing(8)

        page_label = QLabel("Page")
        page_label.setStyleSheet("color: #8b93a7;")
        layout.addWidget(page_label)
        self.page_container = QHBoxLayout()
        self.page_container.setSpacing(4)
        layout.addLayout(self.page_container)

        layout.addSpacing(8)

        self.preset_name_label = QLabel("Untitled")
        self.preset_name_label.setStyleSheet("color: #e8eaed; font-weight: 600; min-width: 70px;")
        layout.addWidget(self.preset_name_label)

        self.templates_combo = QComboBox()
        self._configure_expanding_combo(self.templates_combo, min_chars=10)
        self.templates_combo.addItem("Templates…", "")
        for name in PresetManager.TEMPLATE_NAMES:
            self.templates_combo.addItem(name, name)
        self.templates_combo.currentIndexChanged.connect(self._on_template_index_changed)
        layout.addWidget(self.templates_combo)

        save_btn = QPushButton("Save")
        save_btn.clicked.connect(lambda: self._on_save_preset and self._on_save_preset())
        layout.addWidget(save_btn)

        load_btn = QPushButton("Load")
        load_btn.clicked.connect(lambda: self._on_load_preset and self._on_load_preset())
        layout.addWidget(load_btn)

        cleanup_btn = QPushButton("Clean")
        cleanup_btn.setToolTip(
            "Clear all mappings to an empty show. Hardware slot assignments are kept."
        )
        cleanup_btn.clicked.connect(lambda: self._on_cleanup_project and self._on_cleanup_project())
        layout.addWidget(cleanup_btn)

        layout.addStretch()

        self.connection_label = QLabel("Controllers: 0")
        self.connection_label.setObjectName("statusDisconnected")
        layout.addWidget(self.connection_label)

        self.refresh_midi_ports(populate_only=True)
        self.set_pages(["Page 1", "Page 2", "Page 3"])

    @staticmethod
    def _configure_expanding_combo(combo: QComboBox, *, min_chars: int = 14) -> None:
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        combo.setMinimumContentsLength(min_chars)
        combo.setSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Fixed)
        combo.setMinimumWidth(140)

    def _fit_combo_to_contents(self, combo: QComboBox, *, pad: int = 48) -> None:
        metrics = QFontMetrics(combo.font())
        widest = metrics.horizontalAdvance("W" * max(1, combo.minimumContentsLength()))
        for index in range(combo.count()):
            widest = max(widest, metrics.horizontalAdvance(combo.itemText(index)))
        combo.setMinimumWidth(widest + pad)

    def set_devices(
        self,
        devices: dict[str, object],
        selected_id: Optional[str] = None,
        *,
        hardware_count: Optional[int] = None,
    ) -> None:
        current = selected_id or self.device_combo.currentData()
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        for device_id, device in devices.items():
            name = getattr(device, "name", device_id)
            self.device_combo.addItem(name, device_id)
        if current:
            idx = self.device_combo.findData(current)
            if idx >= 0:
                self.device_combo.setCurrentIndex(idx)
        self.device_combo.blockSignals(False)
        self._fit_combo_to_contents(self.device_combo)
        # Count physical pads when provided — never the fixed 4-slot array length.
        count = hardware_count if hardware_count is not None else len(devices)
        if count:
            self.connection_label.setText(f"Controllers: {count}")
            self.connection_label.setObjectName("statusConnected")
        else:
            self.connection_label.setText("Controllers: 0")
            self.connection_label.setObjectName("statusDisconnected")
        self.connection_label.style().unpolish(self.connection_label)
        self.connection_label.style().polish(self.connection_label)

    def set_pages(self, pages: list[str], active_page: int = 0) -> None:
        while self.page_container.count():
            item = self.page_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._page_buttons.clear()
        for btn in self._page_group.buttons():
            self._page_group.removeButton(btn)

        for index, name in enumerate(pages):
            btn = QPushButton(name)
            btn.setCheckable(True)
            metrics = QFontMetrics(btn.font())
            btn.setMinimumWidth(max(72, metrics.horizontalAdvance(name) + 24))
            btn.setProperty("page_id", index)
            btn.clicked.connect(lambda checked, i=index: self._select_page(i) if checked else None)
            self._page_group.addButton(btn, index)
            self.page_container.addWidget(btn)
            self._page_buttons.append(btn)

        if 0 <= active_page < len(self._page_buttons):
            self._page_buttons[active_page].setChecked(True)

    def set_active_page(self, page_id: int) -> None:
        if 0 <= page_id < len(self._page_buttons):
            self._page_buttons[page_id].setChecked(True)

    def _select_page(self, page_id: int) -> None:
        self.page_selected.emit(page_id)

    def _on_device_changed(self, _index: int) -> None:
        device_id = self.device_combo.currentData()
        if device_id:
            self.device_selected.emit(device_id)

    def _on_template_index_changed(self, index: int) -> None:
        if index <= 0:
            return
        template_name = self.templates_combo.itemData(index)
        if template_name and self._on_template_selected:
            self._on_template_selected(template_name)
        self.templates_combo.blockSignals(True)
        self.templates_combo.setCurrentIndex(0)
        self.templates_combo.blockSignals(False)

    def set_preset_name(self, name: str) -> None:
        self.preset_name_label.setText(name or "Untitled")

    def _midi_port_items(self) -> list[str]:
        items: list[str] = []
        if supports_virtual_midi():
            items.append(_virtual_port_label())
        for name in list_midi_ports()["outputs"]:
            if name not in items:
                items.append(name)
        return items

    def refresh_midi_ports(self, *, populate_only: bool = False, preferred_port: str = "") -> None:
        current = preferred_port or self._selected_port_name()
        self.midi_combo.blockSignals(True)
        self.midi_combo.clear()
        items = self._midi_port_items()
        if items:
            self.midi_combo.addItems(items)
        else:
            self.midi_combo.addItem("(no MIDI outputs)")
        self.midi_combo.blockSignals(False)
        self._fit_combo_to_contents(self.midi_combo)

        if populate_only:
            return

        selected = self._resolve_port_selection(current, items)
        if selected:
            self.select_midi_port(selected, emit_change=True)

    def _resolve_port_selection(self, preferred: str, items: list[str]) -> str:
        if preferred:
            if preferred == DEFAULT_PORT_NAME and supports_virtual_midi():
                virtual_label = _virtual_port_label()
                if virtual_label in items:
                    return virtual_label
            if preferred in items:
                return preferred
        if supports_virtual_midi():
            virtual_label = _virtual_port_label()
            if virtual_label in items:
                return virtual_label
        return items[0] if items else ""

    def select_midi_port(self, port_name: str, *, emit_change: bool = True) -> None:
        display_name = port_name
        if port_name == DEFAULT_PORT_NAME and supports_virtual_midi():
            display_name = _virtual_port_label()
        index = self.midi_combo.findText(display_name)
        if index < 0 and port_name:
            index = self.midi_combo.findText(port_name)
        if index < 0:
            return
        self.midi_combo.blockSignals(True)
        self.midi_combo.setCurrentIndex(index)
        self.midi_combo.blockSignals(False)
        if emit_change:
            self._handle_midi_changed(self.midi_combo.currentText())

    def _selected_port_name(self) -> str:
        text = self.midi_combo.currentText()
        return self._port_name_from_display(text)

    @staticmethod
    def _port_name_from_display(text: str) -> str:
        if text.startswith("Virtual: "):
            return text.replace("Virtual: ", "", 1)
        if text == "(no MIDI outputs)":
            return ""
        return text

    def _handle_midi_changed(self, text: str) -> None:
        if self._on_midi_port_changed and text and text != "(no MIDI outputs)":
            self._on_midi_port_changed(self._port_name_from_display(text))
