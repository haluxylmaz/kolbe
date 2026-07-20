# Kolbe

A desktop application that converts gamepad/controller inputs into highly customizable MIDI signals. Kolbe creates a virtual MIDI output port on your system so it can be used as a MIDI input device in DAWs, VJ software, and lighting consoles.

## Requirements

* **Python 3.12** (Highly Recommended / Tested Version)
* macOS, Windows, or Linux
* On macOS, you may need to grant Input Monitoring permissions for controller access.

## Setup

```bash
cd kolbe
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
```

## Step 1 — Verify MIDI Port and Controller Input (CLI)

Before launching the GUI, you can run the diagnostic CLI to create a virtual MIDI port and stream controller data to the console to ensure everything is working:

```bash
kolbe probe
```

**Options:**
```bash
kolbe probe --port-name "Kolbe MIDI"   # Custom virtual port name
kolbe probe --list-midi              # List available MIDI ports only
kolbe probe --list-controllers       # List connected gamepads only
```
*Press `Ctrl+C` to exit. The virtual MIDI port remains available to other apps while Kolbe is running.*

## Step 2 — Launch the GUI

Once everything is set up, launch the main application:

```bash
kolbe gui
```

The GUI provides a live controller visualizer (left panel), interactive mapping list (right panel), MIDI port selector, and connection status in the top bar.

### Mapping Workflow

1. Click **+ Add Mapping** to open the editor.
2. Use **MIDI Learn** to auto-detect a button or axis, or pick from the source dropdown.
3. Choose target type: Note, CC, or Pitch Bend.
4. **Save** — the mapping engine sends MIDI on value change only.

### Presets & Templates

* **Save / Load** — store mappings as `.kolbe` or `.json` files.
* **Templates dropdown** — instant Drum Pad, Chord Pad, or DJ / VJ Mode layouts.
* **Preset name** shown in the top bar (default: Untitled).

## Packaging / Building Executables

Kolbe can be compiled into a standalone application using PyInstaller. You can use the provided build scripts or the `.spec` file in the repository.

**Windows:**
```powershell
.\build_win.ps1
# or manually via PyInstaller:
pyinstaller Kolbe_v1.0.2.spec
```

**macOS:**
```bash
./build_mac.sh
```

The compiled application will be generated inside the `dist/` folder.

## Project Structure

```text
src/kolbe/
├── midi/           # Virtual MIDI port management
├── controller/     # Gamepad detection and input reading
├── mapping/        # MappingEngine, models, transforms, presets
├── gui/            # PyQt6 interface (visualizer, mappings, threads)
├── cli.py          # Command-line tools (probe, gui, etc.)
└── __main__.py
```

## Supported Inputs

| Input | Source |
| :--- | :--- |
| Face buttons, D-Pad, triggers, sticks | `pygame` (all controllers) |
| Gyro, accelerometer, touchpad | `pydualsense` (DualSense only) |

## License

MIT
