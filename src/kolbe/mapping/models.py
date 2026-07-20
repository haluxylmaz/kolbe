"""Mapping data models."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from kolbe.controller.types import InputSource

DEFAULT_DEVICE_SLOT = "*"
DEFAULT_PAGE_COUNT = 3


class TargetType(str, Enum):
    NOTE = "note"
    CC = "cc"
    PITCH_BEND = "pitch_bend"
    NOTE_VELOCITY_FADER = "note_velocity_fader"
    SPLIT_NOTE = "split_note"
    SPLIT_CC = "split_cc"
    MACRO = "macro"
    SYSTEM = "system"


class AnalogBehaviorMode(str, Enum):
    CONTINUOUS = "continuous"
    SPLIT = "split"


class SplitTargetKind(str, Enum):
    NOTE = "note"
    CC = "cc"
    NOTE_VELOCITY_FADER = "note_velocity_fader"
    MACRO = "macro"


class DigitalMode(str, Enum):
    MOMENTARY = "momentary"
    TOGGLE = "toggle"
    DOUBLE_TAP = "double_tap"
    LONG_PRESS = "long_press"


class ResponseCurve(str, Enum):
    LINEAR = "linear"
    EXPONENTIAL = "exponential"
    LOGARITHMIC = "logarithmic"


class MacroActionType(str, Enum):
    NOTE_ON = "note_on"
    NOTE_OFF = "note_off"
    CC = "cc"
    DELAY = "delay"


class SystemCommand(str, Enum):
    NEXT_PAGE = "next_page"
    PREVIOUS_PAGE = "previous_page"
    GO_TO_PAGE = "go_to_page"


DIGITAL_SOURCES = frozenset(
    {
        InputSource.CROSS,
        InputSource.CIRCLE,
        InputSource.SQUARE,
        InputSource.TRIANGLE,
        InputSource.A,
        InputSource.B,
        InputSource.X,
        InputSource.Y,
        InputSource.L1,
        InputSource.R1,
        InputSource.L3,
        InputSource.R3,
        InputSource.SHARE,
        InputSource.OPTIONS,
        InputSource.PS,
        InputSource.TOUCHPAD_CLICK,
        InputSource.MICROPHONE,
        InputSource.DPAD_UP,
        InputSource.DPAD_DOWN,
        InputSource.DPAD_LEFT,
        InputSource.DPAD_RIGHT,
    }
)

ANALOG_SOURCES = frozenset(
    {
        InputSource.L2,
        InputSource.R2,
        InputSource.LEFT_STICK_X,
        InputSource.LEFT_STICK_Y,
        InputSource.RIGHT_STICK_X,
        InputSource.RIGHT_STICK_Y,
        InputSource.TOUCHPAD_0_X,
        InputSource.TOUCHPAD_0_Y,
        InputSource.TOUCHPAD_1_X,
        InputSource.TOUCHPAD_1_Y,
        InputSource.GYRO_PITCH,
        InputSource.GYRO_YAW,
        InputSource.GYRO_ROLL,
        InputSource.ACCEL_X,
        InputSource.ACCEL_Y,
        InputSource.ACCEL_Z,
    }
)

NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def is_digital_source(source: InputSource) -> bool:
    return source in DIGITAL_SOURCES


def is_analog_source(source: InputSource) -> bool:
    return source in ANALOG_SOURCES


def is_split_target_type(target_type: TargetType) -> bool:
    return target_type in (TargetType.SPLIT_NOTE, TargetType.SPLIT_CC)


def is_stick_source(source: InputSource) -> bool:
    return source.value.startswith(("left_stick", "right_stick"))


def is_centered_axis_source(source: InputSource) -> bool:
    """Axes that range from -1.0 to +1.0 (sticks)."""
    return is_stick_source(source)


def default_page_names(count: int = DEFAULT_PAGE_COUNT) -> list[str]:
    return [f"Page {i + 1}" for i in range(count)]


def note_to_name(note: int) -> str:
    note = max(0, min(127, note))
    return f"{NOTE_NAMES[note % 12]}{note // 12 - 1}"


def name_to_note(name: str) -> Optional[int]:
    name = name.strip().upper()
    for octave in range(9, -2, -1):
        suffix = str(octave)
        if name.endswith(suffix):
            pitch = name[: -len(suffix)]
            if pitch in NOTE_NAMES:
                return NOTE_NAMES.index(pitch) + (octave + 1) * 12
    return None


def source_label(source: InputSource) -> str:
    labels = {
        InputSource.CROSS: "Cross (×)",
        InputSource.CIRCLE: "Circle (○)",
        InputSource.SQUARE: "Square (□)",
        InputSource.TRIANGLE: "Triangle (△)",
        InputSource.A: "A Button",
        InputSource.B: "B Button",
        InputSource.X: "X Button",
        InputSource.Y: "Y Button",
        InputSource.L1: "L1",
        InputSource.R1: "R1",
        InputSource.L2: "L2 Trigger",
        InputSource.R2: "R2 Trigger",
        InputSource.L3: "L3 (Left Stick Click)",
        InputSource.R3: "R3 (Right Stick Click)",
        InputSource.SHARE: "Share",
        InputSource.OPTIONS: "Options",
        InputSource.PS: "PS Button",
        InputSource.TOUCHPAD_CLICK: "Touchpad Click",
        InputSource.MICROPHONE: "Microphone",
        InputSource.DPAD_UP: "D-Pad Up",
        InputSource.DPAD_DOWN: "D-Pad Down",
        InputSource.DPAD_LEFT: "D-Pad Left",
        InputSource.DPAD_RIGHT: "D-Pad Right",
        InputSource.LEFT_STICK_X: "Left Stick X",
        InputSource.LEFT_STICK_Y: "Left Stick Y",
        InputSource.RIGHT_STICK_X: "Right Stick X",
        InputSource.RIGHT_STICK_Y: "Right Stick Y",
        InputSource.TOUCHPAD_0_X: "Touchpad 0 X",
        InputSource.TOUCHPAD_0_Y: "Touchpad 0 Y",
        InputSource.TOUCHPAD_1_X: "Touchpad 1 X",
        InputSource.TOUCHPAD_1_Y: "Touchpad 1 Y",
        InputSource.GYRO_PITCH: "Gyro Pitch",
        InputSource.GYRO_YAW: "Gyro Yaw",
        InputSource.GYRO_ROLL: "Gyro Roll",
        InputSource.ACCEL_X: "Accel X",
        InputSource.ACCEL_Y: "Accel Y",
        InputSource.ACCEL_Z: "Accel Z",
    }
    return labels.get(source, source.value.replace("_", " ").title())


CHAIN_TARGET_TYPES = frozenset(
    {TargetType.NOTE, TargetType.CC, TargetType.NOTE_VELOCITY_FADER}
)


@dataclass
class MidiTarget:
    """Additional MIDI output chained to the same physical input."""

    target_type: TargetType = TargetType.NOTE
    channel: int = 0
    notes: list[int] = field(default_factory=lambda: [60])
    velocity: int = 127
    cc_number: int = 1
    min_value: int = 0
    max_value: int = 127


@dataclass
class MacroStep:
    action: MacroActionType = MacroActionType.NOTE_ON
    channel: int = 0
    note: int = 60
    velocity: int = 127
    cc_number: int = 1
    value: int = 127
    delay_ms: int = 0


@dataclass
class Mapping:
    """A single controller-input → MIDI routing rule."""

    source: InputSource
    target_type: TargetType
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    device_slot: str = DEFAULT_DEVICE_SLOT
    page_id: int = 0
    channel: int = 0
    notes: list[int] = field(default_factory=lambda: [60])
    velocity: int = 127
    digital_mode: DigitalMode = DigitalMode.MOMENTARY
    cc_number: int = 1
    min_value: int = 0
    max_value: int = 127
    offset: float = 0.0
    invert: bool = False
    invert_output: bool = False
    response_curve: ResponseCurve = ResponseCurve.LINEAR
    deadzone: float = 0.1
    use_threshold: bool = False
    threshold: float = 0.5
    analog_behavior: AnalogBehaviorMode = AnalogBehaviorMode.CONTINUOUS
    neg_split_kind: SplitTargetKind = SplitTargetKind.NOTE
    neg_split_channel: int = 0
    neg_split_note: int = 60
    neg_split_velocity: int = 127
    neg_split_cc: int = 1
    neg_split_min: int = 0
    neg_split_max: int = 127
    neg_split_digital_mode: DigitalMode = DigitalMode.MOMENTARY
    pos_split_kind: SplitTargetKind = SplitTargetKind.NOTE
    pos_split_channel: int = 0
    pos_split_note: int = 62
    pos_split_velocity: int = 127
    pos_split_cc: int = 2
    pos_split_min: int = 0
    pos_split_max: int = 127
    pos_split_digital_mode: DigitalMode = DigitalMode.MOMENTARY
    neg_split_macro_steps: list[MacroStep] = field(default_factory=list)
    pos_split_macro_steps: list[MacroStep] = field(default_factory=list)
    macro_steps: list[MacroStep] = field(default_factory=list)
    system_command: SystemCommand = SystemCommand.NEXT_PAGE
    system_page_target: int = 0
    long_press_ms: int = 500
    double_tap_ms: int = 300
    fade_in_sec: float = 0.0
    fade_out_sec: float = 0.0
    continuous_hold_enabled: bool = False
    extra_targets: list[MidiTarget] = field(default_factory=list)

    @property
    def uses_fade_in(self) -> bool:
        return self.fade_in_sec > 0

    @property
    def uses_fade_out(self) -> bool:
        return self.fade_out_sec > 0

    @property
    def uses_vel_fader_fade(self) -> bool:
        return self.target_type == TargetType.NOTE_VELOCITY_FADER and self.uses_fade_out

    @property
    def uses_continuous_hold(self) -> bool:
        return self.continuous_hold_enabled

    @property
    def is_split_behavior(self) -> bool:
        return self.analog_behavior == AnalogBehaviorMode.SPLIT or is_split_target_type(self.target_type)

    def target_summary(self) -> str:
        page = f"P{self.page_id + 1} "
        dev = "" if self.device_slot == DEFAULT_DEVICE_SLOT else f"[{self.device_slot}] "
        if self.target_type == TargetType.MACRO:
            return f"{dev}{page}Macro ({len(self.macro_steps)} steps)"
        if self.target_type == TargetType.SYSTEM:
            cmd = self.system_command.value.replace("_", " ").title()
            if self.system_command == SystemCommand.GO_TO_PAGE:
                return f"{dev}{page}System: {cmd} {self.system_page_target + 1}"
            return f"{dev}{page}System: {cmd}"
        if self.is_split_behavior:
            neg = self._split_side_summary("-", self.neg_split_kind, self.neg_split_channel,
                                           self.neg_split_note, self.neg_split_velocity, self.neg_split_cc)
            pos = self._split_side_summary("+", self.pos_split_kind, self.pos_split_channel,
                                           self.pos_split_note, self.pos_split_velocity, self.pos_split_cc)
            return f"{dev}{page}Split (dz:{self.deadzone:.0%}) {neg} | {pos}"
        chain = f" +{len(self.extra_targets)}" if self.extra_targets else ""
        ch = self.channel + 1
        if self.target_type == TargetType.NOTE:
            note_str = "+".join(note_to_name(n) for n in self.notes)
            mode = f" {self.digital_mode.value}" if is_digital_source(self.source) else ""
            thresh = f" >{self.threshold:.0%}" if self.use_threshold else ""
            return f"{dev}{page}Ch:{ch} Note:{note_str} Vel:{self.velocity}{mode}{thresh}{chain}"
        if self.target_type == TargetType.NOTE_VELOCITY_FADER:
            note_str = "+".join(note_to_name(n) for n in self.notes)
            return f"{dev}{page}Ch:{ch} Vel Fader:{note_str} [{self.min_value}–{self.max_value}]{chain}"
        if self.target_type == TargetType.CC:
            curve = f" {self.response_curve.value}" if self.response_curve != ResponseCurve.LINEAR else ""
            return f"{dev}{page}Ch:{ch} CC:{self.cc_number} [{self.min_value}–{self.max_value}]{curve}"
        return f"{dev}{page}Ch:{ch} Pitch Bend [{self.min_value}–{self.max_value}]"

    def compact_target_label(self) -> str:
        """Short overlay label for the visualizer (raw note numbers, e.g. 12, CC31)."""
        if self.target_type == TargetType.MACRO:
            return "MACRO"
        if self.target_type == TargetType.SYSTEM:
            return "SYS"
        if self.is_split_behavior:
            return (
                f"{self._compact_split_side(self.neg_split_kind, self.neg_split_note, self.neg_split_cc)}|"
                f"{self._compact_split_side(self.pos_split_kind, self.pos_split_note, self.pos_split_cc)}"
            )
        if self.target_type == TargetType.NOTE:
            if not self.notes:
                return "NOTE"
            label = str(self.notes[0])
            return f"{label}+" if len(self.notes) > 1 else label
        if self.target_type == TargetType.NOTE_VELOCITY_FADER:
            if not self.notes:
                return "VEL"
            return f"V{self.notes[0]}"
        if self.target_type == TargetType.CC:
            return f"CC{self.cc_number}"
        if self.target_type == TargetType.PITCH_BEND:
            return "PB"
        return "?"

    @staticmethod
    def _compact_split_side(kind: SplitTargetKind, note: int, cc_number: int) -> str:
        if kind == SplitTargetKind.NOTE:
            return str(note)
        if kind == SplitTargetKind.NOTE_VELOCITY_FADER:
            return f"V{note}"
        if kind == SplitTargetKind.MACRO:
            return "M"
        return f"CC{cc_number}"

    def source_summary(self) -> str:
        return source_label(self.source)

    @staticmethod
    def _split_side_summary(
        label: str,
        kind: SplitTargetKind,
        channel: int,
        note: int,
        velocity: int,
        cc_number: int,
    ) -> str:
        ch = channel + 1
        if kind == SplitTargetKind.NOTE:
            return f"{label} Ch:{ch} Note:{note_to_name(note)} Vel:{velocity}"
        if kind == SplitTargetKind.NOTE_VELOCITY_FADER:
            return f"{label} Ch:{ch} Vel Fader:{note_to_name(note)}"
        if kind == SplitTargetKind.MACRO:
            return f"{label} Macro"
        return f"{label} Ch:{ch} CC:{cc_number}"


@dataclass
class PresetData:
    name: str
    pages: list[str] = field(default_factory=lambda: default_page_names())
    mappings: list[Mapping] = field(default_factory=list)
    device_pages: dict[str, int] = field(default_factory=dict)
    midi_output_port: str = ""

    def active_page_for(self, device_id: str) -> int:
        return self.device_pages.get(device_id, 0)

    def set_active_page_for(self, device_id: str, page_id: int) -> None:
        self.device_pages[device_id] = max(0, min(page_id, len(self.pages) - 1))
