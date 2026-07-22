"""Main application window."""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from kolbe import APP_NAME
from kolbe.controller.slots import (
    SLOT_NUMBERS,
    accent_for_slot,
    led_color_for_slot,
    slot_id,
    slot_label,
)
from kolbe.controller.types import ControllerDevice, ControllerState, InputSource
from kolbe.gui.controller_slots_panel import ControllerSlotsPanel
from kolbe.gui.controller_thread import ControllerThread, PygameEventPump
from kolbe.gui.mapping_inspector import MappingInspectorPanel
from kolbe.gui.system_monitor import SystemMonitorWidget
from kolbe.gui.top_bar import TopBar
from kolbe.gui.visualizer_widget import VisualizerPanel
from kolbe.mapping.engine import MappingEngine
from kolbe.mapping.models import DEFAULT_DEVICE_SLOT, PresetData
from kolbe.mapping.preset_manager import PresetManager
from kolbe.midi.virtual_port import (
    DEFAULT_PORT_NAME,
    VirtualMidiPort,
    list_midi_ports,
    supports_virtual_midi,
)

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Kolbe main window — up to 4 fixed controller slots → MIDI."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} — Gamepad MIDI")
        self.setMinimumSize(1100, 820)
        self.resize(1360, 960)

        self._midi_port: Optional[VirtualMidiPort] = None
        self._controller_thread: Optional[ControllerThread] = None
        self._pygame_pump = PygameEventPump(self)
        self._mapping_engine = MappingEngine(self)
        self._preset_manager = PresetManager()
        self._selected_slot: int = 1
        self._hardware_devices: dict[str, ControllerDevice] = {}
        self._pending_states: dict[str, ControllerState] = {}  # keyed by slot id
        self._state_flush_scheduled = False
        self._accent_color = accent_for_slot(1)
        self._slot_states: dict[str, ControllerState] = {}  # slot id → latest state

        central = QWidget()
        central.setStyleSheet("background-color: #121212;")
        self.setCentralWidget(central)
        column_layout = QVBoxLayout(central)
        column_layout.setContentsMargins(0, 0, 0, 0)
        column_layout.setSpacing(0)

        self.top_bar = TopBar(
            on_midi_port_changed=self._on_midi_port_changed,
            on_save_preset=self._on_save_preset,
            on_load_preset=self._on_load_preset,
            on_template_selected=self._on_template_selected,
            on_cleanup_project=self._on_cleanup_project,
        )
        self.top_bar.page_selected.connect(self._on_page_selected)
        self.top_bar.device_selected.connect(self._on_topbar_slot_selected)
        column_layout.addWidget(self.top_bar)

        self.connection_bar = QLabel("Waiting for controllers…")
        self.connection_bar.setObjectName("connectionBar")
        self.connection_bar.setContentsMargins(16, 6, 16, 6)
        self.connection_bar.setStyleSheet(
            "background-color: #252525; color: #888888; border-bottom: 1px solid #333333; padding: 4px 16px;"
        )
        column_layout.addWidget(self.connection_bar)

        self.slots_panel = ControllerSlotsPanel()
        self.slots_panel.slot_selected.connect(self._on_slot_selected)
        self.slots_panel.slot_assignment_changed.connect(self._on_slot_assignment_changed)
        self.slots_panel.refresh_requested.connect(self._on_rescan_controllers)
        column_layout.addWidget(self.slots_panel)

        main_splitter = QSplitter(Qt.Orientation.Vertical)
        main_splitter.setHandleWidth(2)

        upper = QWidget()
        upper_layout = QHBoxLayout(upper)
        upper_layout.setContentsMargins(0, 0, 0, 0)

        h_splitter = QSplitter(Qt.Orientation.Horizontal)
        h_splitter.setHandleWidth(2)

        self.visualizer_panel = VisualizerPanel()
        self.visualizer_panel.source_clicked.connect(self._on_visualizer_source_clicked)

        inspector_wrapper = QWidget()
        inspector_wrapper.setObjectName("panel")
        iw_layout = QHBoxLayout(inspector_wrapper)
        iw_layout.setContentsMargins(10, 10, 10, 10)
        self.mapping_panel = MappingInspectorPanel(engine=self._mapping_engine)
        iw_layout.addWidget(self.mapping_panel)

        h_splitter.addWidget(self.visualizer_panel)
        h_splitter.addWidget(inspector_wrapper)
        h_splitter.setStretchFactor(0, 11)
        h_splitter.setStretchFactor(1, 9)
        h_splitter.setSizes([620, 520])
        upper_layout.addWidget(h_splitter)

        main_splitter.addWidget(upper)
        self.system_monitor = SystemMonitorWidget()
        self.system_monitor.setMinimumHeight(120)
        main_splitter.addWidget(self.system_monitor)
        main_splitter.setStretchFactor(0, 1)
        main_splitter.setStretchFactor(1, 0)
        main_splitter.setSizes([660, 160])

        column_layout.addWidget(main_splitter, stretch=1)

        self.mapping_panel.mappings_changed.connect(self._on_mappings_changed)
        self._mapping_engine.monitor_line.connect(self.system_monitor.append_line)
        self._mapping_engine.page_changed.connect(self._on_engine_page_changed)

        preset = self._preset_manager.load_startup_preset()
        self._apply_preset(preset)
        self.system_monitor.log_system("Kolbe started — 4 controller slots ready")
        self._apply_slot_accent(self._selected_slot)
        self._start_controller_thread()

    def _edit_device_id(self) -> str:
        """Mappings are stamped with the selected logical slot key."""
        return slot_id(self._selected_slot)

    def _edit_page_id(self) -> int:
        return self._mapping_engine.active_page(self._edit_device_id())

    def _apply_preset(self, preset: PresetData) -> None:
        self._mapping_engine.load_preset(preset)
        self.slots_panel.apply_assignments(preset.slot_assignments)
        self.top_bar.set_pages(preset.pages)
        self._sync_topbar_slots()
        self.mapping_panel.set_edit_context(self._edit_device_id(), self._edit_page_id())
        self.mapping_panel.refresh_from_engine()
        self._refresh_mapped_indicators()
        self._preset_manager.current_name = preset.name
        self.top_bar.set_preset_name(preset.name)
        self._apply_midi_output_port(preset.midi_output_port)
        self._mapping_engine.log_system(
            f"Preset loaded: {preset.name} ({len(preset.mappings)} mappings)"
        )
        logger.info("Preset applied: %s", preset.name)

    def _persist_slot_assignments(self) -> None:
        preset = self._mapping_engine.preset
        preset.slot_assignments = self.slots_panel.assignments()
        try:
            self._preset_manager.save_startup_preset(preset)
        except OSError as exc:
            logger.warning("Could not save slot assignments: %s", exc)

    def _apply_midi_output_port(self, port_name: str) -> None:
        self.top_bar.refresh_midi_ports(preferred_port=port_name)
        if not supports_virtual_midi() and not list_midi_ports()["outputs"]:
            self._mapping_engine.set_midi_port(None)
            self.system_monitor.append_line(
                "No MIDI output ports found. Install loopMIDI or another virtual MIDI driver.",
                "warning",
            )

    def _refresh_mapped_indicators(self) -> None:
        device_id = self._edit_device_id()
        page_id = self._edit_page_id()
        sources: set[InputSource] = set()
        labels: dict[InputSource, str] = {}
        for mapping in self._mapping_engine.mappings:
            if mapping.page_id != page_id:
                continue
            if mapping.device_slot not in (device_id, DEFAULT_DEVICE_SLOT):
                continue
            sources.add(mapping.source)
            labels[mapping.source] = mapping.compact_target_label()
        self.visualizer_panel.set_mapped_sources(sources)
        self.visualizer_panel.set_mapping_labels(labels)

    def _on_visualizer_source_clicked(self, source: InputSource) -> None:
        self.visualizer_panel.set_selected_source(source)
        self.mapping_panel.select_source(source)

    def _on_mappings_changed(self, _mappings: list) -> None:
        self._refresh_mapped_indicators()
        if self._preset_manager.current_path is None:
            self._preset_manager.mark_untitled()
            self.top_bar.set_preset_name("Untitled")

    def _on_page_selected(self, page_id: int) -> None:
        device_id = self._edit_device_id()
        self._mapping_engine.set_active_page(device_id, page_id)
        self.mapping_panel.set_edit_context(device_id, page_id)
        self.mapping_panel.refresh_from_engine()
        self._refresh_mapped_indicators()
        if device_id in self._slot_states:
            self.visualizer_panel.update_state(self._slot_states[device_id])

    def _on_topbar_slot_selected(self, slot_key: str) -> None:
        try:
            number = int(slot_key)
        except (TypeError, ValueError):
            return
        self._on_slot_selected(number)

    def _on_slot_selected(self, slot: int) -> None:
        if slot not in SLOT_NUMBERS:
            return
        self._selected_slot = int(slot)
        self.slots_panel.set_selected_slot(slot)
        self._apply_slot_accent(slot)
        device_id = slot_id(slot)
        page_id = self._mapping_engine.active_page(device_id)
        self.top_bar.set_active_page(page_id)
        # Keep top-bar combo in sync without re-entry loops.
        idx = self.top_bar.device_combo.findData(device_id)
        if idx >= 0 and self.top_bar.device_combo.currentIndex() != idx:
            self.top_bar.device_combo.blockSignals(True)
            self.top_bar.device_combo.setCurrentIndex(idx)
            self.top_bar.device_combo.blockSignals(False)

        self.mapping_panel.set_edit_context(device_id, page_id)
        self.mapping_panel.refresh_from_engine()
        self._refresh_mapped_indicators()

        snap = next((s for s in self.slots_panel.snapshot_slots() if s.number == slot), None)
        if snap and snap.connected and device_id in self._slot_states:
            self.visualizer_panel.update_state(self._slot_states[device_id])
            self.connection_bar.setText(f"Editing: {slot_label(slot)} — {snap.display_name}")
            self.connection_bar.setStyleSheet(
                f"background-color: #252525; color: {self._accent_color}; "
                f"border-bottom: 1px solid {self._accent_color}; padding: 4px 16px;"
            )
        elif snap and snap.hardware_id and not snap.connected:
            self.connection_bar.setText(f"{slot_label(slot)} — Disconnected")
            self.connection_bar.setStyleSheet(
                "background-color: #252525; color: #FF6B6B; "
                "border-bottom: 1px solid #FF6B6B; padding: 4px 16px;"
            )
        else:
            self.connection_bar.setText(f"{slot_label(slot)} — Empty (assign a gamepad)")
            self.connection_bar.setStyleSheet(
                "background-color: #252525; color: #888888; "
                "border-bottom: 1px solid #333333; padding: 4px 16px;"
            )

    def _on_slot_assignment_changed(self, slot: int, _hardware_id: object) -> None:
        self._sync_topbar_slots()
        self._persist_slot_assignments()
        self._sync_slot_leds()
        self._mapping_engine.log_system(f"{slot_label(slot)} assignment updated")
        if slot == self._selected_slot:
            self._on_slot_selected(slot)

    def _sync_slot_leds(self) -> None:
        """Push each connected pad's slot theme color to its lightbar."""
        if self._controller_thread is None:
            return
        colors: dict[str, Optional[tuple[int, int, int]]] = {}
        for slot in self.slots_panel.snapshot_slots():
            if slot.connected and slot.hardware_id:
                colors[slot.hardware_id] = led_color_for_slot(slot.number)
        self._controller_thread.apply_slot_leds(colors)

    def _on_rescan_controllers(self) -> None:
        if self._controller_thread is not None:
            self._controller_thread.request_refresh()
            self._mapping_engine.log_system("Controller rescan requested")

    def _apply_slot_accent(self, slot: int) -> None:
        color = accent_for_slot(slot)
        self._accent_color = color
        self.visualizer_panel.set_accent_color(color)
        self.mapping_panel.set_accent_color(color)

    def _sync_topbar_slots(self) -> None:
        devices: dict[str, object] = {}
        for slot in self.slots_panel.snapshot_slots():
            key = slot.slot_key
            if slot.connected and slot.device is not None:
                label = f"{slot_label(slot.number)}: {slot.device.name}"
            elif slot.hardware_id:
                label = f"{slot_label(slot.number)}: Disconnected"
            else:
                label = f"{slot_label(slot.number)}: Empty"
            devices[key] = type("Dev", (), {"name": label})()
        self.top_bar.set_devices(
            devices,
            slot_id(self._selected_slot),
            hardware_count=len(self._hardware_devices),
        )

    def _on_engine_page_changed(self, device_id: str, page_id: int) -> None:
        if device_id == self._edit_device_id():
            self.top_bar.set_active_page(page_id)
            self.mapping_panel.set_edit_context(device_id, page_id)
            self.mapping_panel.refresh_from_engine()
            self._refresh_mapped_indicators()

    def _on_save_preset(self) -> None:
        preset = self._mapping_engine.preset
        preset.slot_assignments = self.slots_panel.assignments()
        if self._preset_manager.save_with_dialog(self, preset):
            self.top_bar.set_preset_name(preset.name)
            self._preset_manager.save_startup_preset(preset)

    def _on_load_preset(self) -> None:
        preset = self._preset_manager.load_with_dialog(self)
        if preset is None:
            return
        self._apply_preset(preset)
        self._preset_manager.save_startup_preset(preset)

    def _on_cleanup_project(self) -> None:
        """Global reset: empty show (no mappings) while keeping hardware slot assignments."""
        reply = QMessageBox.question(
            self,
            "Clean Show",
            "Clear all mappings and reset to an empty show?\n\n"
            "Hardware slot assignments will be kept. Controllers stay connected.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        slots = self.slots_panel.assignments()
        midi_port = self._mapping_engine.preset.midi_output_port
        empty = PresetData(
            name="Untitled",
            slot_assignments=dict(slots),
            midi_output_port=midi_port,
        )
        self._apply_preset(empty)
        self._preset_manager.mark_untitled()
        try:
            self._preset_manager.save_startup_preset(empty)
        except OSError as exc:
            logger.warning("Could not save cleaned show: %s", exc)
        self._mapping_engine.log_system(
            "Show cleaned — all mappings cleared; slot assignments preserved"
        )

    def _on_template_selected(self, template_name: str) -> None:
        reply = QMessageBox.question(
            self,
            "Load Template",
            f'Load the "{template_name}" template? This will replace your current mappings.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        preset = self._preset_manager.apply_template(template_name)
        preset.slot_assignments = self.slots_panel.assignments()
        self._apply_preset(preset)
        self._preset_manager.save_startup_preset(preset)

    def _on_midi_port_changed(self, port_name: str) -> None:
        if self._midi_port is not None:
            self._midi_port.close()
            self._midi_port = None

        use_virtual = supports_virtual_midi() and port_name == DEFAULT_PORT_NAME
        self._midi_port = VirtualMidiPort(port_name, use_virtual=use_virtual)
        try:
            self._midi_port.open()
            self._mapping_engine.set_midi_port(self._midi_port)
            port_kind = "Virtual MIDI" if use_virtual else "MIDI output"
            self._mapping_engine.log_system(f"{port_kind} port opened: {port_name}")
            logger.info("MIDI port active: %s", port_name)
        except RuntimeError as exc:
            logger.error("MIDI port error: %s", exc)
            self._midi_port = None
            self._mapping_engine.set_midi_port(None)
            self.system_monitor.append_line(f"MIDI port warning: {exc}", "warning")

        preset = self._mapping_engine.preset
        preset.midi_output_port = port_name
        preset.slot_assignments = self.slots_panel.assignments()
        try:
            self._preset_manager.save_startup_preset(preset)
        except OSError as exc:
            logger.warning("Could not save MIDI port preference: %s", exc)

    def _start_controller_thread(self) -> None:
        self._pygame_pump.start()
        self._controller_thread = ControllerThread()
        self._controller_thread.state_updated.connect(self._on_state_updated)
        self._controller_thread.devices_changed.connect(self._on_devices_changed)
        self._controller_thread.error_occurred.connect(self._on_controller_error)
        self._controller_thread.start()

    def _on_devices_changed(self, devices: dict) -> None:
        self._hardware_devices = dict(devices)
        self.slots_panel.set_hardware_devices(self._hardware_devices)
        # Keep persisted assignments when possible; auto-fill empties.
        self._persist_slot_assignments()
        self._sync_topbar_slots()
        self._sync_slot_leds()

        connected = [s for s in self.slots_panel.snapshot_slots() if s.connected]
        if connected:
            names = ", ".join(f"{slot_label(s.number)}={s.display_name}" for s in connected)
            self.connection_bar.setText(f"Live: {names}")
            self.connection_bar.setStyleSheet(
                f"background-color: #252525; color: {self._accent_color}; "
                f"border-bottom: 1px solid #333333; padding: 4px 16px;"
            )
        else:
            self.connection_bar.setText("No controllers connected — plug in a pad and hit Refresh")
            self.connection_bar.setStyleSheet(
                "background-color: #252525; color: #888888; "
                "border-bottom: 1px solid #333333; padding: 4px 16px;"
            )

        # Drop cached states for slots whose hardware left.
        live_slot_keys = {s.slot_key for s in self.slots_panel.snapshot_slots() if s.connected}
        for key in list(self._slot_states):
            if key not in live_slot_keys:
                self._slot_states.pop(key, None)

        self._mapping_engine.log_system(
            f"Controllers updated: {len(devices)} hardware / {len(connected)} slotted"
        )
        self._on_slot_selected(self._selected_slot)

    def _remap_state_to_slot(self, state: ControllerState) -> Optional[ControllerState]:
        """Bind hardware input to its logical slot for MIDI (independent per slot)."""
        hardware_id = state.device.id
        slot_number = self.slots_panel.registry.slot_for_hardware(hardware_id)
        if slot_number is None:
            return None
        slot_device = replace(state.device, id=slot_id(slot_number))
        return replace(state, device=slot_device)

    def _on_state_updated(self, state: ControllerState) -> None:
        remapped = self._remap_state_to_slot(state)
        if remapped is None:
            return
        # Prefer HID companion / report label; Wired must win over a stale percent.
        label = state.battery_label
        if label == "Wired":
            self.slots_panel.update_battery(state.device.id, None, "Wired")
        elif label:
            self.slots_panel.update_battery(state.device.id, state.battery_percent, label)
        elif state.battery_percent is None:
            self.slots_panel.update_battery(state.device.id, None, "Wired")
        else:
            self.slots_panel.update_battery(state.device.id, state.battery_percent)
        # Latest-wins coalesce per slot so simultaneous pads never block each other.
        self._pending_states[remapped.device.id] = remapped
        if not self._state_flush_scheduled:
            self._state_flush_scheduled = True
            QTimer.singleShot(0, self._flush_pending_states)

    def _flush_pending_states(self) -> None:
        self._state_flush_scheduled = False
        pending = self._pending_states
        self._pending_states = {}
        selected_key = self._edit_device_id()
        for state in pending.values():
            slot_key = state.device.id
            self._slot_states[slot_key] = state
            # Independent MIDI dispatch per slot — no shared mutable gate.
            self._mapping_engine.process_state(state)
            self.system_monitor.record_frame()
            if state.active_buttons() or state.non_zero_axes():
                self.system_monitor.record_activity()
            if slot_key == selected_key:
                self.visualizer_panel.update_state(state)

    def _on_controller_error(self, message: str) -> None:
        logger.warning("Controller error: %s", message)
        self.connection_bar.setText(message)
        self.connection_bar.setStyleSheet(
            "background-color: #252525; color: #FF3333; border-bottom: 1px solid #333333; padding: 4px 16px;"
        )
        self._mapping_engine.log_system(f"Controller error: {message}")

    def closeEvent(self, event) -> None:  # noqa: N802
        if getattr(self, "_shutdown_complete", False):
            event.accept()
            return

        logger.info("Application shutdown started")
        self._shutdown_complete = True
        self._persist_slot_assignments()

        if self._controller_thread is not None:
            self._controller_thread.stop()
            self._controller_thread = None

        try:
            from kolbe.controller.hid_lifecycle import force_close_all_hid_handles

            force_close_all_hid_handles()
        except Exception:
            logger.debug("HID force-close on window close failed", exc_info=True)

        self._mapping_engine.shutdown()

        if self._midi_port is not None:
            self._midi_port.close()
            self._midi_port = None

        self._pygame_pump.stop()
        PygameEventPump.shutdown_pygame()

        logger.info("Application shutdown complete")
        event.accept()
        super().closeEvent(event)
        from PyQt6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            app.quit()
