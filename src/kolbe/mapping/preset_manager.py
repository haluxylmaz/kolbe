"""Preset serialization, file I/O, and built-in templates."""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import QFileDialog, QMessageBox, QWidget

from kolbe.controller.types import InputSource
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
    default_page_names,
)

PRESET_VERSION = 8
PRESET_FILTER = "Kolbe Presets (*.kolbe *.json);;All Files (*)"
BASIC_TEMPLATE_NAME = "Basic Triggers & Bumpers"
KOLBE_USER_DIR = Path.home() / ".kolbe"
STARTUP_PRESET_PATH = KOLBE_USER_DIR / "startup_preset.kolbe"

logger = logging.getLogger(__name__)


def midi_target_to_dict(target: MidiTarget) -> dict:
    return {
        "target_type": target.target_type.value,
        "channel": target.channel,
        "notes": list(target.notes),
        "velocity": target.velocity,
        "cc_number": target.cc_number,
        "min_value": target.min_value,
        "max_value": target.max_value,
    }


def midi_target_from_dict(data: dict) -> MidiTarget:
    return MidiTarget(
        target_type=TargetType(data.get("target_type", TargetType.NOTE.value)),
        channel=int(data.get("channel", 0)),
        notes=[int(n) for n in data.get("notes", [60])],
        velocity=int(data.get("velocity", 127)),
        cc_number=int(data.get("cc_number", 1)),
        min_value=int(data.get("min_value", 0)),
        max_value=int(data.get("max_value", 127)),
    )


def macro_step_to_dict(step: MacroStep) -> dict:
    return {
        "action": step.action.value,
        "channel": step.channel,
        "note": step.note,
        "velocity": step.velocity,
        "cc_number": step.cc_number,
        "value": step.value,
        "delay_ms": step.delay_ms,
    }


def macro_step_from_dict(data: dict) -> MacroStep:
    return MacroStep(
        action=MacroActionType(data.get("action", MacroActionType.NOTE_ON.value)),
        channel=int(data.get("channel", 0)),
        note=int(data.get("note", 60)),
        velocity=int(data.get("velocity", 127)),
        cc_number=int(data.get("cc_number", 1)),
        value=int(data.get("value", 127)),
        delay_ms=int(data.get("delay_ms", 0)),
    )


def mapping_to_dict(mapping: Mapping) -> dict:
    return {
        "id": mapping.id,
        "source": mapping.source.value,
        "target_type": mapping.target_type.value,
        "device_slot": mapping.device_slot,
        "page_id": mapping.page_id,
        "channel": mapping.channel,
        "notes": list(mapping.notes),
        "velocity": mapping.velocity,
        "digital_mode": mapping.digital_mode.value,
        "cc_number": mapping.cc_number,
        "min_value": mapping.min_value,
        "max_value": mapping.max_value,
        "offset": mapping.offset,
        "invert": mapping.invert,
        "invert_output": mapping.invert_output,
        "response_curve": mapping.response_curve.value,
        "deadzone": mapping.deadzone,
        "use_threshold": mapping.use_threshold,
        "threshold": mapping.threshold,
        "analog_behavior": mapping.analog_behavior.value,
        "neg_split_kind": mapping.neg_split_kind.value,
        "neg_split_channel": mapping.neg_split_channel,
        "neg_split_note": mapping.neg_split_note,
        "neg_split_velocity": mapping.neg_split_velocity,
        "neg_split_cc": mapping.neg_split_cc,
        "neg_split_min": mapping.neg_split_min,
        "neg_split_max": mapping.neg_split_max,
        "neg_split_digital_mode": mapping.neg_split_digital_mode.value,
        "pos_split_kind": mapping.pos_split_kind.value,
        "pos_split_channel": mapping.pos_split_channel,
        "pos_split_note": mapping.pos_split_note,
        "pos_split_velocity": mapping.pos_split_velocity,
        "pos_split_cc": mapping.pos_split_cc,
        "pos_split_min": mapping.pos_split_min,
        "pos_split_max": mapping.pos_split_max,
        "pos_split_digital_mode": mapping.pos_split_digital_mode.value,
        "neg_split_macro_steps": [macro_step_to_dict(s) for s in mapping.neg_split_macro_steps],
        "pos_split_macro_steps": [macro_step_to_dict(s) for s in mapping.pos_split_macro_steps],
        "macro_steps": [macro_step_to_dict(s) for s in mapping.macro_steps],
        "system_command": mapping.system_command.value,
        "system_page_target": mapping.system_page_target,
        "long_press_ms": mapping.long_press_ms,
        "double_tap_ms": mapping.double_tap_ms,
        "fade_in_sec": mapping.fade_in_sec,
        "fade_out_sec": mapping.fade_out_sec,
        "continuous_hold_enabled": mapping.continuous_hold_enabled,
        "extra_targets": [midi_target_to_dict(t) for t in mapping.extra_targets],
    }


