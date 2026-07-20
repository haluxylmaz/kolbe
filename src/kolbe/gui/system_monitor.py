"""Live system monitor — color-coded MIDI and status log."""

from __future__ import annotations

import time
from collections import deque
from typing import Optional

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPlainTextEdit, QProgressBar, QVBoxLayout, QWidget

from kolbe.gui.styles import FONT_MONO

_MONITOR_COLORS = {
    "note_on": "#44FF88",
    "note_off": "#FF6666",
    "cc": "#00FFFF",
    "pitch": "#FFAA00",
    "system": "#FFDD44",
    "warning": "#FFDD44",
}

_MAX_LINES = 500


class SystemMonitorWidget(QWidget):
    """Read-only console for outgoing MIDI and status events."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("panel")

        self._frame_times: deque[float] = deque(maxlen=120)
        self._activity_score = 0.0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 8)
        layout.setSpacing(4)

        header = QHBoxLayout()
        header.setSpacing(12)
        title = QLabel("SYSTEM MONITOR")
        title.setObjectName("sectionTitle")
        header.addWidget(title)
        header.addStretch()

        self.fps_label = QLabel("FPS —")
        self.fps_label.setStyleSheet("color: #8b93a7; font-family: monospace; font-size: 10px;")
        header.addWidget(self.fps_label)

        load_lbl = QLabel("Load")
        load_lbl.setStyleSheet("color: #8b93a7; font-size: 9px;")
        header.addWidget(load_lbl)

        self.load_bar = QProgressBar()
        self.load_bar.setRange(0, 100)
        self.load_bar.setFixedWidth(80)
        self.load_bar.setFixedHeight(8)
        self.load_bar.setTextVisible(False)
        self.load_bar.setStyleSheet(
            "QProgressBar { background: #0a0a0a; border: 1px solid #333; border-radius: 2px; }"
            "QProgressBar::chunk { background: qlineargradient("
            "x1:0, y1:0, x2:1, y2:0, stop:0 #00bcd4, stop:1 #ffaa00); border-radius: 2px; }"
        )
        header.addWidget(self.load_bar)
        layout.addLayout(header)

        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.console.setMaximumBlockCount(_MAX_LINES)
        self.console.setFont(QFont(FONT_MONO.split(",")[0].strip(), 11))
        self.console.setStyleSheet(
            "QPlainTextEdit {"
            "  background-color: #0a0a0a;"
            "  color: #cccccc;"
            "  border: 1px solid #333333;"
            "  border-radius: 3px;"
            "  padding: 6px;"
            "  font-family: Menlo, Monaco, 'Courier New', monospace;"
            "}"
        )
        layout.addWidget(self.console)

        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._refresh_status)
        self._timer.start()

    def record_frame(self) -> None:
        self._frame_times.append(time.monotonic())
        self._activity_score = min(100.0, self._activity_score + 4.0)

    def record_activity(self, amount: float = 8.0) -> None:
        self._activity_score = min(100.0, self._activity_score + amount)

    def _refresh_status(self) -> None:
        now = time.monotonic()
        while self._frame_times and now - self._frame_times[0] > 1.0:
            self._frame_times.popleft()
        fps = len(self._frame_times)
        self.fps_label.setText(f"FPS {fps}")
        self._activity_score = max(0.0, self._activity_score - 6.0)
        self.load_bar.setValue(int(self._activity_score))

    def append_line(self, message: str, kind: str = "system") -> None:
        color = _MONITOR_COLORS.get(kind, "#cccccc")
        cursor = self.console.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        cursor.insertText(message + "\n", fmt)

        self.console.setTextCursor(cursor)
        self.console.ensureCursorVisible()

    def log_system(self, message: str) -> None:
        self.append_line(message, "system")
