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
