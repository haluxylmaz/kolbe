"""Create and manage a MIDI output port (virtual on macOS, system port elsewhere)."""

from __future__ import annotations

import logging
import sys
from typing import Optional

import mido

logger = logging.getLogger(__name__)

DEFAULT_PORT_NAME = "Kolbe Virtual MIDI"


def supports_virtual_midi() -> bool:
    """Return True when the platform can create virtual MIDI ports."""
    return sys.platform == "darwin"


def list_midi_ports() -> dict[str, list[str]]:
    """Return available MIDI input and output port names."""
    return {
        "inputs": mido.get_input_names(),
        "outputs": mido.get_output_names(),
    }


class VirtualMidiPort:
    """Wraps a mido output port for sending MIDI messages."""

    def __init__(self, name: str = DEFAULT_PORT_NAME, *, use_virtual: Optional[bool] = None) -> None:
        self.name = name
        self._use_virtual = use_virtual
        self._port: Optional[mido.ports.BaseOutput] = None
        self.last_error: Optional[str] = None

    @property
    def use_virtual(self) -> bool:
        if self._use_virtual is not None:
            return self._use_virtual
        return supports_virtual_midi()

    @property
    def is_open(self) -> bool:
        return self._port is not None and not self._port.closed

    def open(self) -> None:
        if self.is_open:
            return
        self.last_error = None
        try:
            if self.use_virtual:
                self._port = mido.open_output(self.name, virtual=True)
                logger.info("Virtual MIDI port opened: %s", self.name)
            else:
                outputs = mido.get_output_names()
                if self.name not in outputs:
                    raise OSError(
                        f"MIDI output port '{self.name}' not found. "
                        f"Available ports: {', '.join(outputs) or '(none)'}"
                    )
                self._port = mido.open_output(self.name)
                logger.info("MIDI output port opened: %s", self.name)
        except OSError as exc:
            self.last_error = str(exc)
            if self.use_virtual:
                message = (
                    f"Failed to create virtual MIDI port '{self.name}'. "
                    "Ensure python-rtmidi is installed and no other app is using the name."
                )
            else:
                message = f"Failed to open MIDI output port '{self.name}': {exc}"
            raise RuntimeError(message) from exc

    def close(self) -> None:
        if self._port is not None:
            try:
                if not self._port.closed:
                    self._port.close()
            except Exception:
                logger.exception("Error closing MIDI port: %s", self.name)
            self._port = None
            logger.info("MIDI port closed: %s", self.name)

    def send(self, message: mido.Message) -> None:
        if not self.is_open or self._port is None:
            raise RuntimeError("MIDI port is not open")
        self._port.send(message)

    def send_note_on(self, note: int, velocity: int = 127, channel: int = 0) -> None:
        self.send(mido.Message("note_on", note=note, velocity=velocity, channel=channel))

    def send_note_off(self, note: int, velocity: int = 0, channel: int = 0) -> None:
        self.send(mido.Message("note_off", note=note, velocity=velocity, channel=channel))

    def send_control_change(self, control: int, value: int, channel: int = 0) -> None:
        self.send(mido.Message("control_change", control=control, value=value, channel=channel))

    def send_pitch_bend(self, pitch: int, channel: int = 0) -> None:
        self.send(mido.Message("pitchwheel", pitch=pitch, channel=channel))

    def send_midi_reset(self) -> None:
        """Send All Notes Off and All Sound Off on every channel."""
        for channel in range(16):
            self.send_control_change(123, 0, channel)
            self.send_control_change(120, 0, channel)

    def __enter__(self) -> VirtualMidiPort:
        self.open()
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
