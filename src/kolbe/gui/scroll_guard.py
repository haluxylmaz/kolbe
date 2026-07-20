"""Prevent mouse-wheel changes on unfocused spinboxes, comboboxes, and sliders."""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QObject
from PyQt6.QtWidgets import QApplication, QComboBox, QDoubleSpinBox, QSlider, QSpinBox


class ScrollFocusGuard(QObject):
    """Ignore wheel events on value widgets unless they have keyboard focus."""

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.Wheel:
            if isinstance(obj, (QComboBox, QSpinBox, QDoubleSpinBox, QSlider)):
                if not obj.hasFocus():
                    event.ignore()
                    return True
        return super().eventFilter(obj, event)


def install_scroll_focus_guard(app: QApplication) -> ScrollFocusGuard:
    guard = ScrollFocusGuard(app)
    app.installEventFilter(guard)
    return guard
