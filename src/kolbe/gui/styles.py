"""Stage-console dark theme and color palette for Kolbe."""

DARK_STYLESHEET = """
QMainWindow, QWidget {
    background-color: #121212;
    color: #CCCCCC;
    font-family: "Menlo", "Monaco", "Courier New", monospace;
    font-size: 12px;
}

QFrame#panel {
    background-color: #181818;
    border: 1px solid #333333;
    border-radius: 4px;
}

QFrame#topBar {
    background-color: #181818;
    border-bottom: 1px solid #333333;
}

QFrame#connectionBar {
    background-color: #252525;
    border-bottom: 1px solid #333333;
}

QLabel#sectionTitle {
    color: #E8EAED;
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 0.12em;
}

QLabel#brandFooter {
    color: #444444;
    font-size: 22px;
    font-weight: 700;
    letter-spacing: 0.2em;
}

QLabel#statusConnected {
    color: #00FFFF;
    font-weight: 600;
}

QLabel#statusDisconnected {
    color: #FF3333;
    font-weight: 600;
}

QComboBox {
    background-color: #252525;
    border: 1px solid #444444;
    border-radius: 3px;
    padding: 5px 10px;
    color: #CCCCCC;
}

QComboBox:hover {
    border-color: #00FFFF;
}

QComboBox::drop-down {
    border: none;
    width: 22px;
}

QComboBox QAbstractItemView {
    background-color: #252525;
    border: 1px solid #444444;
    selection-background-color: #00FFFF;
    selection-color: #121212;
}

QPushButton {
    background-color: #252525;
    border: 1px solid #444444;
    border-radius: 3px;
    padding: 5px 12px;
    color: #CCCCCC;
}

QPushButton:hover {
    background-color: #2e2e2e;
    border-color: #00FFFF;
}

QPushButton#primaryButton {
    border-color: #00FFFF;
    color: #00FFFF;
}

QPushButton#primaryButton:hover {
    background-color: #003333;
}

QPushButton#dangerButton {
    background-color: #2a1818;
    border-color: #663333;
    color: #ff8888;
}

QPushButton#dangerButton:hover {
    background-color: #3a2020;
    border-color: #ff6666;
    color: #ffaaaa;
}

QPushButton#iconButton {
    padding: 4px 6px;
    min-width: 26px;
    max-width: 26px;
    border: 1px solid #444444;
}

QPushButton#iconButton:hover {
    background-color: #333333;
    border-color: #00FFFF;
    color: #00FFFF;
}

QPushButton#deleteButton {
    border: 1px solid #444444;
}

QPushButton#deleteButton:hover {
    background-color: #330000;
    border-color: #FF3333;
    color: #FF3333;
}

QPushButton#categoryButton {
    text-align: left;
    padding: 8px 10px;
    border: 1px solid transparent;
    border-radius: 2px;
}

QPushButton#categoryButton:hover {
    background-color: #2a2a2a;
    border-color: #444444;
}

QPushButton#categoryButton[active="true"] {
    background-color: #252525;
    border-color: #00FFFF;
    color: #00FFFF;
}

QScrollArea {
    border: none;
    background-color: transparent;
}

QScrollBar:vertical {
    background: #181818;
    width: 8px;
}

QScrollBar::handle:vertical {
    background: #444444;
    border-radius: 4px;
    min-height: 24px;
}

QScrollBar::handle:vertical:hover {
    background: #00FFFF;
}

QSplitter::handle {
    background-color: #333333;
}

QFrame#mappingRow {
    background-color: #252525;
    border: 1px solid #333333;
    border-radius: 4px;
}

QFrame#mappingRow:hover {
    border-color: #555555;
}

QLabel#mappingHeader {
    color: #00FFFF;
    font-weight: 700;
    font-size: 12px;
}

QLabel#mappingDetail {
    color: #AAAAAA;
    font-size: 11px;
}

QLabel#mappingMode {
    color: #FF9900;
    font-size: 11px;
}
"""

# ── Palette ──────────────────────────────────────────────────────────
COLOR_BG_MAIN = "#121212"
COLOR_BG_PANEL = "#181818"
COLOR_BG_SUBPANEL = "#252525"
COLOR_BORDER = "#333333"
COLOR_BORDER_LIGHT = "#444444"

COLOR_CYAN = "#00FFFF"
COLOR_PINK = "#FF1493"
COLOR_AMBER = "#FF9900"
COLOR_RED = "#FF3333"

COLOR_TEXT = "#CCCCCC"
COLOR_TEXT_DIM = "#888888"
COLOR_TEXT_MUTED = "#555555"

COLOR_IDLE = "#2a2a2a"
COLOR_IDLE_BORDER = "#3a3a3a"

# Visualizer-specific aliases
COLOR_DIGITAL_ACTIVE = COLOR_PINK
COLOR_ANALOG_ACTIVE = COLOR_CYAN
COLOR_SENSOR_ACTIVE = COLOR_AMBER
COLOR_STICK_DOT = COLOR_CYAN
COLOR_TRIGGER_FILL = COLOR_CYAN
COLOR_TOUCH = COLOR_AMBER

# Per-controller accent colors — aligned with logical slots 1–4.
CONTROLLER_ACCENT_COLORS = (
    "#00E5FF",  # Controller 1 — cyan
    "#FF2D95",  # Controller 2 — magenta
    "#FF9F1C",  # Controller 3 — orange
    "#44FF88",  # Controller 4 — green
)


def accent_for_controller_index(index: int) -> str:
    if not CONTROLLER_ACCENT_COLORS:
        return COLOR_CYAN
    return CONTROLLER_ACCENT_COLORS[index % len(CONTROLLER_ACCENT_COLORS)]


def accent_for_slot_number(slot: int) -> str:
    return accent_for_controller_index(max(0, int(slot) - 1))


FONT_MONO = "Menlo, Monaco, Courier New, monospace"
