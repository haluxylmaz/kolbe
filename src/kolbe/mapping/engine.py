"""Core mapping engine — converts ControllerState to MIDI messages."""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Callable, Literal, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from kolbe.controller.types import ControllerState, InputSource
from kolbe.mapping.digital_repeat_runner import DigitalRepeatRunner
from kolbe.mapping.macro_runner import MacroRunner
from kolbe.mapping.output_timing import OutputTimingManager
from kolbe.mapping.models import (
    AnalogBehaviorMode,
    DEFAULT_DEVICE_SLOT,
    DigitalMode,
    MacroActionType,
    MacroStep,
    Mapping,
    MidiTarget,
    PresetData,
    ResponseCurve,
    SplitTargetKind,
    SystemCommand,
    TargetType,
    is_analog_source,
    is_digital_source,
    is_stick_source,
    note_to_name,
)
from kolbe.mapping.transforms import (
    apply_deadzone,
    apply_response_curve,
    normalize_analog_raw,
    scale_split_side,
    transform_to_midi,
    transform_to_pitch_bend,
)
from kolbe.midi.virtual_port import VirtualMidiPort

logger = logging.getLogger(__name__)

MonitorKind = Literal["note_on", "note_off", "cc", "pitch", "system"]
SplitSide = Literal["neg", "pos", ""]