def _load_analog_behavior(value: str) -> AnalogBehaviorMode:
    if value == "radial":
        return AnalogBehaviorMode.CONTINUOUS
    return AnalogBehaviorMode(value)


def _parse_preset_version(data: dict) -> int:
    raw = data.get("version", 1)
    try:
        return int(raw)
    except (TypeError, ValueError):
        logger.warning("Invalid preset version %r; treating as version 1", raw)
        return 1


def _migrate_mapping_dict(data: dict, source_version: int) -> dict:
    """Fill missing mapping keys and apply version-specific upgrades."""
    migrated = dict(data)

    if source_version < 2:
        migrated.setdefault("device_slot", DEFAULT_DEVICE_SLOT)
        migrated.setdefault("page_id", 0)

    if source_version < 3:
        migrated.setdefault("analog_behavior", AnalogBehaviorMode.CONTINUOUS.value)
        migrated.setdefault("use_threshold", False)
        migrated.setdefault("threshold", 0.5)

    if source_version < 4:
        migrated.setdefault("macro_steps", [])
        migrated.setdefault("system_command", SystemCommand.NEXT_PAGE.value)
        migrated.setdefault("system_page_target", 0)
        migrated.setdefault("long_press_ms", 500)
        migrated.setdefault("double_tap_ms", 300)

    if source_version < 5:
        migrated.setdefault("extra_targets", [])
        migrated.setdefault("neg_split_macro_steps", [])
        migrated.setdefault("pos_split_macro_steps", [])

    if source_version < 6:
        migrated.setdefault("on_duration_sec", 0.0)
        migrated.setdefault("fade_duration_sec", 0.0)
        migrated.setdefault("loop_enabled", False)

    if source_version < 8:
        fade_out = float(migrated.get("fade_out_sec", migrated.get("fade_duration_sec", 0.0)))
        fade_in = float(migrated.get("fade_in_sec", 0.0))
        hold = bool(
            migrated.get(
                "continuous_hold_enabled",
                migrated.get("auto_fire_enabled", False),
            )
        )
        migrated["fade_in_sec"] = fade_in
        migrated["fade_out_sec"] = fade_out
        migrated["continuous_hold_enabled"] = hold

    return migrated


def migrate_preset_data(data: object) -> dict:
    """Normalize legacy preset JSON to the current in-memory structure."""
    if isinstance(data, list):
        payload: dict = {"version": 1, "name": "Untitled", "mappings": data}
    elif isinstance(data, dict):
        payload = dict(data)
        if "mappings" not in payload and "source" in payload and "target_type" in payload:
            payload = {"version": 1, "name": "Untitled", "mappings": [payload]}
    else:
        raise ValueError("Preset file must contain a JSON object or mapping list")

    source_version = _parse_preset_version(payload)
    if source_version > PRESET_VERSION:
        logger.warning(
            "Preset version %s is newer than app version %s; loading with defaults for unknown fields",
            source_version,
            PRESET_VERSION,
        )
    elif source_version < PRESET_VERSION:
        logger.info("Upgrading preset from version %s to %s", source_version, PRESET_VERSION)

    payload.setdefault("name", "Untitled")
    payload.setdefault("pages", default_page_names())
    payload.setdefault("device_pages", {})
    payload.setdefault("midi_output_port", "")
    payload.setdefault("mappings", [])
    payload["version"] = PRESET_VERSION

    migrated_mappings: list[dict] = []
    for item in payload["mappings"]:
        if not isinstance(item, dict):
            logger.warning("Skipping non-object mapping entry: %r", item)
            continue
        migrated_mappings.append(_migrate_mapping_dict(item, source_version))
    payload["mappings"] = migrated_mappings

    return payload


