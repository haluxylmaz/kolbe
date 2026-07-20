"""Non-blocking fade-in / fade-out ramps via QTimer (main-thread safe)."""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

from PyQt6.QtCore import QObject, QTimer

from kolbe.mapping.models import Mapping, TargetType

TICK_MS = 16


class TimingPhase(str, Enum):
    IDLE = "idle"
    RAMP_UP = "ramp_up"
    RAMP_DOWN = "ramp_down"


@dataclass
class _TimingState:
    phase: TimingPhase = TimingPhase.IDLE
    phase_start: float = 0.0
    ramp_start_value: int = 0
    ramp_end_value: int = 0
    last_sent_value: int = -1
    target_type: TargetType = TargetType.CC


class OutputTimingManager(QObject):
    """Smooth value ramps on press (fade in) and release (fade out)."""

    def __init__(
        self,
        *,
        send_cc: Callable[[Mapping, int], None],
        send_pitch: Callable[[Mapping, int], None],
        send_note_velocity: Callable[[Mapping, int], None],
        send_note_off: Callable[[Mapping], None],
        send_velocity_fader: Callable[[Mapping, int], None],
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._send_cc = send_cc
        self._send_pitch = send_pitch
        self._send_note_velocity = send_note_velocity
        self._send_note_off = send_note_off
        self._send_velocity_fader = send_velocity_fader
        self._states: dict[str, _TimingState] = {}
        self._mapping_holder: dict[str, Mapping] = {}
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def is_busy(self, mapping_id: str) -> bool:
        state = self._states.get(mapping_id)
        return state is not None and state.phase != TimingPhase.IDLE

    def get_output_value(self, mapping_id: str) -> int:
        state = self._states.get(mapping_id)
        if state is None or state.last_sent_value < 0:
            return -1
        return state.last_sent_value

    def clear_mapping(self, mapping_id: str) -> None:
        self._states.pop(mapping_id, None)

    def stop_all(self) -> None:
        self._states.clear()
        self._mapping_holder.clear()

    def handle_press_fade_in(self, mapping: Mapping, target_value: int) -> bool:
        """Ramp from 0 to target_value on press. Returns True if ramp started."""
        if mapping.fade_in_sec <= 0 or target_value <= 0:
            return False

        state = self._state_for(mapping)
        state.target_type = mapping.target_type
        state.phase = TimingPhase.RAMP_UP
        state.phase_start = time.monotonic()
        state.ramp_start_value = 0
        state.ramp_end_value = max(0, min(127, target_value))
        state.last_sent_value = -1
        self._emit_value(mapping, 0, state)
        return True

    def handle_release_fade_out(self, mapping: Mapping, current_value: int) -> bool:
        """Ramp from current_value to 0 on release. Returns True if ramp started."""
        if mapping.fade_out_sec <= 0:
            return False
        if current_value <= 0:
            return False

        state = self._state_for(mapping)
        if state.phase == TimingPhase.RAMP_DOWN:
            return True

        state.target_type = mapping.target_type
        state.phase = TimingPhase.RAMP_DOWN
        state.phase_start = time.monotonic()
        state.ramp_start_value = max(0, min(127, current_value))
        state.ramp_end_value = 0
        state.last_sent_value = -1
        self._emit_value(mapping, state.ramp_start_value, state)
        return True

    def _state_for(self, mapping: Mapping) -> _TimingState:
        if mapping.id not in self._states:
            self._states[mapping.id] = _TimingState(target_type=mapping.target_type)
        return self._states[mapping.id]

    def _tick(self) -> None:
        now = time.monotonic()
        for mapping_id, state in list(self._states.items()):
            mapping = self._mapping_holder.get(mapping_id)
            if mapping is None:
                continue

            if state.phase == TimingPhase.RAMP_UP:
                duration = mapping.fade_in_sec
                elapsed = now - state.phase_start
                progress = 1.0 if duration <= 0 else min(1.0, elapsed / duration)
                span = state.ramp_end_value - state.ramp_start_value
                value = int(round(state.ramp_start_value + span * progress))
                if value != state.last_sent_value:
                    self._emit_value(mapping, value, state)
                if progress >= 1.0:
                    state.phase = TimingPhase.IDLE
                continue

            if state.phase == TimingPhase.RAMP_DOWN:
                duration = mapping.fade_out_sec
                elapsed = now - state.phase_start
                progress = 1.0 if duration <= 0 else min(1.0, elapsed / duration)
                span = state.ramp_end_value - state.ramp_start_value
                value = int(round(state.ramp_start_value + span * progress))
                if value != state.last_sent_value:
                    self._emit_value(mapping, value, state)
                if progress >= 1.0:
                    self._emit_value(mapping, 0, state)
                    self._finalize_off(mapping, state)
                    state.phase = TimingPhase.IDLE

    def register_mapping(self, mapping: Mapping) -> None:
        self._mapping_holder[mapping.id] = mapping

    def unregister_mapping(self, mapping_id: str) -> None:
        self._mapping_holder.pop(mapping_id, None)

    def _emit_value(self, mapping: Mapping, value: int, state: _TimingState) -> None:
        value = max(0, min(127, value))
        if value == state.last_sent_value and value > 0:
            return
        state.last_sent_value = value
        target = state.target_type

        if target == TargetType.CC:
            self._send_cc(mapping, value)
        elif target == TargetType.PITCH_BEND:
            self._send_pitch(mapping, value)
        elif target == TargetType.NOTE_VELOCITY_FADER:
            if value <= 0:
                self._send_note_off(mapping)
            else:
                self._send_velocity_fader(mapping, value)
        elif target == TargetType.NOTE:
            if value <= 0:
                self._send_note_off(mapping)
            else:
                self._send_note_velocity(mapping, value)

    def _finalize_off(self, mapping: Mapping, state: _TimingState) -> None:
        target = state.target_type
        if target in (TargetType.NOTE, TargetType.NOTE_VELOCITY_FADER):
            self._send_note_off(mapping)
        elif target == TargetType.CC:
            self._send_cc(mapping, mapping.min_value)
        elif target == TargetType.PITCH_BEND:
            self._send_pitch(mapping, mapping.min_value)
