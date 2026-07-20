"""Command-line interface for Kolbe."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from typing import Optional

from kolbe.controller import ControllerManager, detect_controllers
from kolbe.midi import VirtualMidiPort, list_midi_ports
from kolbe.midi.virtual_port import DEFAULT_PORT_NAME

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("kolbe")


def _format_state_line(state) -> str:
    """Build a compact one-line summary of changed inputs."""
    parts: list[str] = []

    active = state.active_buttons()
    if active:
        parts.append(f"BTN[{','.join(active)}]")

    axes = state.non_zero_axes()
    if axes:
        axis_str = ", ".join(f"{k}={v:+.2f}" for k, v in sorted(axes.items()))
        parts.append(f"AX[{axis_str}]")

    if state.gyro:
        g = state.gyro
        gyro_mag = max(abs(g.get("gyro_pitch", 0)), abs(g.get("gyro_yaw", 0)), abs(g.get("gyro_roll", 0)))
        if gyro_mag > 50:
            parts.append(
                f"GYRO[P={g.get('gyro_pitch', 0):.0f} "
                f"Y={g.get('gyro_yaw', 0):.0f} "
                f"R={g.get('gyro_roll', 0):.0f}]"
            )

    if state.accelerometer:
        a = state.accelerometer
        accel_mag = max(abs(a.get("accel_x", 0)), abs(a.get("accel_y", 0)), abs(a.get("accel_z", 0)))
        if accel_mag > 100:
            parts.append(
                f"ACCEL[X={a.get('accel_x', 0):.0f} "
                f"Y={a.get('accel_y', 0):.0f} "
                f"Z={a.get('accel_z', 0):.0f}]"
            )

    for i, touch in enumerate(state.touchpad):
        if touch.active:
            parts.append(f"TOUCH{i}[x={touch.x:.2f} y={touch.y:.2f} id={touch.finger_id}]")

    if state.battery_percent is not None:
        parts.append(f"BAT={state.battery_percent}%")

    return " | ".join(parts) if parts else "(idle)"


def cmd_list_midi(_args: argparse.Namespace) -> int:
    ports = list_midi_ports()
    print("MIDI Input Ports:")
    for name in ports["inputs"] or ["(none)"]:
        print(f"  • {name}")
    print("\nMIDI Output Ports:")
    for name in ports["outputs"] or ["(none)"]:
        print(f"  • {name}")
    return 0


def cmd_list_controllers(_args: argparse.Namespace) -> int:
    devices = detect_controllers()
    if not devices:
        print("No gamepads detected.")
        return 1
    print(f"Found {len(devices)} controller(s):\n")
    for i, dev in enumerate(devices):
        print(f"  [{i}] {dev.name}")
        print(f"      Type:   {dev.controller_type.value}")
        print(f"      Backend: {dev.backend}")
        print(f"      Buttons: {dev.num_buttons}  Axes: {dev.num_axes}  Hats: {dev.num_hats}")
        if dev.guid:
            print(f"      GUID:   {dev.guid}")
        print()
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    port_name = args.port_name or DEFAULT_PORT_NAME
    running = True

    def _handle_signal(_sig, _frame) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    # Step 1: Virtual MIDI port
    print("=" * 60)
    print("KOLBE — Step 1: Virtual MIDI Port")
    print("=" * 60)
    midi = VirtualMidiPort(port_name)
    try:
        midi.open()
        print(f"✓ Virtual MIDI port created: \"{port_name}\"")
        print("  Open your DAW and select this port as a MIDI input.\n")

        # Send a test note so users can verify in a MIDI monitor
        midi.send_note_on(60, velocity=100)
        time.sleep(0.1)
        midi.send_note_off(60)
        print("  Sent test note (C4) — check your MIDI monitor.\n")
    except RuntimeError as exc:
        print(f"✗ MIDI port error: {exc}")
        return 1

    # Step 2: Controller detection
    print("=" * 60)
    print("KOLBE — Step 2: Controller Input")
    print("=" * 60)

    devices = detect_controllers()
    if not devices:
        print("✗ No gamepads detected. Connect a controller and re-run `kolbe probe`.")
        midi.close()
        return 1

    for i, dev in enumerate(devices):
        marker = "→" if i == args.controller else " "
        print(f"{marker} [{i}] {dev.name} ({dev.controller_type.value}, backend={dev.backend})")

    manager = ControllerManager(device_index=args.controller)
    try:
        device = manager.connect()
        print(f"\n✓ Connected to: {device.name}")
        print(f"  Backend: {device.backend}")
        print("\nStreaming input (press Ctrl+C to stop)...\n")
    except RuntimeError as exc:
        print(f"✗ {exc}")
        midi.close()
        return 1

    last_line = ""
    poll_interval = 1.0 / args.rate

    try:
        while running:
            state = manager.poll()
            line = _format_state_line(state)
            if line != last_line:
                print(f"\r{line:<120}", end="", flush=True)
                last_line = line
            time.sleep(poll_interval)
    finally:
        print("\n\nShutting down...")
        manager.disconnect()
        midi.close()
        print("Done.")

    return 0


def cmd_gui(_args: argparse.Namespace) -> int:
    from kolbe.gui.app import run_app

    return run_app()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kolbe",
        description="Kolbe — Gamepad to MIDI converter",
    )
    sub = parser.add_subparsers(dest="command")
    parser.set_defaults(func=cmd_gui)

    probe = sub.add_parser("probe", help="Create virtual MIDI port and stream controller input")
    probe.add_argument(
        "--port-name",
        default=DEFAULT_PORT_NAME,
        help=f"Virtual MIDI port name (default: {DEFAULT_PORT_NAME})",
    )
    probe.add_argument(
        "--controller",
        type=int,
        default=0,
        help="Controller index to use (default: 0)",
    )
    probe.add_argument(
        "--rate",
        type=float,
        default=60.0,
        help="Poll rate in Hz (default: 60)",
    )
    probe.set_defaults(func=cmd_probe)

    list_midi = sub.add_parser("list-midi", help="List available MIDI ports")
    list_midi.set_defaults(func=cmd_list_midi)

    list_ctrl = sub.add_parser("list-controllers", help="List connected gamepads")
    list_ctrl.set_defaults(func=cmd_list_controllers)

    gui = sub.add_parser("gui", help="Launch the graphical interface")
    gui.set_defaults(func=cmd_gui)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