def mapping_from_dict(data: dict) -> Mapping:
    return Mapping(
        id=data.get("id", str(uuid.uuid4())),
        source=InputSource(data["source"]),
        target_type=TargetType(data["target_type"]),
        device_slot=str(data.get("device_slot", DEFAULT_DEVICE_SLOT)),
        page_id=int(data.get("page_id", 0)),
        channel=int(data.get("channel", 0)),
        notes=[int(n) for n in data.get("notes", [60])],
        velocity=int(data.get("velocity", 127)),
        digital_mode=DigitalMode(data.get("digital_mode", DigitalMode.MOMENTARY.value)),
        cc_number=int(data.get("cc_number", 1)),
        min_value=int(data.get("min_value", 0)),
        max_value=int(data.get("max_value", 127)),
        offset=float(data.get("offset", 0.0)),
        invert=bool(data.get("invert", False)),
        invert_output=bool(data.get("invert_output", False)),
        response_curve=ResponseCurve(data.get("response_curve", ResponseCurve.LINEAR.value)),
        deadzone=float(data.get("deadzone", 0.1)),
        use_threshold=bool(data.get("use_threshold", False)),
        threshold=float(data.get("threshold", 0.5)),
        analog_behavior=_load_analog_behavior(data.get("analog_behavior", AnalogBehaviorMode.CONTINUOUS.value)),
        neg_split_kind=SplitTargetKind(data.get("neg_split_kind", SplitTargetKind.NOTE.value)),
        neg_split_channel=int(data.get("neg_split_channel", 0)),
        neg_split_note=int(data.get("neg_split_note", 60)),
        neg_split_velocity=int(data.get("neg_split_velocity", 127)),
        neg_split_cc=int(data.get("neg_split_cc", 1)),
        neg_split_min=int(data.get("neg_split_min", 0)),
        neg_split_max=int(data.get("neg_split_max", 127)),
        neg_split_digital_mode=DigitalMode(data.get("neg_split_digital_mode", DigitalMode.MOMENTARY.value)),
        pos_split_kind=SplitTargetKind(data.get("pos_split_kind", SplitTargetKind.NOTE.value)),
        pos_split_channel=int(data.get("pos_split_channel", 0)),
        pos_split_note=int(data.get("pos_split_note", 62)),
        pos_split_velocity=int(data.get("pos_split_velocity", 127)),
        pos_split_cc=int(data.get("pos_split_cc", 2)),
        pos_split_min=int(data.get("pos_split_min", 0)),
        pos_split_max=int(data.get("pos_split_max", 127)),
        pos_split_digital_mode=DigitalMode(data.get("pos_split_digital_mode", DigitalMode.MOMENTARY.value)),
        neg_split_macro_steps=[macro_step_from_dict(s) for s in data.get("neg_split_macro_steps", [])],
        pos_split_macro_steps=[macro_step_from_dict(s) for s in data.get("pos_split_macro_steps", [])],
        macro_steps=[macro_step_from_dict(s) for s in data.get("macro_steps", [])],
        system_command=SystemCommand(data.get("system_command", SystemCommand.NEXT_PAGE.value)),
        system_page_target=int(data.get("system_page_target", 0)),
        long_press_ms=int(data.get("long_press_ms", 500)),
        double_tap_ms=int(data.get("double_tap_ms", 300)),
        fade_in_sec=float(data.get("fade_in_sec", 0.0)),
        fade_out_sec=float(data.get("fade_out_sec", 0.0)),
        continuous_hold_enabled=bool(data.get("continuous_hold_enabled", False)),
        extra_targets=[midi_target_from_dict(t) for t in data.get("extra_targets", [])],
    )


def preset_to_dict(preset: PresetData) -> dict:
    return {
        "version": PRESET_VERSION,
        "name": preset.name,
        "pages": list(preset.pages),
        "device_pages": dict(preset.device_pages),
        "midi_output_port": preset.midi_output_port,
        "mappings": [mapping_to_dict(m) for m in preset.mappings],
    }


def preset_from_dict(data: dict) -> PresetData:
    migrated = migrate_preset_data(data)
    name = str(migrated.get("name", "Untitled"))
    pages = list(migrated.get("pages", default_page_names()))
    device_pages = {str(k): int(v) for k, v in migrated.get("device_pages", {}).items()}
    midi_output_port = str(migrated.get("midi_output_port", ""))

    mappings: list[Mapping] = []
    for item in migrated.get("mappings", []):
        try:
            mappings.append(mapping_from_dict(item))
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("Skipping invalid mapping entry: %s", exc)

    return PresetData(
        name=name,
        pages=pages,
        mappings=mappings,
        device_pages=device_pages,
        midi_output_port=midi_output_port,
    )