class MappingEngine(QObject):
    """Processes controller state against mappings and emits MIDI on change."""

    monitor_line = pyqtSignal(str, str)
    page_changed = pyqtSignal(str, int)  # device_id, page_id

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._preset = PresetData(name="Untitled")
        self._midi_port: Optional[VirtualMidiPort] = None
        self._prev_digital: dict[str, bool] = {}
        self._axis_hold_prev: dict[str, bool] = {}
        self._split_zone_hold_prev: dict[str, bool] = {}
        self._toggle_on: dict[str, bool] = {}
        self._threshold_on: dict[str, bool] = {}
        self._last_cc: dict[str, int] = {}
        self._last_pitch: dict[str, int] = {}
        self._split_active: dict[str, SplitSide] = {}
        self._split_note_on: dict[str, bool] = {}
        self._split_velocity_on: dict[str, bool] = {}
        self._split_last_velocity: dict[str, int] = {}
        self._velocity_fader_on: dict[str, bool] = {}
        self._last_velocity: dict[str, int] = {}
        self._press_start: dict[str, float] = {}
        self._long_press_fired: dict[str, bool] = {}
        self._last_release_time: dict[str, float] = {}
        self._pending_tap: dict[str, bool] = {}
        self._activity: dict[str, str] = {}
        self._analog_active: dict[str, bool] = {}
        self._macro_runner = MacroRunner(self._execute_macro_step, self)
        self._continuous_hold = DigitalRepeatRunner(self._continuous_hold_fire, self)
        self._timing = OutputTimingManager(
            send_cc=self._timing_send_cc,
            send_pitch=self._timing_send_pitch,
            send_note_velocity=self._timing_send_note_velocity,
            send_note_off=self._timing_send_note_off,
            send_velocity_fader=self._timing_send_velocity_fader,
            parent=self,
        )

    @property
    def mappings(self) -> list[Mapping]:
        return list(self._preset.mappings)

    @property
    def pages(self) -> list[str]:
        return list(self._preset.pages)

    @property
    def preset(self) -> PresetData:
        return self._preset

    def set_midi_port(self, port: Optional[VirtualMidiPort]) -> None:
        self._midi_port = port
        self.reset_state()

    def load_preset(self, preset: PresetData) -> None:
        self.clear_all_states()
        self._preset = preset

    def set_mappings(self, mappings: list[Mapping]) -> None:
        self.clear_all_states()
        self._preset.mappings = list(mappings)

    def add_mapping(self, mapping: Mapping) -> None:
        self._preset.mappings.append(mapping)

    def update_mapping(self, mapping: Mapping) -> None:
        for i, existing in enumerate(self._preset.mappings):
            if existing.id == mapping.id:
                self._preset.mappings[i] = mapping
                self._clear_mapping_state(mapping.id)
                return
        self._preset.mappings.append(mapping)

    def remove_mapping(self, mapping_id: str) -> None:
        mapping = next((m for m in self._preset.mappings if m.id == mapping_id), None)
        if mapping:
            self._release_mapping(mapping)
        self._preset.mappings = [m for m in self._preset.mappings if m.id != mapping_id]
        self._clear_mapping_state(mapping_id)

    def mapping_for_source(
        self,
        source: InputSource,
        device_slot: str,
        page_id: int,
    ) -> Optional[Mapping]:
        exact = None
        wildcard = None
        for mapping in self._preset.mappings:
            if mapping.source != source or mapping.page_id != page_id:
                continue
            if mapping.device_slot == device_slot:
                exact = mapping
            elif mapping.device_slot == DEFAULT_DEVICE_SLOT:
                wildcard = mapping
        return exact or wildcard

    def active_page(self, device_id: str) -> int:
        return self._preset.active_page_for(device_id)

    def set_active_page(self, device_id: str, page_id: int) -> None:
        old = self.active_page(device_id)
        page_id = max(0, min(page_id, len(self._preset.pages) - 1))
        if page_id == old:
            return
        self.clear_all_states()
        self._preset.set_active_page_for(device_id, page_id)
        page_name = self._preset.pages[page_id]
        self.log_system(f"Page changed: {page_name} (device {device_id})")
        self.page_changed.emit(device_id, page_id)

    def next_page(self, device_id: str) -> None:
        current = self.active_page(device_id)
        self.set_active_page(device_id, (current + 1) % len(self._preset.pages))

    def previous_page(self, device_id: str) -> None:
        current = self.active_page(device_id)
        self.set_active_page(device_id, (current - 1) % len(self._preset.pages))

    def clear_all_states(self) -> None:
        """Stop all runners, release MIDI output, and reset input tracking."""
        self._continuous_hold.block_fires(True)
        try:
            self._macro_runner.stop()
            self._continuous_hold.stop_all()
            self._timing.stop_all()
            self._release_all_notes()
            self._send_midi_reset()
            self._reset_tracking_state()
        finally:
            self._continuous_hold.block_fires(False)

    def reset_state(self) -> None:
        self._macro_runner.stop()
        self._continuous_hold.stop_all()
        self._timing.stop_all()
        self._reset_tracking_state()

    def _reset_tracking_state(self) -> None:
        self._prev_digital.clear()
        self._axis_hold_prev.clear()
        self._split_zone_hold_prev.clear()
        self._toggle_on.clear()
        self._threshold_on.clear()
        self._last_cc.clear()
        self._last_pitch.clear()
        self._split_active.clear()
        self._split_note_on.clear()
        self._split_velocity_on.clear()
        self._split_last_velocity.clear()
        self._velocity_fader_on.clear()
        self._last_velocity.clear()
        self._press_start.clear()
        self._long_press_fired.clear()
        self._last_release_time.clear()
        self._pending_tap.clear()
        self._activity.clear()
        self._analog_active.clear()

    def shutdown(self) -> None:
        self.clear_all_states()
        self._midi_port = None

    def log_system(self, message: str) -> None:
        self._emit_monitor(message, "system")

    def get_activity(self, mapping_id: str) -> str:
        return self._activity.get(mapping_id, "")

    def process_state(self, state: ControllerState) -> None:
        device_id = state.device.id
        page_id = self.active_page(device_id)
        for mapping in self._active_mappings(device_id, page_id):
            if is_digital_source(mapping.source):
                self._process_digital(mapping, state, device_id)
            elif is_analog_source(mapping.source):
                self._process_analog(mapping, state)

    def _active_mappings(self, device_id: str, page_id: int) -> list[Mapping]:
        by_source: dict[InputSource, Mapping] = {}
        for mapping in self._preset.mappings:
            if mapping.page_id != page_id:
                continue
            if mapping.device_slot == DEFAULT_DEVICE_SLOT:
                by_source.setdefault(mapping.source, mapping)
            elif mapping.device_slot == device_id:
                by_source[mapping.source] = mapping
        return list(by_source.values())

    def _process_digital(self, mapping: Mapping, state: ControllerState, device_id: str) -> None:
        key = mapping.source.value
        pressed = bool(state.buttons.get(key, False))
        prev = self._prev_digital.get(mapping.id, False)
        now = time.monotonic()

        if mapping.digital_mode == DigitalMode.LONG_PRESS:
            if pressed and not prev:
                self._press_start[mapping.id] = now
                self._long_press_fired[mapping.id] = False
            elif pressed and not self._long_press_fired.get(mapping.id, False):
                elapsed_ms = (now - self._press_start.get(mapping.id, now)) * 1000
                if elapsed_ms >= mapping.long_press_ms:
                    self._long_press_fired[mapping.id] = True
                    self._fire_digital_action(mapping, device_id)
                    self._activity[mapping.id] = "HOLD"
            elif not pressed and prev:
                self._press_start.pop(mapping.id, None)
                self._long_press_fired.pop(mapping.id, None)
                if self._activity.get(mapping.id) == "HOLD":
                    self._activity[mapping.id] = ""
            self._prev_digital[mapping.id] = pressed
            return

        if mapping.digital_mode == DigitalMode.DOUBLE_TAP:
            if pressed and not prev:
                self._press_start[mapping.id] = now
            elif not pressed and prev:
                last_release = self._last_release_time.get(mapping.id, 0.0)
                gap_ms = (now - last_release) * 1000 if last_release else mapping.double_tap_ms + 1
                if gap_ms <= mapping.double_tap_ms and self._pending_tap.get(mapping.id, False):
                    self._pending_tap[mapping.id] = False
                    self._fire_digital_action(mapping, device_id)
                    self._activity[mapping.id] = "2×"
                else:
                    self._pending_tap[mapping.id] = True
                self._last_release_time[mapping.id] = now
            self._prev_digital[mapping.id] = pressed
            return

        if mapping.target_type == TargetType.MACRO:
            if pressed and not prev:
                self._start_macro(mapping)
        elif mapping.target_type == TargetType.SYSTEM:
            if pressed and not prev:
                self._execute_system_command(mapping, device_id)
        elif mapping.target_type == TargetType.NOTE:
            self._process_digital_note(mapping, pressed, prev)
        elif mapping.target_type == TargetType.NOTE_VELOCITY_FADER:
            self._process_digital_velocity_fader(mapping, pressed, prev)

        self._prev_digital[mapping.id] = pressed

    def _fire_digital_action(self, mapping: Mapping, device_id: str) -> None:
        if mapping.target_type == TargetType.MACRO:
            self._start_macro(mapping)
        elif mapping.target_type == TargetType.SYSTEM:
            self._execute_system_command(mapping, device_id)
        elif mapping.target_type == TargetType.NOTE:
            self._send_note_on(mapping.channel, mapping.notes, mapping.velocity)
            self._fire_extra_targets_press(mapping)

    def _digital_vel_fader_value(self, mapping: Mapping) -> int:
        return max(mapping.min_value, mapping.max_value)

    def _continuous_hold_fire(self, mapping: Mapping, zone: str = "") -> None:
        if zone in ("neg", "pos"):
            self._fire_split_zone_pulse(mapping, zone)
            return

        current = self._timing.get_output_value(mapping.id)
        if mapping.target_type == TargetType.NOTE_VELOCITY_FADER:
            value = current if current >= 0 else self._digital_vel_fader_value(mapping)
            self._send_velocity_fader_value(mapping, value)
        elif mapping.target_type == TargetType.NOTE:
            velocity = current if current >= 0 else mapping.velocity
            self._send_note_on(mapping.channel, mapping.notes, velocity)

    def _fire_split_zone_pulse(self, mapping: Mapping, side: SplitSide) -> None:
        kind, channel, note, velocity, cc_number, cc_min, cc_max, _mode = self._split_side_config(
            mapping, side
        )
        if kind == SplitTargetKind.NOTE:
            self._send_note_on(channel, [note], velocity)
        elif kind == SplitTargetKind.NOTE_VELOCITY_FADER:
            value = max(cc_min, cc_max)
            vel_key = f"{mapping.id}:{side}"
            self._split_last_velocity[vel_key] = value
            self._split_velocity_on[vel_key] = True
            if self._midi_port:
                try:
                    self._midi_port.send_note_on(note, value, channel)
                    ch = channel + 1
                    self._emit_monitor(
                        f"[{self._timestamp()}] OUT -> Vel Fader (Ch:{ch}, "
                        f"Note:{self._format_note(note)}, Vel:{value})",
                        "note_on",
                    )
                except RuntimeError:
                    logger.warning("Failed split zone velocity fader note %d", note)

    def _send_velocity_fader_value(self, mapping: Mapping, value: int) -> None:
        value = max(0, min(127, value))
        self._last_velocity[mapping.id] = value
        self._velocity_fader_on[mapping.id] = value > 0
        for note in mapping.notes:
            if not self._midi_port:
                return
            try:
                self._midi_port.send_note_on(note, value, mapping.channel)
                ch = mapping.channel + 1
                self._emit_monitor(
                    f"[{self._timestamp()}] OUT -> Vel Fader (Ch:{ch}, "
                    f"Note:{self._format_note(note)}, Vel:{value})",
                    "note_on",
                )
            except RuntimeError:
                logger.warning("Failed to send velocity fader note %d", note)

    def _process_digital_note(self, mapping: Mapping, pressed: bool, prev: bool) -> None:
        self._timing.register_mapping(mapping)

        if mapping.digital_mode == DigitalMode.MOMENTARY:
            if pressed and not prev:
                if mapping.uses_fade_in:
                    self._timing.handle_press_fade_in(mapping, mapping.velocity)
                elif not mapping.uses_continuous_hold:
                    self._send_note_on(mapping.channel, mapping.notes, mapping.velocity)
                if mapping.uses_continuous_hold:
                    self._continuous_hold.start(mapping)
                self._fire_extra_targets_press(mapping)
                self._activity[mapping.id] = "ON"
            elif not pressed and prev:
                self._continuous_hold.stop(mapping.id)
                current = self._timing.get_output_value(mapping.id)
                if current < 0:
                    current = mapping.velocity
                if mapping.uses_fade_out and self._timing.handle_release_fade_out(mapping, current):
                    self._fire_extra_targets_release(mapping)
                    self._activity[mapping.id] = "FADE"
                else:
                    self._send_note_off(mapping.channel, mapping.notes)
                    self._fire_extra_targets_release(mapping)
                    self._activity[mapping.id] = ""
        elif mapping.digital_mode == DigitalMode.TOGGLE:
            if pressed and not prev:
                is_on = not self._toggle_on.get(mapping.id, False)
                self._toggle_on[mapping.id] = is_on
                if is_on:
                    self._send_note_on(mapping.channel, mapping.notes, mapping.velocity)
                    self._fire_extra_targets_press(mapping)
                    self._activity[mapping.id] = "ON"
                else:
                    self._send_note_off(mapping.channel, mapping.notes)
                    self._fire_extra_targets_release(mapping)
                    self._activity[mapping.id] = ""

    def _process_digital_velocity_fader(self, mapping: Mapping, pressed: bool, prev: bool) -> None:
        self._timing.register_mapping(mapping)
        output_val = self._digital_vel_fader_value(mapping)

        if mapping.digital_mode != DigitalMode.MOMENTARY:
            return

        if pressed and not prev:
            if mapping.uses_fade_in:
                self._timing.handle_press_fade_in(mapping, output_val)
            elif not mapping.uses_continuous_hold:
                self._send_velocity_fader_value(mapping, output_val)
            if mapping.uses_continuous_hold:
                self._continuous_hold.start(mapping)
            self._fire_extra_targets_press(mapping)
            self._activity[mapping.id] = str(output_val)
        elif not pressed and prev:
            self._continuous_hold.stop(mapping.id)
            current = self._timing.get_output_value(mapping.id)
            if current < 0:
                current = output_val
            if mapping.uses_fade_out and self._timing.handle_release_fade_out(mapping, current):
                self._fire_extra_targets_release(mapping)
                self._activity[mapping.id] = "FADE"
            else:
                self._send_note_off(mapping.channel, mapping.notes)
                self._velocity_fader_on.pop(mapping.id, None)
                self._last_velocity.pop(mapping.id, None)
                self._fire_extra_targets_release(mapping)
                self._activity[mapping.id] = ""

    def _execute_system_command(self, mapping: Mapping, device_id: str) -> None:
        cmd = mapping.system_command
        if cmd == SystemCommand.NEXT_PAGE:
            self.next_page(device_id)
        elif cmd == SystemCommand.PREVIOUS_PAGE:
            self.previous_page(device_id)
        elif cmd == SystemCommand.GO_TO_PAGE:
            self.set_active_page(device_id, mapping.system_page_target)

    def _start_macro(self, mapping: Mapping) -> None:
        if not mapping.macro_steps:
            return
        self._macro_runner.start(mapping.macro_steps)
        self._activity[mapping.id] = "MACRO"
        self.log_system(f"Macro started ({len(mapping.macro_steps)} steps)")

    def _execute_macro_step(self, step: MacroStep) -> None:
        if step.action == MacroActionType.NOTE_ON:
            self._send_note_on(step.channel, [step.note], step.velocity)
        elif step.action == MacroActionType.NOTE_OFF:
            self._send_note_off(step.channel, [step.note])
        elif step.action == MacroActionType.CC:
            self._send_cc(step.channel, step.cc_number, step.value)

    def _process_analog(self, mapping: Mapping, state: ControllerState) -> None:
        raw = self._read_analog(state, mapping.source)

        if mapping.uses_continuous_hold and is_stick_source(mapping.source):
            centered = 0.0 if raw is None else self._centered_analog_value(mapping.source, raw)
            if mapping.is_split_behavior:
                self._process_split_continuous_hold(mapping, centered)
                return
            if mapping.target_type in (
                TargetType.NOTE,
                TargetType.NOTE_VELOCITY_FADER,
            ):
                active = (
                    False
                    if raw is None
                    else self._is_stick_hold_active(mapping, raw)
                )
                prev = self._axis_hold_prev.get(mapping.id, False)
                if mapping.target_type == TargetType.NOTE:
                    self._process_digital_note(mapping, active, prev)
                else:
                    self._process_digital_velocity_fader(mapping, active, prev)
                self._axis_hold_prev[mapping.id] = active
                return

        if raw is None:
            return

        if mapping.is_split_behavior:
            centered = self._centered_analog_value(mapping.source, raw)
            self._process_split(mapping, centered)
            return

        normalized = self._normalize_analog(mapping, raw)

        if mapping.target_type == TargetType.NOTE and mapping.use_threshold:
            self._process_threshold_note(mapping, normalized)
        elif mapping.target_type == TargetType.CC:
            self._process_cc(mapping, normalized)
        elif mapping.target_type == TargetType.PITCH_BEND:
            self._process_pitch_bend(mapping, normalized)
        elif mapping.target_type == TargetType.NOTE_VELOCITY_FADER:
            self._process_velocity_fader(mapping, normalized)

    def _process_split_continuous_hold(self, mapping: Mapping, centered: float) -> None:
        threshold = self._axis_hold_threshold(mapping)
        neg_active = centered < -threshold
        pos_active = centered > threshold

        neg_key = f"{mapping.id}:neg"
        pos_key = f"{mapping.id}:pos"
        neg_prev = self._split_zone_hold_prev.get(neg_key, False)
        pos_prev = self._split_zone_hold_prev.get(pos_key, False)

        self._process_split_zone_hold(mapping, "neg", neg_active, neg_prev)
        self._process_split_zone_hold(mapping, "pos", pos_active, pos_prev)

        self._split_zone_hold_prev[neg_key] = neg_active
        self._split_zone_hold_prev[pos_key] = pos_active

        if neg_active:
            self._activity[mapping.id] = "−"
        elif pos_active:
            self._activity[mapping.id] = "+"
        else:
            self._activity[mapping.id] = ""

    def _process_split_zone_hold(
        self,
        mapping: Mapping,
        side: SplitSide,
        active: bool,
        prev: bool,
    ) -> None:
        kind, channel, note, velocity, cc_number, cc_min, cc_max, mode = self._split_side_config(
            mapping, side
        )

        if kind not in (SplitTargetKind.NOTE, SplitTargetKind.NOTE_VELOCITY_FADER):
            if not active and prev:
                self._continuous_hold.stop(mapping.id, zone=side)
            return

        if mode != DigitalMode.MOMENTARY:
            return

        output_val = velocity if kind == SplitTargetKind.NOTE else max(cc_min, cc_max)

        if active and not prev:
            if mapping.uses_fade_in:
                self._timing.handle_press_fade_in(mapping, output_val)
            elif not mapping.uses_continuous_hold:
                if kind == SplitTargetKind.NOTE:
                    self._send_note_on(channel, [note], velocity)
                else:
                    self._fire_split_zone_pulse(mapping, side)
            if mapping.uses_continuous_hold:
                self._continuous_hold.start(mapping, zone=side)
            self._split_active[mapping.id] = side
        elif not active and prev:
            self._continuous_hold.stop(mapping.id, zone=side)
            current = self._timing.get_output_value(mapping.id)
            if current < 0:
                current = output_val
            if mapping.uses_fade_out and self._timing.handle_release_fade_out(mapping, current):
                pass
            else:
                self._send_note_off(channel, [note])
                vel_key = f"{mapping.id}:{side}"
                self._split_velocity_on.pop(vel_key, None)
                self._split_last_velocity.pop(vel_key, None)
                note_key = f"{mapping.id}:{side}"
                self._split_note_on.pop(note_key, None)
            if self._split_active.get(mapping.id) == side:
                self._split_active[mapping.id] = ""

    def _process_split(self, mapping: Mapping, centered: float) -> None:
        deadzone = mapping.deadzone
        prev_side = self._split_active.get(mapping.id, "")

        if centered < -deadzone:
            current: SplitSide = "neg"
        elif centered > deadzone:
            current = "pos"
        else:
            current = ""

        if current != prev_side:
            if prev_side == "neg":
                self._deactivate_split_side(mapping, "neg")
            elif prev_side == "pos":
                self._deactivate_split_side(mapping, "pos")
            self._split_active[mapping.id] = current
            if current == "neg":
                self._activity[mapping.id] = "−"
                self._on_split_side_enter(mapping, "neg")
            elif current == "pos":
                self._activity[mapping.id] = "+"
                self._on_split_side_enter(mapping, "pos")
            else:
                self._activity[mapping.id] = ""

        if current == "neg":
            self._update_split_side(mapping, "neg", centered, deadzone)
        elif current == "pos":
            self._update_split_side(mapping, "pos", centered, deadzone)

    def _on_split_side_enter(self, mapping: Mapping, side: SplitSide) -> None:
        kind = mapping.neg_split_kind if side == "neg" else mapping.pos_split_kind
        if kind != SplitTargetKind.MACRO:
            return
        steps = mapping.neg_split_macro_steps if side == "neg" else mapping.pos_split_macro_steps
        if not steps:
            steps = mapping.macro_steps
        if steps:
            self._macro_runner.start(steps)
            self._activity[mapping.id] = "MACRO"

    def _update_split_side(self, mapping: Mapping, side: SplitSide, centered: float, deadzone: float) -> None:
        kind, channel, note, velocity, cc_number, cc_min, cc_max, mode = self._split_side_config(mapping, side)
        if kind == SplitTargetKind.MACRO:
            return

        norm = scale_split_side(centered, deadzone, side)
        norm = apply_response_curve(norm, mapping.response_curve)
        if mapping.invert_output:
            norm = 1.0 - norm

        if kind == SplitTargetKind.CC:
            value = transform_to_midi(norm, cc_min, cc_max, 0.0, mapping.invert, False, ResponseCurve.LINEAR)
            cc_key = f"{mapping.id}:{side}"
            if self._last_cc.get(cc_key) == value:
                return
            self._last_cc[cc_key] = value
            self._send_cc(channel, cc_number, value)
            return

        if kind == SplitTargetKind.NOTE_VELOCITY_FADER:
            lo = min(cc_min, cc_max)
            hi = max(cc_min, cc_max)
            value = int(round(lo + norm * (hi - lo)))
            value = max(0, min(127, value))
            vel_key = f"{mapping.id}:{side}"
            is_on = self._split_velocity_on.get(vel_key, False)
            if value <= 0:
                if is_on:
                    self._send_note_off(channel, [note])
                    self._split_velocity_on[vel_key] = False
                    self._split_last_velocity.pop(vel_key, None)
                return
            if self._split_last_velocity.get(vel_key) == value and is_on:
                return
            self._split_last_velocity[vel_key] = value
            self._split_velocity_on[vel_key] = True
            if self._midi_port:
                try:
                    self._midi_port.send_note_on(note, value, channel)
                    ch = channel + 1
                    self._emit_monitor(
                        f"[{self._timestamp()}] OUT -> Vel Fader (Ch:{ch}, "
                        f"Note:{self._format_note(note)}, Vel:{value})",
                        "note_on",
                    )
                except RuntimeError:
                    logger.warning("Failed split velocity fader note %d", note)
            return

        note_key = f"{mapping.id}:{side}"
        is_active = norm > 0.01
        was_active = self._split_note_on.get(note_key, False)
        if mode == DigitalMode.MOMENTARY:
            if is_active and not was_active:
                self._send_note_on(channel, [note], velocity)
            elif not is_active and was_active:
                self._send_note_off(channel, [note])
            self._split_note_on[note_key] = is_active
        elif is_active and not was_active:
            toggled = not self._split_note_on.get(note_key, False)
            self._split_note_on[note_key] = toggled
            if toggled:
                self._send_note_on(channel, [note], velocity)
            else:
                self._send_note_off(channel, [note])

    def _deactivate_split_side(self, mapping: Mapping, side: SplitSide) -> None:
        kind, channel, note, _velocity, cc_number, cc_min, _cc_max, mode = self._split_side_config(mapping, side)
        note_key = f"{mapping.id}:{side}"
        cc_key = f"{mapping.id}:{side}"
        vel_key = f"{mapping.id}:{side}"
        if kind == SplitTargetKind.NOTE:
            if self._split_note_on.get(note_key, False) or mode == DigitalMode.MOMENTARY:
                self._send_note_off(channel, [note])
            self._split_note_on.pop(note_key, None)
        elif kind == SplitTargetKind.NOTE_VELOCITY_FADER:
            if self._split_velocity_on.get(vel_key, False):
                self._send_note_off(channel, [note])
            self._split_velocity_on.pop(vel_key, None)
            self._split_last_velocity.pop(vel_key, None)
        elif kind == SplitTargetKind.CC:
            self._send_cc(channel, cc_number, cc_min)
            self._last_cc.pop(cc_key, None)

    @staticmethod
    def _split_side_config(
        mapping: Mapping, side: SplitSide
    ) -> tuple[SplitTargetKind, int, int, int, int, int, int, DigitalMode]:
        if side == "neg":
            return (
                mapping.neg_split_kind,
                mapping.neg_split_channel,
                mapping.neg_split_note,
                mapping.neg_split_velocity,
                mapping.neg_split_cc,
                mapping.neg_split_min,
                mapping.neg_split_max,
                mapping.neg_split_digital_mode,
            )
        return (
            mapping.pos_split_kind,
            mapping.pos_split_channel,
            mapping.pos_split_note,
            mapping.pos_split_velocity,
            mapping.pos_split_cc,
            mapping.pos_split_min,
            mapping.pos_split_max,
            mapping.pos_split_digital_mode,
        )

    def _axis_hold_threshold(self, mapping: Mapping) -> float:
        if mapping.use_threshold:
            return mapping.threshold
        return 0.5

    def _is_stick_hold_active(self, mapping: Mapping, raw: float) -> bool:
        centered = max(-1.0, min(1.0, raw))
        return abs(centered) > self._axis_hold_threshold(mapping)

    def _centered_analog_value(self, source: InputSource, raw: float) -> float:
        key = source.value
        if key.startswith(("left_stick", "right_stick")):
            return max(-1.0, min(1.0, raw))
        if key in ("l2", "r2") or key.startswith("touchpad"):
            return max(-1.0, min(1.0, raw * 2.0 - 1.0))
        if key in ("gyro_pitch", "gyro_yaw", "gyro_roll"):
            return max(-1.0, min(1.0, raw / 2000.0))
        if key in ("accel_x", "accel_y", "accel_z"):
            return max(-1.0, min(1.0, raw / 32768.0))
        return max(-1.0, min(1.0, raw))

    def _normalize_analog(self, mapping: Mapping, raw: float) -> float:
        key = mapping.source.value
        deadzone = mapping.deadzone
        if key.startswith(("left_stick", "right_stick")):
            centered = apply_deadzone(raw, deadzone)
            normalized = max(0.0, min(1.0, (centered + 1.0) / 2.0))
        elif key in ("gyro_pitch", "gyro_yaw", "gyro_roll", "accel_x", "accel_y", "accel_z"):
            base = normalize_analog_raw(key, raw)
            if base <= deadzone:
                return 0.0
            normalized = min(1.0, (base - deadzone) / (1.0 - deadzone))
        elif key in ("l2", "r2"):
            # Triggers: backend already bottom-deadzones to exact 0.0 on rest.
            if raw <= 0.0:
                return 0.0
            if raw <= deadzone:
                return 0.0
            normalized = min(1.0, (raw - deadzone) / (1.0 - deadzone))
        elif raw <= deadzone:
            return 0.0
        else:
            normalized = min(1.0, (raw - deadzone) / (1.0 - deadzone))

        normalized = apply_response_curve(normalized, mapping.response_curve)
        if mapping.invert_output:
            normalized = 1.0 - normalized
        return normalized

    def _process_threshold_note(self, mapping: Mapping, normalized: float) -> None:
        self._timing.register_mapping(mapping)
        is_above = normalized >= mapping.threshold
        was_above = self._threshold_on.get(mapping.id, False)

        if is_above and not was_above:
            if not self._timing.is_busy(mapping.id):
                if mapping.uses_fade_in:
                    self._timing.handle_press_fade_in(mapping, mapping.velocity)
                else:
                    self._send_note_on(mapping.channel, mapping.notes, mapping.velocity)
                self._activity[mapping.id] = "ON"
        elif not is_above and was_above:
            current = self._timing.get_output_value(mapping.id)
            if current < 0:
                current = mapping.velocity
            if mapping.uses_fade_out and self._timing.handle_release_fade_out(mapping, current):
                self._activity[mapping.id] = "FADE"
            else:
                self._send_note_off(mapping.channel, mapping.notes)
                self._activity[mapping.id] = ""
        self._threshold_on[mapping.id] = is_above

    def _process_cc(self, mapping: Mapping, normalized: float) -> None:
        self._timing.register_mapping(mapping)
        if self._timing.is_busy(mapping.id):
            return

        value = transform_to_midi(
            normalized,
            mapping.min_value,
            mapping.max_value,
            mapping.offset,
            mapping.invert,
            mapping.invert_output,
            mapping.response_curve,
        )
        is_active = normalized > 0.001
        was_active = self._analog_active.get(mapping.id, False)

        if not is_active:
            self._analog_active[mapping.id] = False
            # Must emit resting CC (usually Val:0). Previous code returned early and left
            # the last non-zero value stuck in VJ software forever.
            if was_active or self._last_cc.get(mapping.id) not in (None, value):
                if was_active and mapping.uses_fade_out:
                    last = self._last_cc.get(mapping.id, value)
                    if self._timing.handle_release_fade_out(mapping, last):
                        self._last_cc[mapping.id] = value
                        self._activity[mapping.id] = "FADE"
                        return
                if self._last_cc.get(mapping.id) != value:
                    self._last_cc[mapping.id] = value
                    self._activity[mapping.id] = str(value)
                    self._send_cc(mapping.channel, mapping.cc_number, value)
                else:
                    self._activity[mapping.id] = ""
            return

        self._analog_active[mapping.id] = True
        last = self._last_cc.get(mapping.id)
        if last == value:
            return
        self._last_cc[mapping.id] = value
        self._activity[mapping.id] = str(value)
        self._send_cc(mapping.channel, mapping.cc_number, value)

    def _process_pitch_bend(self, mapping: Mapping, normalized: float) -> None:
        self._timing.register_mapping(mapping)
        if self._timing.is_busy(mapping.id):
            return

        value = transform_to_pitch_bend(
            normalized,
            mapping.min_value,
            mapping.max_value,
            mapping.offset,
            mapping.invert,
            mapping.invert_output,
            mapping.response_curve,
        )
        is_active = normalized > 0.001
        was_active = self._analog_active.get(mapping.id, False)

        if not is_active:
            self._analog_active[mapping.id] = False
            if was_active or self._last_pitch.get(mapping.id) not in (None, value):
                if was_active and mapping.uses_fade_out:
                    last = self._last_pitch.get(mapping.id, value)
                    if self._timing.handle_release_fade_out(mapping, last):
                        self._last_pitch[mapping.id] = value
                        self._activity[mapping.id] = "FADE"
                        return
                if self._last_pitch.get(mapping.id) != value:
                    self._last_pitch[mapping.id] = value
                    self._activity[mapping.id] = str(value)
                    self._send_pitch_bend(mapping.channel, value)
                else:
                    self._activity[mapping.id] = ""
            return

        self._analog_active[mapping.id] = True
        last = self._last_pitch.get(mapping.id)
        if last == value:
            return
        self._last_pitch[mapping.id] = value
        self._activity[mapping.id] = str(value)
        self._send_pitch_bend(mapping.channel, value)

    def _process_velocity_fader(self, mapping: Mapping, normalized: float) -> None:
        self._timing.register_mapping(mapping)
        if self._timing.is_busy(mapping.id):
            return

        lo = min(mapping.min_value, mapping.max_value)
        hi = max(mapping.min_value, mapping.max_value)
        value = int(round(lo + normalized * (hi - lo)))
        value = max(0, min(127, value))
        is_active = value > 0
        was_active = self._velocity_fader_on.get(mapping.id, False)

        if value <= 0:
            if was_active:
                last = self._last_velocity.get(mapping.id, 0)
                if mapping.uses_fade_out and self._timing.handle_release_fade_out(mapping, last):
                    self._velocity_fader_on[mapping.id] = False
                    self._activity[mapping.id] = "FADE"
                else:
                    self._send_note_off(mapping.channel, mapping.notes)
                    self._velocity_fader_on[mapping.id] = False
                    self._last_velocity.pop(mapping.id, None)
                    self._activity[mapping.id] = ""
            return

        last = self._last_velocity.get(mapping.id)
        is_on = self._velocity_fader_on.get(mapping.id, False)

        if last == value and is_on:
            return

        self._last_velocity[mapping.id] = value
        self._velocity_fader_on[mapping.id] = True
        self._activity[mapping.id] = str(value)
        for note in mapping.notes:
            if not self._midi_port:
                return
            try:
                self._midi_port.send_note_on(note, value, mapping.channel)
                ch = mapping.channel + 1
                self._emit_monitor(
                    f"[{self._timestamp()}] OUT -> Vel Fader (Ch:{ch}, "
                    f"Note:{self._format_note(note)}, Vel:{value})",
                    "note_on",
                )
            except RuntimeError:
                logger.warning("Failed to send velocity fader note %d", note)

    def _timing_send_cc(self, mapping: Mapping, value: int) -> None:
        self._last_cc[mapping.id] = value
        self._activity[mapping.id] = str(value) if value > 0 else ""
        self._send_cc(mapping.channel, mapping.cc_number, value)

    def _timing_send_pitch(self, mapping: Mapping, value: int) -> None:
        self._last_pitch[mapping.id] = value
        self._activity[mapping.id] = str(value) if value > 0 else ""
        self._send_pitch_bend(mapping.channel, value)

    def _timing_send_note_velocity(self, mapping: Mapping, velocity: int) -> None:
        self._activity[mapping.id] = str(velocity) if velocity > 0 else ""
        self._send_note_on(mapping.channel, mapping.notes, velocity)

    def _timing_send_note_off(self, mapping: Mapping) -> None:
        self._send_note_off(mapping.channel, mapping.notes)
        self._activity[mapping.id] = ""

    def _timing_send_velocity_fader(self, mapping: Mapping, value: int) -> None:
        self._last_velocity[mapping.id] = value
        self._velocity_fader_on[mapping.id] = value > 0
        self._activity[mapping.id] = str(value) if value > 0 else ""
        for note in mapping.notes:
            if not self._midi_port:
                return
            try:
                if value <= 0:
                    self._midi_port.send_note_off(note, 0, mapping.channel)
                else:
                    self._midi_port.send_note_on(note, value, mapping.channel)
                ch = mapping.channel + 1
                kind: MonitorKind = "note_off" if value <= 0 else "note_on"
                label = "Note Off" if value <= 0 else "Vel Fader"
                self._emit_monitor(
                    f"[{self._timestamp()}] OUT -> {label} (Ch:{ch}, "
                    f"Note:{self._format_note(note)}, Vel:{value})",
                    kind,
                )
            except RuntimeError:
                logger.warning("Failed timing velocity fader note %d", note)

    def _fire_extra_targets_press(self, mapping: Mapping) -> None:
        for target in mapping.extra_targets:
            self._fire_midi_target(target, press=True)

    def _fire_extra_targets_release(self, mapping: Mapping) -> None:
        for target in mapping.extra_targets:
            self._fire_midi_target(target, press=False)

    def _fire_midi_target(self, target: MidiTarget, *, press: bool) -> None:
        if target.target_type == TargetType.NOTE:
            if press:
                self._send_note_on(target.channel, target.notes, target.velocity)
            else:
                self._send_note_off(target.channel, target.notes)
        elif target.target_type == TargetType.CC:
            value = target.max_value if press else target.min_value
            self._send_cc(target.channel, target.cc_number, value)
        elif target.target_type == TargetType.NOTE_VELOCITY_FADER and press:
            vel = max(0, min(127, target.max_value))
            for note in target.notes:
                if self._midi_port:
                    try:
                        self._midi_port.send_note_on(note, vel, target.channel)
                    except RuntimeError:
                        logger.warning("Failed chained velocity fader note %d", note)

    def _read_analog(self, state: ControllerState, source: InputSource) -> Optional[float]:
        key = source.value
        if key in state.axes:
            return state.axes[key]
        if key in state.gyro:
            return state.gyro[key]
        if key in state.accelerometer:
            return state.accelerometer[key]
        return None

    def _timestamp(self) -> str:
        return datetime.now().strftime("%H:%M:%S")

    @staticmethod
    def _format_note(note: int) -> str:
        return f"{note} ({note_to_name(note)})"

    def _emit_monitor(self, message: str, kind: MonitorKind) -> None:
        self.monitor_line.emit(message, kind)

    def _send_note_on(self, channel: int, notes: list[int], velocity: int) -> None:
        if not self._midi_port:
            return
        ch = channel + 1
        for note in notes:
            try:
                self._midi_port.send_note_on(note, velocity, channel)
                self._emit_monitor(
                    f"[{self._timestamp()}] OUT -> Note On (Ch:{ch}, Note:{self._format_note(note)}, Vel:{velocity})",
                    "note_on",
                )
            except RuntimeError:
                logger.warning("Failed to send note on %d", note)

    def _send_note_off(self, channel: int, notes: list[int]) -> None:
        if not self._midi_port:
            return
        ch = channel + 1
        for note in notes:
            try:
                self._midi_port.send_note_off(note, 0, channel)
                self._emit_monitor(
                    f"[{self._timestamp()}] OUT -> Note Off (Ch:{ch}, Note:{self._format_note(note)})",
                    "note_off",
                )
            except RuntimeError:
                logger.warning("Failed to send note off %d", note)

    def _send_cc(self, channel: int, cc_number: int, value: int) -> None:
        if not self._midi_port:
            return
        try:
            self._midi_port.send_control_change(cc_number, value, channel)
            self._emit_monitor(
                f"[{self._timestamp()}] OUT -> CC (Ch:{channel + 1}, CC:{cc_number}, Val:{value})",
                "cc",
            )
        except RuntimeError:
            logger.warning("Failed to send CC %d", cc_number)

    def _send_pitch_bend(self, channel: int, value: int) -> None:
        if not self._midi_port:
            return
        try:
            self._midi_port.send_pitch_bend(value, channel)
            self._emit_monitor(
                f"[{self._timestamp()}] OUT -> Pitch Bend (Ch:{channel + 1}, Val:{value})",
                "pitch",
            )
        except RuntimeError:
            logger.warning("Failed to send pitch bend")

    def _release_mapping(self, mapping: Mapping) -> None:
        self._continuous_hold.stop_zones_for_mapping(mapping.id)
        if mapping.is_split_behavior:
            for side in ("neg", "pos"):
                self._deactivate_split_side(mapping, side)
            return
        if mapping.target_type == TargetType.NOTE_VELOCITY_FADER:
            if self._velocity_fader_on.get(mapping.id, False):
                self._send_note_off(mapping.channel, mapping.notes)
                self._velocity_fader_on.pop(mapping.id, None)
                self._last_velocity.pop(mapping.id, None)
            return
        if mapping.target_type == TargetType.NOTE:
            self._send_note_off(mapping.channel, mapping.notes)

    def _release_device_page_notes(self, device_id: str, page_id: int) -> None:
        for mapping in self._active_mappings(device_id, page_id):
            self._release_mapping(mapping)

    def _release_all_notes(self) -> None:
        for mapping in self._preset.mappings:
            self._release_mapping(mapping)

    def _send_midi_reset(self) -> None:
        if self._midi_port is None or not self._midi_port.is_open:
            return
        try:
            self._midi_port.send_midi_reset()
            self._emit_monitor(
                f"[{self._timestamp()}] OUT -> MIDI Reset (All Notes Off)",
                "system",
            )
        except RuntimeError:
            logger.warning("Failed to send MIDI reset")

    def _clear_mapping_state(self, mapping_id: str) -> None:
        self._prev_digital.pop(mapping_id, None)
        self._axis_hold_prev.pop(mapping_id, None)
        self._split_zone_hold_prev.pop(f"{mapping_id}:neg", None)
        self._split_zone_hold_prev.pop(f"{mapping_id}:pos", None)
        self._toggle_on.pop(mapping_id, None)
        self._threshold_on.pop(mapping_id, None)
        self._last_cc.pop(mapping_id, None)
        self._last_pitch.pop(mapping_id, None)
        self._split_active.pop(mapping_id, None)
        self._split_note_on.pop(mapping_id, None)
        self._split_velocity_on.pop(mapping_id, None)
        self._split_last_velocity.pop(mapping_id, None)
        self._velocity_fader_on.pop(mapping_id, None)
        self._last_velocity.pop(mapping_id, None)
        self._press_start.pop(mapping_id, None)
        self._long_press_fired.pop(mapping_id, None)
        self._last_release_time.pop(mapping_id, None)
        self._pending_tap.pop(mapping_id, None)
        self._activity.pop(mapping_id, None)
        self._analog_active.pop(mapping_id, None)
        self._continuous_hold.stop_zones_for_mapping(mapping_id)
        self._timing.clear_mapping(mapping_id)
        self._timing.unregister_mapping(mapping_id)
        for key in list(self._last_cc.keys()):
            if key.startswith(f"{mapping_id}:"):
                self._last_cc.pop(key, None)
        for key in list(self._split_note_on.keys()):
            if key.startswith(f"{mapping_id}:"):
                self._split_note_on.pop(key, None)
        for key in list(self._split_velocity_on.keys()):
            if key.startswith(f"{mapping_id}:"):
                self._split_velocity_on.pop(key, None)
        for key in list(self._split_last_velocity.keys()):
            if key.startswith(f"{mapping_id}:"):
                self._split_last_velocity.pop(key, None)
