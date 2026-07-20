"""Main application window."""

from __future__ import annotations

import logging
from typing import Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QHBoxLayout, QMainWindow, QMessageBox, QSplitter, QVBoxLayout, QWidget, QLabel

from kolbe.controller.types import ControllerDevice, ControllerState, InputSource
from kolbe import APP_NAME
from kolbe.gui.styles import accent_for_controller_index
from kolbe.gui.controller_thread import ControllerThread, PygameEventPump
from kolbe.gui.mapping_inspector import MappingInspectorPanel
from kolbe.gui.system_monitor import SystemMonitorWidget
from kolbe.gui.top_bar import TopBar
from kolbe.gui.visualizer_widget import VisualizerPanel
from kolbe.mapping.engine import MappingEngine
from kolbe.mapping.models import DEFAULT_DEVICE_SLOT, Mapping, PresetData
from kolbe.mapping.preset_manager import PresetManager
from kolbe.midi.virtual_port import DEFAULT_PORT_NAME, VirtualMidiPort, list_midi_ports, supports_virtual_midi

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Kolbe main window — multi-device show control station."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} — Gamepad MIDI")
        self.setMinimumSize(1100, 760)
        self.resize(1360, 900)

        self._midi_port: Optional[VirtualMidiPort] = None
        self._controller_thread: Optional[ControllerThread] = None
        self._pygame_pump = PygameEventPump(self)
        self._mapping_engine = MappingEngine(self)
        self._preset_manager = PresetManager()
        self._selected_device_id: Optional[str] = None
        self._device_order: list[str] = []
        self._pending_states: dict[str, ControllerState] = {}
        self._state_flush_scheduled = False
        self._accent_color = accent_for_controller_index(0)
        self._device_states: dict[str, ControllerState] = {}

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
        self.top_bar.device_selected.connect(self._on_device_selected)
        column_layout.addWidget(self.top_bar)

        self.connection_bar = QLabel("Waiting for controllers…")
        self.connection_bar.setObjectName("connectionBar")
        self.connection_bar.setContentsMargins(16, 6, 16, 6)
        self.connection_bar.setStyleSheet(
            "background-color: #252525; color: #888888; border-bottom: 1px solid #333333; padding: 4px 16px;"
        )
        column_layout.addWidget(self.connection_bar)

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
        self.system_monitor.log_system("Kolbe started")
        self.visualizer_panel.set_accent_color(self._accent_color)
        self.mapping_panel.set_accent_color(self._accent_color)

        self._start_controller_thread()

    def _edit_device_id(self) -> str:
        return self._selected_device_id or DEFAULT_DEVICE_SLOT

    def _edit_page_id(self) -> int:
        if self._selected_device_id:
            return self._mapping_engine.active_page(self._selected_device_id)
        return 0

    def _apply_preset(self, preset: PresetData) -> None:
        self._mapping_engine.load_preset(preset)
        self.top_bar.set_pages(preset.pages)
        self.mapping_panel.set_edit_context(self._edit_device_id(), self._edit_page_id())
        self.mapping_panel.refresh_from_engine()
        self._refresh_mapped_indicators()
        self._preset_manager.current_name = preset.name
        self.top_bar.set_preset_name(preset.name)
        self._apply_midi_output_port(preset.midi_output_port)
        self._mapping_engine.log_system(f"Preset loaded: {preset.name} ({len(preset.mappings)} mappings)")
        logger.info("Preset applied: %s", preset.name)

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
        if device_id != DEFAULT_DEVICE_SLOT:
            self._mapping_engine.set_active_page(device_id, page_id)
        self.mapping_panel.set_edit_context(device_id, page_id)
        self.mapping_panel.refresh_from_engine()
        self._refresh_mapped_indicators()
        if self._selected_device_id and self._selected_device_id in self._device_states:
            self.visualizer_panel.update_state(self._device_states[self._selected_device_id])

    def _on_device_selected(self, device_id: str) -> None:
        self._selected_device_id = device_id
        self._apply_controller_accent(device_id)
        page_id = self._mapping_engine.active_page(device_id)
        self.top_bar.set_active_page(page_id)
        self.mapping_panel.set_edit_context(device_id, page_id)
        self.mapping_panel.refresh_from_engine()
        self._refresh_mapped_indicators()
        if device_id in self._device_states:
            self.visualizer_panel.update_state(self._device_states[device_id])
            self.connection_bar.setText(f"Editing: {self._device_states[device_id].device.name}")
            self.connection_bar.setStyleSheet(
                f"background-color: #252525; color: {self._accent_color}; "
                f"border-bottom: 1px solid {self._accent_color}; padding: 4px 16px;"
            )

    def _apply_controller_accent(self, device_id: str) -> None:
        try:
            index = self._device_order.index(device_id)
        except ValueError:
            index = 0
        color = accent_for_controller_index(index)
        self._accent_color = color
        self.visualizer_panel.set_accent_color(color)
        self.mapping_panel.set_accent_color(color)

    def _on_engine_page_changed(self, device_id: str, page_id: int) -> None:
        if device_id == self._selected_device_id:
            self.top_bar.set_active_page(page_id)
            self.mapping_panel.set_edit_context(device_id, page_id)
            self.mapping_panel.refresh_from_engine()
            self._refresh_mapped_indicators()

    def _on_save_preset(self) -> None:
        preset = self._mapping_engine.preset
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
        from kolbe.utils.project_cleanup import cleanup_project

        removed = cleanup_project()
        if removed:
            summary = "\n".join(str(p) for p in removed[:12])
            extra = f"\n…and {len(removed) - 12} more" if len(removed) > 12 else ""
            QMessageBox.information(
                self,
                "Project Cleanup",
                f"Removed {len(removed)} junk path(s):\n{summary}{extra}",
            )
            self._mapping_engine.log_system(f"Project cleanup removed {len(removed)} junk path(s)")
        else:
            QMessageBox.information(self, "Project Cleanup", "No junk files found.")

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
        previous = list(self._device_order)
        # Keep stable color indices for devices that remain connected.
        self._device_order = [did for did in previous if did in devices]
        for device_id in devices:
            if device_id not in self._device_order:
                self._device_order.append(device_id)

        self.top_bar.set_devices(devices, self._selected_device_id)
        if not self._selected_device_id and devices:
            first_id = next(iter(devices.keys()))
            self.top_bar.device_combo.setCurrentIndex(0)
            self._on_device_selected(first_id)
        elif self._selected_device_id and self._selected_device_id in devices:
            self._apply_controller_accent(self._selected_device_id)
        names = ", ".join(getattr(d, "name", k) for k, d in devices.items())
        self.connection_bar.setText(f"Connected: {names}" if names else "No controllers")
        accent = self._accent_color if names else "#888888"
        self.connection_bar.setStyleSheet(
            f"background-color: #252525; color: {accent}; border-bottom: 1px solid #333333; padding: 4px 16px;"
        )
        self._mapping_engine.log_system(f"Controllers updated: {len(devices)} connected")

    def _on_state_updated(self, state: ControllerState) -> None:
        # Latest-wins coalesce: drain at most one flush per event-loop turn so a
        # queued burst of signals never runs process_state N times for stale snaps.
        self._pending_states[state.device.id] = state
        if not self._state_flush_scheduled:
            self._state_flush_scheduled = True
            QTimer.singleShot(0, self._flush_pending_states)

    def _flush_pending_states(self) -> None:
        self._state_flush_scheduled = False
        pending = self._pending_states
        self._pending_states = {}
        for state in pending.values():
            device_id = state.device.id
            self._device_states[device_id] = state
            self._mapping_engine.process_state(state)
            self.system_monitor.record_frame()
            if state.active_buttons() or state.non_zero_axes():
                self.system_monitor.record_activity()
            if device_id == self._selected_device_id:
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

        if self._controller_thread is not None:
            self._controller_thread.stop()
            self._controller_thread = None

        self._mapping_engine.shutdown()

        if self._midi_port is not None:
            self._midi_port.close()
            self._midi_port = None

        self._pygame_pump.stop()
        PygameEventPump.shutdown_pygame()

        logger.info("Application shutdown complete")
        event.accept()
        super().closeEvent(event)