class PresetManager:
    """Save, load, and apply mapping presets."""

    TEMPLATE_NAMES = (BASIC_TEMPLATE_NAME,)

    def __init__(self) -> None:
        self.current_name = "Untitled"
        self.current_path: Optional[Path] = None

    def save_to_file(self, path: Path, preset: PresetData) -> None:
        payload = preset_to_dict(preset)
        path = Path(path)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self.current_name = preset.name
        self.current_path = path

    def load_from_file(self, path: Path) -> PresetData:
        path = Path(path)
        raw = json.loads(path.read_text(encoding="utf-8"))
        preset = preset_from_dict(raw)
        self.current_name = preset.name
        self.current_path = path
        return preset

    def save_with_dialog(self, parent: QWidget, preset: PresetData) -> bool:
        name = preset.name or self.current_name
        default_path = ""
        if self.current_path:
            default_path = str(self.current_path)
        elif name and name != "Untitled":
            default_path = str(Path.home() / f"{name}.kolbe")

        file_path, _ = QFileDialog.getSaveFileName(parent, "Save Preset", default_path, PRESET_FILTER)
        if not file_path:
            return False

        path = Path(file_path)
        if path.suffix.lower() not in (".kolbe", ".json"):
            path = path.with_suffix(".kolbe")

        preset.name = path.stem
        try:
            self.save_to_file(path, preset)
        except OSError as exc:
            QMessageBox.critical(parent, "Save Failed", str(exc))
            return False
        return True

    def load_with_dialog(self, parent: QWidget) -> Optional[PresetData]:
        file_path, _ = QFileDialog.getOpenFileName(parent, "Load Preset", str(Path.home()), PRESET_FILTER)
        if not file_path:
            return None
        try:
            return self.load_from_file(Path(file_path))
        except (OSError, json.JSONDecodeError, ValueError, KeyError) as exc:
            QMessageBox.critical(parent, "Load Failed", f"Could not load preset:\n{exc}")
            return None

    def load_startup_preset(self) -> PresetData:
        if STARTUP_PRESET_PATH.exists():
            try:
                return self.load_from_file(STARTUP_PRESET_PATH)
            except (OSError, json.JSONDecodeError, ValueError, KeyError) as exc:
                logging.getLogger(__name__).warning("Could not load startup preset: %s", exc)
        return self.apply_template(BASIC_TEMPLATE_NAME)

    def save_startup_preset(self, preset: PresetData) -> None:
        KOLBE_USER_DIR.mkdir(parents=True, exist_ok=True)
        self.save_to_file(STARTUP_PRESET_PATH, preset)

    def get_template(self, template_name: str) -> PresetData:
        if template_name != BASIC_TEMPLATE_NAME:
            raise ValueError(f"Unknown template: {template_name}")
        return PresetData(name=template_name, mappings=_template_basic_triggers_bumpers())

    def apply_template(self, template_name: str) -> PresetData:
        preset = self.get_template(template_name)
        self.current_name = template_name
        self.current_path = None
        return preset

    def mark_untitled(self) -> None:
        self.current_name = "Untitled"
        self.current_path = None


def _note_mapping(
    source: InputSource,
    notes: list[int],
    channel: int = 0,
    velocity: int = 127,
    mode: DigitalMode = DigitalMode.MOMENTARY,
) -> Mapping:
    return Mapping(
        source=source,
        target_type=TargetType.NOTE,
        channel=channel,
        notes=notes,
        velocity=velocity,
        digital_mode=mode,
    )


def _cc_mapping(
    source: InputSource,
    cc_number: int,
    channel: int = 0,
    min_value: int = 0,
    max_value: int = 127,
    deadzone: float = 0.1,
    invert: bool = False,
) -> Mapping:
    return Mapping(
        source=source,
        target_type=TargetType.CC,
        channel=channel,
        cc_number=cc_number,
        min_value=min_value,
        max_value=max_value,
        deadzone=deadzone,
        invert=invert,
    )


def _template_basic_triggers_bumpers() -> list[Mapping]:
    dz = 0.1
    return [
        _note_mapping(InputSource.L1, [60]),
        _note_mapping(InputSource.R1, [62]),
        _cc_mapping(InputSource.L2, cc_number=11, deadzone=dz),
        _cc_mapping(InputSource.R2, cc_number=12, deadzone=dz),
    ]
