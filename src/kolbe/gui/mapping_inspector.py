"""Inspector panel — edit mappings for the selected device, page, and input."""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from kolbe.controller.types import InputSource
from kolbe.mapping.engine import MappingEngine
from kolbe.mapping.models import (
    AnalogBehaviorMode,
    CHAIN_TARGET_TYPES,
    DEFAULT_DEVICE_SLOT,
    DigitalMode,
    MacroActionType,
    MacroStep,
    Mapping,
    MidiTarget,
    ResponseCurve,
    SplitTargetKind,
    SystemCommand,
    TargetType,
    is_analog_source,
    is_digital_source,
    source_label,
)


class MappingInspectorPanel(QWidget):
    mappings_changed = pyqtSignal(list)

    def __init__(self, engine: MappingEngine, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._engine = engine
        self._selected: Optional[InputSource] = None
        self._editing_mapping: Optional[Mapping] = None
        self._device_slot: str = DEFAULT_DEVICE_SLOT
        self._page_id: int = 0
        self._block_apply = False
        self._locked = True
        self.setStyleSheet(
            "QGroupBox { color: #FFFFFF; font-weight: 700; }"
            "QFormLayout QLabel, QLabel { color: #E4E8F0; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.context_label = QLabel("")
        self.context_label.setStyleSheet("color: #B0B8C8; font-size: 11px;")
        layout.addWidget(self.context_label)

        title_row = QHBoxLayout()
        title = QLabel("MAPPING INSPECTOR")
        title.setObjectName("sectionTitle")
        title_row.addWidget(title)
        title_row.addStretch()
        self.lock_btn = QPushButton("Locked")
        self.lock_btn.setCheckable(True)
        self.lock_btn.setChecked(True)
        self.lock_btn.setToolTip("When locked, mapping fields are read-only to prevent accidental live edits.")
        self.lock_btn.setStyleSheet(
            "QPushButton { min-width: 88px; font-weight: 700; }"
            "QPushButton:checked { color: #121212; background: #FFB347; border-color: #FFB347; }"
            "QPushButton:!checked { color: #121212; background: #44FF88; border-color: #44FF88; }"
        )
        self.lock_btn.toggled.connect(self._on_lock_toggled)
        title_row.addWidget(self.lock_btn)
        layout.addLayout(title_row)

        self.source_title = QLabel("Click a control on the visualizer")
        self.source_title.setStyleSheet("color: #FFFFFF; font-size: 15px; font-weight: 600;")
        self.source_title.setWordWrap(True)
        layout.addWidget(self.source_title)

        self.stack = QStackedWidget()

        empty_page = QWidget()
        el = QVBoxLayout(empty_page)
        self.empty_label = QLabel("")
        self.empty_label.setWordWrap(True)
        el.addWidget(self.empty_label)
        self.add_btn = QPushButton("Add Mapping")
        self.add_btn.clicked.connect(self._on_add_mapping)
        el.addWidget(self.add_btn)
        el.addStretch()
        self.stack.addWidget(empty_page)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        editor = QWidget()
        editor_layout = QVBoxLayout(editor)

        self.behavior_widget = QWidget()
        bf = QFormLayout(self.behavior_widget)
        self.behavior_combo = QComboBox()
        self.behavior_combo.addItem("Continuous (Full Axis)", AnalogBehaviorMode.CONTINUOUS)
        self.behavior_combo.addItem("Split (Two Halves)", AnalogBehaviorMode.SPLIT)
        self.behavior_combo.currentIndexChanged.connect(self._on_behavior_changed)
        bf.addRow("Mode", self.behavior_combo)

        editor_layout.addWidget(self.behavior_widget)

        timing_group = QGroupBox("Output Behavior")
        timing_form = QFormLayout(timing_group)

        self.continuous_hold_check = QCheckBox("Continuous Hold (repeat Note On while pressed)")
        self.continuous_hold_check.setToolTip(
            "While held (button pressed or stick past threshold), repeatedly send Note On. "
            "Sticks use the axis threshold (default 50%) as the hold zone."
        )

        self.fade_in_spin = QDoubleSpinBox()
        self.fade_in_spin.setRange(0.0, 60.0)
        self.fade_in_spin.setSingleStep(0.1)
        self.fade_in_spin.setDecimals(2)
        self.fade_in_spin.setSuffix(" s")
        self.fade_in_spin.setValue(0.0)
        self.fade_in_spin.setToolTip("Smoothly ramp output from 0 to full value on press (0 = instant)")

        self.fade_out_spin = QDoubleSpinBox()
        self.fade_out_spin.setRange(0.0, 60.0)
        self.fade_out_spin.setSingleStep(0.1)
        self.fade_out_spin.setDecimals(2)
        self.fade_out_spin.setSuffix(" s")
        self.fade_out_spin.setValue(0.0)
        self.fade_out_spin.setToolTip("Smoothly ramp output from full value to 0 on release (0 = instant)")

        timing_form.addRow(self.continuous_hold_check)
        timing_form.addRow("Fade In Time", self.fade_in_spin)
        timing_form.addRow("Fade Out Time", self.fade_out_spin)
        editor_layout.addWidget(timing_group)

        self.mode_stack = QStackedWidget()

        # Continuous target panel (primary)
        cont = QWidget()
        cont_layout = QVBoxLayout(cont)
        tg = QGroupBox("Target")
        tl = QVBoxLayout(tg)

        type_row = QHBoxLayout()
        self.note_radio = QRadioButton("Note")
        self.cc_radio = QRadioButton("CC")
        self.pitch_radio = QRadioButton("Pitch Bend")
        self.velocity_fader_radio = QRadioButton("Vel Fader")
        self.macro_radio = QRadioButton("Macro")
        self.system_radio = QRadioButton("System")
        self._target_radios = (
            (self.note_radio, "#5CE1FF"),
            (self.cc_radio, "#FFB347"),
            (self.pitch_radio, "#C793FF"),
            (self.velocity_fader_radio, "#44FF88"),
            (self.macro_radio, "#FF6B9D"),
            (self.system_radio, "#FFE66D"),
        )
        self._accent_color = "#44FF88"
        self._apply_target_radio_styles()
        for r, _color in self._target_radios:
            r.toggled.connect(self._update_panels)
        type_row.addWidget(self.note_radio)
        type_row.addWidget(self.cc_radio)
        type_row.addWidget(self.pitch_radio)
        type_row.addWidget(self.velocity_fader_radio)
        type_row.addWidget(self.macro_radio)
        type_row.addWidget(self.system_radio)
        type_row.addStretch()
        tl.addLayout(type_row)

        self.settings_stack = QStackedWidget()

        # Note page
        np = QWidget()
        nf = QFormLayout(np)
        self.channel_spin = self._spin(1, 16, 1)
        self.notes_edit = QLineEdit("60")
        self.velocity_spin = self._spin(0, 127, 127)
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Momentary", DigitalMode.MOMENTARY)
        self.mode_combo.addItem("Toggle", DigitalMode.TOGGLE)
        self.mode_combo.addItem("Double-Tap", DigitalMode.DOUBLE_TAP)
        self.mode_combo.addItem("Long-Press", DigitalMode.LONG_PRESS)
        self.threshold_check = QCheckBox("Use axis threshold")
        self.threshold_spin = self._spin(1, 100, 50)
        self.threshold_spin.setSuffix("%")
        self.threshold_check.toggled.connect(self.threshold_spin.setEnabled)
        self.double_tap_spin = self._spin(100, 1000, 300)
        self.double_tap_spin.setSuffix(" ms")
        self.long_press_spin = self._spin(200, 3000, 500)
        self.long_press_spin.setSuffix(" ms")
        nf.addRow("Channel", self.channel_spin)
        nf.addRow("Note(s)", self.notes_edit)
        nf.addRow("Velocity", self.velocity_spin)
        nf.addRow("Note Mode", self.mode_combo)
        nf.addRow("Double-Tap Window", self.double_tap_spin)
        nf.addRow("Long-Press Hold", self.long_press_spin)
        nf.addRow(self.threshold_check)
        nf.addRow("Threshold", self.threshold_spin)
        self.settings_stack.addWidget(np)

        # CC page
        cp = QWidget()
        cf = QFormLayout(cp)
        self.cc_channel_spin = self._spin(1, 16, 1)
        self.cc_number_spin = self._spin(0, 127, 1)
        self.cc_min_spin = self._spin(0, 127, 0)
        self.cc_max_spin = self._spin(0, 127, 127)
        self.cc_deadzone_spin = self._spin(0, 50, 10)
        self.cc_deadzone_spin.setSuffix("%")
        self.cc_invert_check = QCheckBox("Invert axis")
        self.invert_output_check = QCheckBox("Invert output")
        self.curve_combo = QComboBox()
        for c in ResponseCurve:
            self.curve_combo.addItem(c.value.title(), c)
        self.cc_offset_spin = QSpinBox()
        self.cc_offset_spin.setRange(-100, 100)
        self.cc_offset_spin.setSuffix("%")
        cf.addRow("Channel", self.cc_channel_spin)
        cf.addRow("CC Number", self.cc_number_spin)
        cf.addRow("Min", self.cc_min_spin)
        cf.addRow("Max", self.cc_max_spin)
        cf.addRow("Deadzone", self.cc_deadzone_spin)
        cf.addRow("Response Curve", self.curve_combo)
        cf.addRow("Offset", self.cc_offset_spin)
        cf.addRow(self.cc_invert_check)
        cf.addRow(self.invert_output_check)
        self.settings_stack.addWidget(cp)

        # Pitch page
        pp = QWidget()
        pf = QFormLayout(pp)
        self.pitch_channel_spin = self._spin(1, 16, 1)
        self.pitch_min_spin = self._spin(0, 127, 0)
        self.pitch_max_spin = self._spin(0, 127, 127)
        self.pitch_deadzone_spin = self._spin(0, 50, 10)
        self.pitch_deadzone_spin.setSuffix("%")
        self.pitch_invert_check = QCheckBox("Invert axis")
        self.pitch_invert_output_check = QCheckBox("Invert output")
        self.pitch_curve_combo = QComboBox()
        for c in ResponseCurve:
            self.pitch_curve_combo.addItem(c.value.title(), c)
        pf.addRow("Channel", self.pitch_channel_spin)
        pf.addRow("Min", self.pitch_min_spin)
        pf.addRow("Max", self.pitch_max_spin)
        pf.addRow("Deadzone", self.pitch_deadzone_spin)
        pf.addRow("Response Curve", self.pitch_curve_combo)
        pf.addRow(self.pitch_invert_check)
        pf.addRow(self.pitch_invert_output_check)
        self.settings_stack.addWidget(pp)

        # Velocity fader page (grandMA2)
        vfp = QWidget()
        vff = QFormLayout(vfp)
        self.vf_channel_spin = self._spin(1, 16, 1)
        self.vf_notes_edit = QLineEdit("60")
        self.vf_min_spin = self._spin(0, 127, 0)
        self.vf_max_spin = self._spin(0, 127, 127)
        self.vf_deadzone_spin = self._spin(0, 50, 10)
        self.vf_deadzone_spin.setSuffix("%")
        self.vf_curve_combo = QComboBox()
        for c in ResponseCurve:
            self.vf_curve_combo.addItem(c.value.title(), c)
        self.vf_invert_check = QCheckBox("Invert axis")
        vff.addRow("Channel", self.vf_channel_spin)
        vff.addRow("Note(s)", self.vf_notes_edit)
        vff.addRow("Min Velocity", self.vf_min_spin)
        vff.addRow("Max Velocity", self.vf_max_spin)
        vff.addRow("Deadzone", self.vf_deadzone_spin)
        vff.addRow("Response Curve", self.vf_curve_combo)
        vff.addRow(self.vf_invert_check)
        self.settings_stack.addWidget(vfp)

        # Macro page
        mp = QWidget()
        ml = QVBoxLayout(mp)
        self.macro_list = QListWidget()
        ml.addWidget(self.macro_list)
        macro_btns = QHBoxLayout()
        add_step = QPushButton("+ Add Step")
        add_step.clicked.connect(self._add_macro_step)
        rm_step = QPushButton("Remove Step")
        rm_step.clicked.connect(self._remove_macro_step)
        macro_btns.addWidget(add_step)
        macro_btns.addWidget(rm_step)
        ml.addLayout(macro_btns)
        self.macro_step_form = QFormLayout()
        self.macro_action_combo = QComboBox()
        for a in MacroActionType:
            self.macro_action_combo.addItem(a.value.replace("_", " ").title(), a)
        self.macro_step_channel = self._spin(1, 16, 1)
        self.macro_step_note = self._spin(0, 127, 60)
        self.macro_step_velocity = self._spin(0, 127, 127)
        self.macro_step_cc = self._spin(0, 127, 1)
        self.macro_step_value = self._spin(0, 127, 127)
        self.macro_step_delay = self._spin(0, 5000, 100)
        self.macro_step_delay.setSuffix(" ms")
        self.macro_step_form.addRow("Action", self.macro_action_combo)
        self.macro_step_form.addRow("Channel", self.macro_step_channel)
        self.macro_step_form.addRow("Note", self.macro_step_note)
        self.macro_step_form.addRow("Velocity", self.macro_step_velocity)
        self.macro_step_form.addRow("CC", self.macro_step_cc)
        self.macro_step_form.addRow("Value", self.macro_step_value)
        self.macro_step_form.addRow("Delay After", self.macro_step_delay)
        ml.addLayout(self.macro_step_form)
        self.settings_stack.addWidget(mp)

        # System page
        sp = QWidget()
        sf = QFormLayout(sp)
        self.system_cmd_combo = QComboBox()
        for cmd in SystemCommand:
            self.system_cmd_combo.addItem(cmd.value.replace("_", " ").title(), cmd)
        self.system_page_spin = self._spin(1, 16, 1)
        sf.addRow("Command", self.system_cmd_combo)
        sf.addRow("Target Page", self.system_page_spin)
        self.settings_stack.addWidget(sp)

        tl.addWidget(self.settings_stack)
        cont_layout.addWidget(tg)
        cont_layout.addStretch()
        self.mode_stack.addWidget(cont)

        # Split panel
        split = QWidget()
        sl = QVBoxLayout(split)
        sdf = QFormLayout()
        self.split_deadzone_spin = self._spin(0, 50, 10)
        self.split_deadzone_spin.setSuffix("%")
        self.split_curve_combo = QComboBox()
        for c in ResponseCurve:
            self.split_curve_combo.addItem(c.value.title(), c)
        self.split_invert_output = QCheckBox("Invert output")
        sdf.addRow("Deadzone", self.split_deadzone_spin)
        sdf.addRow("Response Curve", self.split_curve_combo)
        sdf.addRow(self.split_invert_output)
        sl.addLayout(sdf)

        self.neg_group, self.neg_kind_combo, self.neg_channel_spin, self.neg_note_spin, self.neg_velocity_spin, self.neg_cc_spin, self.neg_min_spin, self.neg_max_spin, self.neg_mode_combo, self.neg_macro_label = self._split_side_group("Negative Side (−)")
        self.pos_group, self.pos_kind_combo, self.pos_channel_spin, self.pos_note_spin, self.pos_velocity_spin, self.pos_cc_spin, self.pos_min_spin, self.pos_max_spin, self.pos_mode_combo, self.pos_macro_label = self._split_side_group("Positive Side (+)")
        sl.addWidget(self.neg_group)
        sl.addWidget(self.pos_group)
        sl.addStretch()
        self.mode_stack.addWidget(split)

        editor_layout.addWidget(self.mode_stack)

        # Chained targets (advanced — below primary target settings)
        chain_group = QGroupBox("Chained Targets")
        chain_layout = QVBoxLayout(chain_group)
        self.chain_list = QListWidget()
        self.chain_list.setMaximumHeight(90)
        chain_layout.addWidget(self.chain_list)
        chain_btns = QHBoxLayout()
        add_chain = QPushButton("+ Add Target")
        add_chain.clicked.connect(self._add_chain_target)
        rm_chain = QPushButton("Remove")
        rm_chain.clicked.connect(self._remove_chain_target)
        chain_btns.addWidget(add_chain)
        chain_btns.addWidget(rm_chain)
        chain_layout.addLayout(chain_btns)
        chain_form = QFormLayout()
        self.chain_type_combo = QComboBox()
        for tt in CHAIN_TARGET_TYPES:
            label = "Vel Fader" if tt == TargetType.NOTE_VELOCITY_FADER else tt.value.replace("_", " ").title()
            self.chain_type_combo.addItem(label, tt)
        self.chain_channel_spin = self._spin(1, 16, 1)
        self.chain_notes_edit = QLineEdit("62")
        self.chain_velocity_spin = self._spin(0, 127, 127)
        self.chain_cc_spin = self._spin(0, 127, 1)
        self.chain_min_spin = self._spin(0, 127, 0)
        self.chain_max_spin = self._spin(0, 127, 127)
        chain_form.addRow("Type", self.chain_type_combo)
        chain_form.addRow("Channel", self.chain_channel_spin)
        chain_form.addRow("Note(s)", self.chain_notes_edit)
        chain_form.addRow("Velocity", self.chain_velocity_spin)
        chain_form.addRow("CC Number", self.chain_cc_spin)
        chain_form.addRow("Min Out", self.chain_min_spin)
        chain_form.addRow("Max Out", self.chain_max_spin)
        chain_layout.addLayout(chain_form)
        editor_layout.addWidget(chain_group)

        self.delete_btn = QPushButton("Delete Mapping")
        self.delete_btn.setObjectName("dangerButton")
        self.delete_btn.clicked.connect(self._on_delete_mapping)
        editor_layout.addWidget(self.delete_btn)

        scroll.setWidget(editor)
        self.stack.addWidget(scroll)

        layout.addWidget(self.stack, stretch=1)
        self._wire_signals()
        self._install_scroll_guards(editor)
        self.stack.setCurrentIndex(0)
        self.behavior_widget.setVisible(False)
        self._update_split_visibility()
        self._apply_lock_state()

    def set_accent_color(self, color: str) -> None:
        self._accent_color = color
        self._apply_target_radio_styles()
        self.setStyleSheet(
            "QGroupBox { color: #FFFFFF; font-weight: 700; border: 1px solid #444; "
            f"border-top-color: {color}; margin-top: 8px; padding-top: 6px; }}"
            "QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; color: #FFFFFF; }"
            "QFormLayout QLabel, QLabel { color: #E4E8F0; }"
            f"QLabel#sectionTitle {{ color: {color}; }}"
        )
        for title in self.findChildren(QLabel):
            if title.objectName() == "sectionTitle":
                title.setStyleSheet(
                    f"color: {color}; font-size: 13px; font-weight: 700; letter-spacing: 0.12em;"
                )

    def _apply_target_radio_styles(self) -> None:
        accent = self._accent_color
        for radio, color in self._target_radios:
            radio.setStyleSheet(
                f"""
                QRadioButton {{
                    color: {color};
                    font-weight: 700;
                    padding: 6px 12px;
                    border: 2px solid {color};
                    border-radius: 5px;
                    background-color: #1a1a1a;
                    spacing: 6px;
                }}
                QRadioButton:hover {{
                    background-color: #252525;
                }}
                QRadioButton:checked {{
                    color: #101010;
                    background-color: {color};
                    border: 3px solid {accent};
                    font-weight: 800;
                }}
                QRadioButton::indicator {{
                    width: 0px;
                    height: 0px;
                    border: none;
                }}
                """
            )

    def _on_lock_toggled(self, locked: bool) -> None:
        self._locked = locked
        self.lock_btn.setText("Locked" if locked else "Editing")
        self._apply_lock_state()

    def _apply_lock_state(self) -> None:
        can_edit = not self._locked
        self.stack.setEnabled(can_edit)
        if not can_edit:
            self.add_btn.setEnabled(False)
            return
        has_selection = self._selected is not None
        has_mapping = self._editing_mapping is not None
        self.add_btn.setEnabled(has_selection and not has_mapping)
        self.delete_btn.setEnabled(has_mapping)

    def _split_side_group(self, title: str):
        group = QGroupBox(title)
        form = QFormLayout(group)
        kind = QComboBox()
        kind.addItem("Note", SplitTargetKind.NOTE)
        kind.addItem("CC", SplitTargetKind.CC)
        kind.addItem("Vel Fader", SplitTargetKind.NOTE_VELOCITY_FADER)
        kind.addItem("Macro", SplitTargetKind.MACRO)
        kind.currentIndexChanged.connect(self._update_split_visibility)
        channel = self._spin(1, 16, 1)
        note = self._spin(0, 127, 60)
        velocity = self._spin(0, 127, 127)
        cc = self._spin(0, 127, 1)
        cc_min = self._spin(0, 127, 0)
        cc_max = self._spin(0, 127, 127)
        mode = QComboBox()
        mode.addItem("Momentary", DigitalMode.MOMENTARY)
        mode.addItem("Toggle", DigitalMode.TOGGLE)
        macro_label = QLabel("Runs the main Macro steps when this side activates.")
        macro_label.setWordWrap(True)
        macro_label.setStyleSheet("color: #8b93a7; font-size: 10px;")
        form.addRow("Target Type", kind)
        form.addRow("Channel", channel)
        form.addRow("Note", note)
        form.addRow("Velocity", velocity)
        form.addRow("CC Number", cc)
        form.addRow("Min Out", cc_min)
        form.addRow("Max Out", cc_max)
        form.addRow("Note Mode", mode)
        form.addRow(macro_label)
        return group, kind, channel, note, velocity, cc, cc_min, cc_max, mode, macro_label

    def set_edit_context(self, device_slot: str, page_id: int) -> None:
        self._device_slot = device_slot
        self._page_id = page_id
        pages = self._engine.pages
        page_name = pages[page_id] if page_id < len(pages) else f"Page {page_id + 1}"
        self.context_label.setText(f"Device: {device_slot}  ·  Layer: {page_name}")

    def refresh_from_engine(self) -> None:
        if self._selected is not None:
            self.select_source(self._selected)

    def mapped_sources(self) -> set[InputSource]:
        return {
            m.source
            for m in self._engine.mappings
            if m.page_id == self._page_id and m.device_slot in (self._device_slot, DEFAULT_DEVICE_SLOT)
        }

    def select_source(self, source: Optional[InputSource]) -> None:
        self._selected = source
        if source is None:
            self.source_title.setText("Click a control on the visualizer")
            self.stack.setCurrentIndex(0)
            self._editing_mapping = None
            self._apply_lock_state()
            return

        self.source_title.setText(source_label(source))
        mapping = self._engine.mapping_for_source(source, self._device_slot, self._page_id)
        self._editing_mapping = mapping
        show_analog = is_analog_source(source)
        self.behavior_widget.setVisible(show_analog)
        self._update_analog_target_options()

        if mapping is None:
            self.stack.setCurrentIndex(0)
            self.empty_label.setText(f"No mapping for {source_label(source)} on this page.")
            self.add_btn.setText(f"Add Mapping to {source_label(source)}")
        else:
            self._load_form(mapping)
            self.stack.setCurrentIndex(1)
        self._apply_lock_state()

    def _wire_signals(self) -> None:
        widgets = [
            self.behavior_combo, self.note_radio, self.cc_radio, self.pitch_radio,
            self.velocity_fader_radio, self.macro_radio, self.system_radio, self.channel_spin, self.notes_edit,
            self.velocity_spin, self.mode_combo, self.threshold_check, self.threshold_spin,
            self.double_tap_spin, self.long_press_spin,
            self.cc_channel_spin, self.cc_number_spin, self.cc_min_spin, self.cc_max_spin,
            self.cc_deadzone_spin, self.cc_invert_check, self.invert_output_check,
            self.curve_combo, self.cc_offset_spin, self.pitch_channel_spin, self.pitch_min_spin,
            self.pitch_max_spin, self.pitch_deadzone_spin, self.pitch_invert_check,
            self.pitch_invert_output_check, self.pitch_curve_combo,
            self.vf_channel_spin, self.vf_notes_edit, self.vf_min_spin, self.vf_max_spin,
            self.vf_deadzone_spin, self.vf_curve_combo, self.vf_invert_check,
            self.system_cmd_combo, self.system_page_spin, self.split_deadzone_spin, self.split_curve_combo,
            self.split_invert_output, self.neg_kind_combo, self.neg_channel_spin,
            self.neg_note_spin, self.neg_velocity_spin, self.neg_cc_spin, self.neg_min_spin,
            self.neg_max_spin, self.neg_mode_combo, self.pos_kind_combo, self.pos_channel_spin,
            self.pos_note_spin, self.pos_velocity_spin, self.pos_cc_spin, self.pos_min_spin,
            self.pos_max_spin, self.pos_mode_combo,
            self.fade_in_spin, self.fade_out_spin, self.continuous_hold_check,
        ]
        for w in widgets:
            if isinstance(w, QLineEdit):
                w.textChanged.connect(self._apply_current)
            elif isinstance(w, QComboBox):
                w.currentIndexChanged.connect(self._apply_current)
            elif isinstance(w, QRadioButton):
                w.toggled.connect(self._on_type_toggled)
            elif isinstance(w, QCheckBox):
                w.toggled.connect(self._apply_current)
            elif isinstance(w, QDoubleSpinBox):
                w.valueChanged.connect(self._apply_current)
            else:
                w.valueChanged.connect(self._apply_current)  # type: ignore[attr-defined]

    @staticmethod
    def _spin(lo: int, hi: int, val: int) -> QSpinBox:
        s = QSpinBox()
        s.setRange(lo, hi)
        s.setValue(val)
        return s

    def _install_scroll_guards(self, root: QWidget) -> None:
        from kolbe.gui.scroll_guard import ScrollFocusGuard

        guard = ScrollFocusGuard(root)
        for widget in root.findChildren(QComboBox):
            widget.installEventFilter(guard)
        for widget in root.findChildren(QSpinBox):
            widget.installEventFilter(guard)
        for widget in root.findChildren(QDoubleSpinBox):
            widget.installEventFilter(guard)

    def _on_type_toggled(self, _checked: bool) -> None:
        self._update_panels()
        self._apply_current()

    def _on_behavior_changed(self) -> None:
        if self._block_apply:
            return
        mode = self.behavior_combo.currentData()
        self.mode_stack.setCurrentIndex(1 if mode == AnalogBehaviorMode.SPLIT else 0)
        self._update_analog_target_options()
        self._apply_current()

    def _update_analog_target_options(self) -> None:
        analog = self._selected is not None and is_analog_source(self._selected)
        split = analog and self.behavior_combo.currentData() == AnalogBehaviorMode.SPLIT
        restrict_continuous = analog and not split

        self.note_radio.setVisible(not restrict_continuous)
        self.macro_radio.setVisible(not restrict_continuous)
        self.system_radio.setVisible(not restrict_continuous)
        self.cc_radio.setVisible(True)
        self.pitch_radio.setVisible(True)
        self.velocity_fader_radio.setVisible(True)

        if restrict_continuous and not any(
            r.isChecked() for r in (self.cc_radio, self.pitch_radio, self.velocity_fader_radio)
        ):
            self.cc_radio.setChecked(True)
            self._update_panels()

    def _update_panels(self) -> None:
        if self.macro_radio.isChecked():
            self.settings_stack.setCurrentIndex(4)
        elif self.system_radio.isChecked():
            self.settings_stack.setCurrentIndex(5)
        elif self.note_radio.isChecked():
            self.settings_stack.setCurrentIndex(0)
        elif self.cc_radio.isChecked():
            self.settings_stack.setCurrentIndex(1)
        elif self.velocity_fader_radio.isChecked():
            self.settings_stack.setCurrentIndex(3)
        else:
            self.settings_stack.setCurrentIndex(2)

    def _update_split_visibility(self) -> None:
        for kind, channel, note, vel, cc, cmin, cmax, mode, macro_label in (
            (self.neg_kind_combo, self.neg_channel_spin, self.neg_note_spin, self.neg_velocity_spin,
             self.neg_cc_spin, self.neg_min_spin, self.neg_max_spin, self.neg_mode_combo, self.neg_macro_label),
            (self.pos_kind_combo, self.pos_channel_spin, self.pos_note_spin, self.pos_velocity_spin,
             self.pos_cc_spin, self.pos_min_spin, self.pos_max_spin, self.pos_mode_combo, self.pos_macro_label),
        ):
            target = kind.currentData()
            is_note = target == SplitTargetKind.NOTE
            is_cc = target == SplitTargetKind.CC
            is_vf = target == SplitTargetKind.NOTE_VELOCITY_FADER
            is_macro = target == SplitTargetKind.MACRO
            channel.setVisible(not is_macro)
            note.setVisible(is_note or is_vf)
            vel.setVisible(is_note)
            mode.setVisible(is_note)
            cc.setVisible(is_cc)
            cmin.setVisible(is_cc or is_vf)
            cmax.setVisible(is_cc or is_vf)
            macro_label.setVisible(is_macro)

    def _load_form(self, m: Mapping) -> None:
        self._block_apply = True
        idx = self.behavior_combo.findData(m.analog_behavior)
        if idx >= 0:
            self.behavior_combo.setCurrentIndex(idx)
        self.mode_stack.setCurrentIndex(1 if m.is_split_behavior else 0)

        if m.is_split_behavior:
            self.split_deadzone_spin.setValue(int(m.deadzone * 100))
            self._set(self.split_curve_combo, m.response_curve)
            self.split_invert_output.setChecked(m.invert_output)
            self._load_split_side(m, "neg")
            self._load_split_side(m, "pos")
            self._update_split_visibility()
        elif m.target_type == TargetType.MACRO:
            self.macro_radio.setChecked(True)
            self._load_macro_list(m.macro_steps)
        elif m.target_type == TargetType.SYSTEM:
            self.system_radio.setChecked(True)
            self._set(self.system_cmd_combo, m.system_command)
            self.system_page_spin.setValue(m.system_page_target + 1)
        elif m.target_type == TargetType.NOTE:
            self.note_radio.setChecked(True)
            self.channel_spin.setValue(m.channel + 1)
            self.notes_edit.setText(",".join(str(n) for n in m.notes))
            self.velocity_spin.setValue(m.velocity)
            self._set(self.mode_combo, m.digital_mode)
            self.double_tap_spin.setValue(m.double_tap_ms)
            self.long_press_spin.setValue(m.long_press_ms)
            self.threshold_check.setChecked(m.use_threshold)
            self.threshold_spin.setValue(int(m.threshold * 100))
        elif m.target_type == TargetType.NOTE_VELOCITY_FADER:
            self.velocity_fader_radio.setChecked(True)
            self.vf_channel_spin.setValue(m.channel + 1)
            self.vf_notes_edit.setText(",".join(str(n) for n in m.notes))
            self.vf_min_spin.setValue(m.min_value)
            self.vf_max_spin.setValue(m.max_value)
            self.vf_deadzone_spin.setValue(int(m.deadzone * 100))
            self._set(self.vf_curve_combo, m.response_curve)
            self.vf_invert_check.setChecked(m.invert)
        elif m.target_type == TargetType.CC:
            self.cc_radio.setChecked(True)
            self.cc_channel_spin.setValue(m.channel + 1)
            self.cc_number_spin.setValue(m.cc_number)
            self.cc_min_spin.setValue(m.min_value)
            self.cc_max_spin.setValue(m.max_value)
            self.cc_deadzone_spin.setValue(int(m.deadzone * 100))
            self._set(self.curve_combo, m.response_curve)
            self.invert_output_check.setChecked(m.invert_output)
            self.cc_invert_check.setChecked(m.invert)
            self.cc_offset_spin.setValue(int(m.offset * 100))
        else:
            self.pitch_radio.setChecked(True)
            self.pitch_channel_spin.setValue(m.channel + 1)
            self.pitch_min_spin.setValue(m.min_value)
            self.pitch_max_spin.setValue(m.max_value)
            self.pitch_deadzone_spin.setValue(int(m.deadzone * 100))
            self._set(self.pitch_curve_combo, m.response_curve)
            self.pitch_invert_output_check.setChecked(m.invert_output)
            self.pitch_invert_check.setChecked(m.invert)

        self._load_chain_list(m.extra_targets)
        self.fade_in_spin.setValue(m.fade_in_sec)
        self.fade_out_spin.setValue(m.fade_out_sec)
        self.continuous_hold_check.setChecked(m.continuous_hold_enabled)
        self._update_analog_target_options()
        self._update_panels()
        self._block_apply = False

    def _load_chain_list(self, targets: list[MidiTarget]) -> None:
        self.chain_list.clear()
        for i, target in enumerate(targets):
            self.chain_list.addItem(QListWidgetItem(self._chain_target_label(target, i)))

    def _load_split_side(self, m: Mapping, side: str) -> None:
        if side == "neg":
            combos = (self.neg_kind_combo, self.neg_channel_spin, self.neg_note_spin, self.neg_velocity_spin,
                      self.neg_cc_spin, self.neg_min_spin, self.neg_max_spin, self.neg_mode_combo)
            vals = (m.neg_split_kind, m.neg_split_channel, m.neg_split_note, m.neg_split_velocity,
                    m.neg_split_cc, m.neg_split_min, m.neg_split_max, m.neg_split_digital_mode)
        else:
            combos = (self.pos_kind_combo, self.pos_channel_spin, self.pos_note_spin, self.pos_velocity_spin,
                      self.pos_cc_spin, self.pos_min_spin, self.pos_max_spin, self.pos_mode_combo)
            vals = (m.pos_split_kind, m.pos_split_channel, m.pos_split_note, m.pos_split_velocity,
                    m.pos_split_cc, m.pos_split_min, m.pos_split_max, m.pos_split_digital_mode)
        self._set(combos[0], vals[0])
        combos[1].setValue(vals[1] + 1)
        combos[2].setValue(vals[2])
        combos[3].setValue(vals[3])
        combos[4].setValue(vals[4])
        combos[5].setValue(vals[5])
        combos[6].setValue(vals[6])
        self._set(combos[7], vals[7])

    def _load_macro_list(self, steps: list[MacroStep]) -> None:
        self.macro_list.clear()
        for i, step in enumerate(steps):
            self.macro_list.addItem(QListWidgetItem(self._macro_step_label(step, i)))

    @staticmethod
    def _macro_step_label(step: MacroStep, index: int) -> str:
        if step.action == MacroActionType.DELAY:
            return f"{index + 1}. Wait {step.delay_ms}ms"
        return f"{index + 1}. {step.action.value} ch={step.channel + 1}"

    @staticmethod
    def _set(combo: QComboBox, value: object) -> None:
        i = combo.findData(value)
        if i >= 0:
            combo.setCurrentIndex(i)

    def _on_add_mapping(self) -> None:
        if self._locked or self._selected is None:
            return
        source = self._selected
        if is_digital_source(source):
            mapping = Mapping(source=source, target_type=TargetType.NOTE,
                              device_slot=self._device_slot, page_id=self._page_id)
        else:
            mapping = Mapping(source=source, target_type=TargetType.CC, deadzone=0.1,
                              device_slot=self._device_slot, page_id=self._page_id)
        self._engine.add_mapping(mapping)
        self._editing_mapping = mapping
        self._load_form(mapping)
        self.stack.setCurrentIndex(1)
        self._apply_lock_state()
        self.mappings_changed.emit(self._engine.mappings)

    def _on_delete_mapping(self) -> None:
        if self._locked or self._editing_mapping is None:
            return
        self._engine.remove_mapping(self._editing_mapping.id)
        self._editing_mapping = None
        self.select_source(self._selected)
        self.mappings_changed.emit(self._engine.mappings)

    def _add_macro_step(self) -> None:
        if self._editing_mapping is None:
            return
        step = MacroStep(
            action=self.macro_action_combo.currentData(),
            channel=self.macro_step_channel.value() - 1,
            note=self.macro_step_note.value(),
            velocity=self.macro_step_velocity.value(),
            cc_number=self.macro_step_cc.value(),
            value=self.macro_step_value.value(),
            delay_ms=self.macro_step_delay.value(),
        )
        self._editing_mapping.macro_steps.append(step)
        self._load_macro_list(self._editing_mapping.macro_steps)
        self._apply_current()

    def _remove_macro_step(self) -> None:
        if self._editing_mapping is None:
            return
        row = self.macro_list.currentRow()
        if 0 <= row < len(self._editing_mapping.macro_steps):
            del self._editing_mapping.macro_steps[row]
            self._load_macro_list(self._editing_mapping.macro_steps)
            self._apply_current()

    def _add_chain_target(self) -> None:
        if self._editing_mapping is None:
            return
        notes = self._parse_notes(self.chain_notes_edit.text()) or [60]
        target = MidiTarget(
            target_type=self.chain_type_combo.currentData(),
            channel=self.chain_channel_spin.value() - 1,
            notes=notes,
            velocity=self.chain_velocity_spin.value(),
            cc_number=self.chain_cc_spin.value(),
            min_value=self.chain_min_spin.value(),
            max_value=self.chain_max_spin.value(),
        )
        self._editing_mapping.extra_targets.append(target)
        self._load_chain_list(self._editing_mapping.extra_targets)
        self._apply_current()

    def _remove_chain_target(self) -> None:
        if self._editing_mapping is None:
            return
        row = self.chain_list.currentRow()
        if 0 <= row < len(self._editing_mapping.extra_targets):
            del self._editing_mapping.extra_targets[row]
            self._load_chain_list(self._editing_mapping.extra_targets)
            self._apply_current()

    @staticmethod
    def _chain_target_label(target: MidiTarget, index: int) -> str:
        tt = target.target_type.value.replace("_", " ")
        if target.target_type == TargetType.CC:
            return f"{index + 1}. CC {target.cc_number} ch={target.channel + 1}"
        notes = ",".join(str(n) for n in target.notes)
        return f"{index + 1}. {tt} note={notes} ch={target.channel + 1}"

    def _apply_current(self) -> None:
        if self._locked or self._block_apply or self._editing_mapping is None or self._selected is None:
            return
        mapping = self._build_mapping()
        if mapping is None:
            return
        self._engine.update_mapping(mapping)
        self._editing_mapping = mapping
        self.mappings_changed.emit(self._engine.mappings)

    def _build_mapping(self) -> Optional[Mapping]:
        if self._selected is None or self._editing_mapping is None:
            return None
        base = Mapping(source=self._selected, target_type=self._editing_mapping.target_type)
        base.id = self._editing_mapping.id
        base.device_slot = self._device_slot
        base.page_id = self._page_id
        base.macro_steps = list(self._editing_mapping.macro_steps)
        base.extra_targets = list(self._editing_mapping.extra_targets)
        base.neg_split_macro_steps = list(self._editing_mapping.neg_split_macro_steps)
        base.pos_split_macro_steps = list(self._editing_mapping.pos_split_macro_steps)
        base.long_press_ms = self.long_press_spin.value()
        base.double_tap_ms = self.double_tap_spin.value()
        base.fade_in_sec = self.fade_in_spin.value()
        base.fade_out_sec = self.fade_out_spin.value()
        base.continuous_hold_enabled = self.continuous_hold_check.isChecked()

        if is_analog_source(self._selected):
            behavior = self.behavior_combo.currentData()
            if behavior == AnalogBehaviorMode.SPLIT:
                base.analog_behavior = AnalogBehaviorMode.SPLIT
                base.deadzone = self.split_deadzone_spin.value() / 100.0
                base.response_curve = self.split_curve_combo.currentData()
                base.invert_output = self.split_invert_output.isChecked()
                self._save_split_side(base, "neg")
                self._save_split_side(base, "pos")
                both_cc = base.neg_split_kind == SplitTargetKind.CC and base.pos_split_kind == SplitTargetKind.CC
                base.target_type = TargetType.SPLIT_CC if both_cc else TargetType.SPLIT_NOTE
                return base

        base.analog_behavior = AnalogBehaviorMode.CONTINUOUS
        if self.macro_radio.isChecked():
            base.target_type = TargetType.MACRO
        elif self.system_radio.isChecked():
            base.target_type = TargetType.SYSTEM
            base.system_command = self.system_cmd_combo.currentData()
            base.system_page_target = self.system_page_spin.value() - 1
        elif self.note_radio.isChecked():
            notes = self._parse_notes(self.notes_edit.text())
            if not notes:
                return None
            base.target_type = TargetType.NOTE
            base.channel = self.channel_spin.value() - 1
            base.notes = notes
            base.velocity = self.velocity_spin.value()
            base.digital_mode = self.mode_combo.currentData()
            base.use_threshold = self.threshold_check.isChecked()
            base.threshold = self.threshold_spin.value() / 100.0
        elif self.velocity_fader_radio.isChecked():
            notes = self._parse_notes(self.vf_notes_edit.text())
            if not notes:
                return None
            base.target_type = TargetType.NOTE_VELOCITY_FADER
            base.channel = self.vf_channel_spin.value() - 1
            base.notes = notes
            base.min_value = self.vf_min_spin.value()
            base.max_value = self.vf_max_spin.value()
            base.deadzone = self.vf_deadzone_spin.value() / 100.0
            base.response_curve = self.vf_curve_combo.currentData()
            base.invert = self.vf_invert_check.isChecked()
        elif self.cc_radio.isChecked():
            base.target_type = TargetType.CC
            base.channel = self.cc_channel_spin.value() - 1
            base.cc_number = self.cc_number_spin.value()
            base.min_value = self.cc_min_spin.value()
            base.max_value = self.cc_max_spin.value()
            base.deadzone = self.cc_deadzone_spin.value() / 100.0
            base.response_curve = self.curve_combo.currentData()
            base.invert_output = self.invert_output_check.isChecked()
            base.invert = self.cc_invert_check.isChecked()
            base.offset = self.cc_offset_spin.value() / 100.0
        else:
            base.target_type = TargetType.PITCH_BEND
            base.channel = self.pitch_channel_spin.value() - 1
            base.min_value = self.pitch_min_spin.value()
            base.max_value = self.pitch_max_spin.value()
            base.deadzone = self.pitch_deadzone_spin.value() / 100.0
            base.response_curve = self.pitch_curve_combo.currentData()
            base.invert_output = self.pitch_invert_output_check.isChecked()
            base.invert = self.pitch_invert_check.isChecked()
        return base

    def _save_split_side(self, base: Mapping, side: str) -> None:
        if side == "neg":
            combos = (self.neg_kind_combo, self.neg_channel_spin, self.neg_note_spin, self.neg_velocity_spin,
                      self.neg_cc_spin, self.neg_min_spin, self.neg_max_spin, self.neg_mode_combo)
            attrs = ("neg_split_kind", "neg_split_channel", "neg_split_note", "neg_split_velocity",
                     "neg_split_cc", "neg_split_min", "neg_split_max", "neg_split_digital_mode")
        else:
            combos = (self.pos_kind_combo, self.pos_channel_spin, self.pos_note_spin, self.pos_velocity_spin,
                      self.pos_cc_spin, self.pos_min_spin, self.pos_max_spin, self.pos_mode_combo)
            attrs = ("pos_split_kind", "pos_split_channel", "pos_split_note", "pos_split_velocity",
                     "pos_split_cc", "pos_split_min", "pos_split_max", "pos_split_digital_mode")
        setattr(base, attrs[0], combos[0].currentData())
        setattr(base, attrs[1], combos[1].value() - 1)
        setattr(base, attrs[2], combos[2].value())
        setattr(base, attrs[3], combos[3].value())
        setattr(base, attrs[4], combos[4].value())
        setattr(base, attrs[5], combos[5].value())
        setattr(base, attrs[6], combos[6].value())
        setattr(base, attrs[7], combos[7].currentData())

    @staticmethod
    def _parse_notes(text: str) -> list[int]:
        notes: list[int] = []
        for part in text.replace(" ", "").split(","):
            if not part:
                continue
            if part.isdigit():
                notes.append(max(0, min(127, int(part))))
            else:
                from kolbe.mapping.models import name_to_note
                parsed = name_to_note(part)
                if parsed is not None:
                    notes.append(parsed)
        return notes
