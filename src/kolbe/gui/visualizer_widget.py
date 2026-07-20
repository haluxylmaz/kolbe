"""Live gamepad visualizer — reference layout, stage-console palette."""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from kolbe.controller.types import ControllerState, ControllerType, ControllerDevice, InputSource
from kolbe.gui.styles import (
    COLOR_AMBER,
    COLOR_BG_SUBPANEL,
    COLOR_BORDER,
    COLOR_CYAN,
    COLOR_DIGITAL_ACTIVE,
    COLOR_IDLE,
    COLOR_IDLE_BORDER,
    COLOR_PINK,
    COLOR_STICK_DOT,
    COLOR_TEXT,
    COLOR_TEXT_DIM,
    COLOR_TEXT_MUTED,
    COLOR_TRIGGER_FILL,
)


def _btn(state: ControllerState, key: str) -> bool:
    return bool(state.buttons.get(key, False))


def _axis(state: ControllerState, key: str, default: float = 0.0) -> float:
    return float(state.axes.get(key, default))


def _mono_font(size: int, bold: bool = False) -> QFont:
    font = QFont("Menlo", size)
    font.setStyleHint(QFont.StyleHint.Monospace)
    if bold:
        font.setBold(True)
    return font


_PREVIEW_DEVICE = ControllerDevice(
    id="preview",
    name="Preview",
    controller_type=ControllerType.PLAYSTATION,
    backend="pygame",
)


class GamepadVisualizerWidget(QWidget):
    """Controller visualizer matching reference geometry with dark neon palette."""

    source_clicked = pyqtSignal(object)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._state: Optional[ControllerState] = None
        self._hit_regions: dict[InputSource, QRectF] = {}
        self._hover_source: Optional[InputSource] = None
        self._selected_source: Optional[InputSource] = None
        self._mapped_sources: set[InputSource] = set()
        self._mapping_labels: dict[InputSource, str] = {}
        self._accent = "#44FF88"
        self.setMinimumSize(420, 580)
        self.setMouseTracking(True)

    def set_accent_color(self, color: str) -> None:
        self._accent = color
        self.update()

    def set_mapped_sources(self, sources: set[InputSource]) -> None:
        self._mapped_sources = set(sources)
        self.update()

    def set_mapping_labels(self, labels: dict[InputSource, str]) -> None:
        self._mapping_labels = dict(labels)
        self.update()

    def set_selected_source(self, source: Optional[InputSource]) -> None:
        self._selected_source = source
        self.update()

    def _register_region(self, source: InputSource, rect: QRectF) -> None:
        self._hit_regions[source] = rect

    def _source_at(self, pos: QPointF) -> Optional[InputSource]:
        matches = [s for s, rect in self._hit_regions.items() if rect.contains(pos)]
        if not matches:
            return None
        if len(matches) == 1:
            return matches[0]
        return min(matches, key=lambda s: self._hit_regions[s].width() * self._hit_regions[s].height())

    def _draw_interaction_chrome(self, painter: QPainter, rect: QRectF, source: InputSource) -> None:
        mapped = source in self._mapped_sources
        selected = source == self._selected_source
        hover = source == self._hover_source

        if mapped:
            glow = QColor(self._accent)
            glow.setAlpha(70)
            painter.setPen(QPen(QColor(self._accent), 2.5))
            painter.setBrush(QBrush(glow))
            painter.drawRoundedRect(rect.adjusted(-2, -2, 2, 2), 4, 4)

        if selected or hover:
            color = QColor(self._accent if selected else COLOR_PINK)
            color.setAlpha(240 if selected else 200)
            painter.setPen(QPen(color, 3.2 if selected else 2.0))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(-3, -3, 3, 3), 4, 4)

        label = self._mapping_labels.get(source)
        if label:
            self._draw_mapping_label(painter, rect, label)

    def _draw_mapping_label(self, painter: QPainter, rect: QRectF, label: str) -> None:
        painter.setFont(_mono_font(8, bold=True))
        metrics = painter.fontMetrics()
        text_w = metrics.horizontalAdvance(label) + 8
        text_h = metrics.height() + 2
        badge = QRectF(
            rect.center().x() - text_w / 2,
            rect.bottom() - text_h - 1,
            text_w,
            text_h,
        )
        if badge.bottom() > rect.bottom() + 2:
            badge.moveTop(rect.top() + 1)
        bg = QColor("#0A0A0A")
        bg.setAlpha(210)
        painter.setPen(QPen(QColor(self._accent), 1))
        painter.setBrush(QBrush(bg))
        painter.drawRoundedRect(badge, 2, 2)
        painter.setPen(QColor("#FFFF66"))
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, label)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        source = self._source_at(event.position())
        if source != self._hover_source:
            self._hover_source = source
            self.setCursor(
                Qt.CursorShape.PointingHandCursor if source else Qt.CursorShape.ArrowCursor
            )
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover_source = None
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            source = self._source_at(event.position())
            if source is not None:
                self._selected_source = source
                self.source_clicked.emit(source)
                self.update()
        super().mousePressEvent(event)

    def update_state(self, state: ControllerState) -> None:
        self._state = state
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        margin = 12
        inner = QRectF(margin, margin, w - 2 * margin, h - 2 * margin - 8)
        self._hit_regions.clear()

        painter.fillRect(self.rect(), QColor("#181818"))
        painter.setPen(QPen(QColor(COLOR_BORDER), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(inner)

        if self._state is None:
            painter.setPen(QColor(COLOR_TEXT_DIM))
            painter.setFont(_mono_font(10))
            painter.drawText(
                QRectF(inner.left(), inner.top() + 4, inner.width(), 16),
                Qt.AlignmentFlag.AlignCenter,
                "Waiting for controller — layout is still clickable",
            )
            state = ControllerState(device=_PREVIEW_DEVICE)
        else:
            state = self._state

        self._draw_shoulders_row(painter, inner, state)
        self._draw_middle_row(painter, inner, state)
        self._draw_system_row(painter, inner, state)
        self._draw_sticks_row(painter, inner, state)
        self._draw_branding(painter, w, h)
        painter.end()

    def _draw_branding(self, painter: QPainter, w: int, h: int) -> None:
        painter.setPen(QColor(COLOR_TEXT_MUTED))
        painter.setFont(_mono_font(14, bold=True))
        painter.drawText(
            QRectF(0, h - 22, w, 18),
            Qt.AlignmentFlag.AlignCenter,
            "KOLBE",
        )

    def _draw_shoulders_row(self, painter: QPainter, inner: QRectF, state: ControllerState) -> None:
        row_h = inner.height() * 0.09
        y = inner.top() + 8
        gap = 6
        total_w = inner.width() - 16
        block_w = (total_w - 3 * gap) / 4
        x0 = inner.left() + 8

        specs = [
            ("L1", InputSource.L1.value, None, True),
            ("L2", InputSource.L2.value, InputSource.L2.value, False),
            ("R1", InputSource.R1.value, None, True),
            ("R2", InputSource.R2.value, InputSource.R2.value, False),
        ]

        for i, (label, btn_key, axis_key, is_digital) in enumerate(specs):
            rect = QRectF(x0 + i * (block_w + gap), y, block_w, row_h)
            source = InputSource.L1 if label == "L1" else InputSource.R1 if label == "R1" else InputSource.L2 if label == "L2" else InputSource.R2
            self._register_region(source, rect)
            if axis_key:
                value = _axis(state, axis_key)
                self._draw_trigger_block(painter, rect, label, value)
            else:
                self._draw_digital_block(painter, rect, label, _btn(state, btn_key))
            self._draw_interaction_chrome(painter, rect, source)

    def _draw_trigger_block(self, painter: QPainter, rect: QRectF, label: str, value: float) -> None:
        active = value > 0.01
        accent = self._accent
        bg = QColor(accent if active else COLOR_IDLE)
        bg.setAlpha(80 if active else 255)
        painter.setPen(QPen(QColor(accent if active else COLOR_IDLE_BORDER), 1.5 if active else 1))
        painter.setBrush(QBrush(bg if active else QColor(COLOR_IDLE)))
        painter.drawRoundedRect(rect, 3, 3)

        if active:
            fill_h = rect.height() * min(value, 1.0)
            fill = QRectF(rect.left(), rect.bottom() - fill_h, rect.width(), fill_h)
            fill_color = QColor(accent)
            fill_color.setAlpha(120)
            painter.setBrush(QBrush(fill_color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(fill, 3, 3)

        painter.setPen(QColor(accent if active else COLOR_TEXT))
        painter.setFont(_mono_font(9, bold=active))
        painter.drawText(rect.adjusted(0, 0, 0, -rect.height() * 0.35), Qt.AlignmentFlag.AlignCenter, label)
        painter.setFont(_mono_font(8))
        painter.drawText(
            rect.adjusted(0, rect.height() * 0.4, 0, 0),
            Qt.AlignmentFlag.AlignCenter,
            f"{value:.2f}",
        )

    def _draw_digital_block(self, painter: QPainter, rect: QRectF, label: str, active: bool) -> None:
        if active:
            painter.setPen(QPen(QColor(COLOR_PINK), 2))
            bg = QColor(COLOR_PINK)
            bg.setAlpha(200)
            painter.setBrush(QBrush(bg))
        else:
            painter.setPen(QPen(QColor(COLOR_IDLE_BORDER), 1))
            painter.setBrush(QBrush(QColor(COLOR_IDLE)))
        painter.drawRoundedRect(rect, 3, 3)
        painter.setPen(QColor("#121212" if active else COLOR_TEXT))
        painter.setFont(_mono_font(10, bold=active))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)

    def _draw_middle_row(self, painter: QPainter, inner: QRectF, state: ControllerState) -> None:
        top = inner.top() + inner.height() * 0.11
        row_h = inner.height() * 0.38
        pad_w = inner.width() * 0.36
        side_w = (inner.width() - pad_w - 24) / 2

        dpad_rect = QRectF(inner.left() + 8, top, side_w, row_h)
        pad_rect = QRectF(inner.left() + 8 + side_w + 8, top, pad_w, row_h * 0.72)
        face_rect = QRectF(pad_rect.right() + 8, top, side_w - 8, row_h)

        self._draw_dpad(painter, dpad_rect, state)
        self._draw_touchpad(painter, pad_rect, state)
        self._draw_face_buttons(painter, face_rect, state)

        finger_y = pad_rect.bottom() + 4
        finger_h = row_h * 0.28 - 8
        self._draw_finger_rows(painter, QRectF(pad_rect.left(), finger_y, pad_w, finger_h), state)

    def _draw_dpad(self, painter: QPainter, area: QRectF, state: ControllerState) -> None:
        painter.setPen(QColor(COLOR_TEXT_DIM))
        painter.setFont(_mono_font(8))
        painter.drawText(QRectF(area.left(), area.top(), area.width(), 14), Qt.AlignmentFlag.AlignCenter, "D-PAD")

        cx = area.center().x()
        cy = area.center().y() + 8
        size = min(area.width(), area.height()) * 0.18

        buttons = [
            (0, -1.2, "▲", InputSource.DPAD_UP.value),
            (0, 1.2, "▼", InputSource.DPAD_DOWN.value),
            (-1.2, 0, "◀", InputSource.DPAD_LEFT.value),
            (1.2, 0, "▶", InputSource.DPAD_RIGHT.value),
        ]
        for dx, dy, label, key in buttons:
            rect = QRectF(cx + dx * size - size / 2, cy + dy * size - size / 2, size, size)
            source = InputSource(key)
            self._register_region(source, rect)
            self._draw_digital_button(painter, rect, label, _btn(state, key), square=True)
            self._draw_interaction_chrome(painter, rect, source)

    def _draw_face_buttons(self, painter: QPainter, area: QRectF, state: ControllerState) -> None:
        painter.setPen(QColor(COLOR_TEXT_DIM))
        painter.setFont(_mono_font(8))
        painter.drawText(QRectF(area.left(), area.top(), area.width(), 14), Qt.AlignmentFlag.AlignCenter, "FACE")

        cx = area.center().x()
        cy = area.center().y() + 8
        size = min(area.width(), area.height()) * 0.2

        is_xbox = state.device.controller_type == ControllerType.XBOX
        if is_xbox:
            buttons = [(0, -1.15, "Y", InputSource.Y.value), (1.15, 0, "B", InputSource.B.value),
                       (-1.15, 0, "X", InputSource.X.value), (0, 1.15, "A", InputSource.A.value)]
        else:
            buttons = [(0, -1.15, "△", InputSource.TRIANGLE.value), (1.15, 0, "○", InputSource.CIRCLE.value),
                       (-1.15, 0, "□", InputSource.SQUARE.value), (0, 1.15, "×", InputSource.CROSS.value)]

        for dx, dy, label, key in buttons:
            rect = QRectF(cx + dx * size - size / 2, cy + dy * size - size / 2, size, size)
            source = InputSource(key)
            self._register_region(source, rect)
            self._draw_digital_button(painter, rect, label, _btn(state, key))
            self._draw_interaction_chrome(painter, rect, source)

    def _draw_digital_button(
        self, painter: QPainter, rect: QRectF, label: str, active: bool, square: bool = False
    ) -> None:
        if active:
            color = QColor(COLOR_DIGITAL_ACTIVE)
            color.setAlpha(220)
            painter.setPen(QPen(QColor(COLOR_PINK), 2))
            painter.setBrush(QBrush(color))
        else:
            painter.setPen(QPen(QColor(COLOR_IDLE_BORDER), 1))
            painter.setBrush(QBrush(QColor(COLOR_IDLE)))
        if square:
            painter.drawRoundedRect(rect, 4, 4)
        else:
            painter.drawEllipse(rect)
        painter.setPen(QColor("#121212" if active else COLOR_TEXT))
        painter.setFont(_mono_font(9 if len(label) <= 2 else 8, bold=active))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)

    def _draw_touchpad(self, painter: QPainter, rect: QRectF, state: ControllerState) -> None:
        click = _btn(state, InputSource.TOUCHPAD_CLICK.value)
        border = QColor(COLOR_AMBER if click else COLOR_IDLE_BORDER)
        painter.setPen(QPen(border, 2 if click else 1))
        painter.setBrush(QBrush(QColor(COLOR_BG_SUBPANEL)))

        grid_rect = rect.adjusted(0, 16, 0, 0)
        self._register_region(InputSource.TOUCHPAD_CLICK, grid_rect)
        painter.drawRect(grid_rect)

        # Grid lines
        painter.setPen(QPen(QColor("#333333"), 1))
        for i in range(1, 4):
            x = grid_rect.left() + grid_rect.width() * i / 4
            painter.drawLine(QPointF(x, grid_rect.top()), QPointF(x, grid_rect.bottom()))
        for i in range(1, 3):
            y = grid_rect.top() + grid_rect.height() * i / 3
            painter.drawLine(QPointF(grid_rect.left(), y), QPointF(grid_rect.right(), y))

        painter.setPen(QColor(COLOR_TEXT_DIM))
        painter.setFont(_mono_font(8))
        painter.drawText(rect.adjusted(0, 0, 0, -rect.height() + 14), Qt.AlignmentFlag.AlignCenter, "TOUCHPAD")

        for i, touch in enumerate(state.touchpad):
            if touch.active:
                tx = grid_rect.left() + touch.x * grid_rect.width()
                ty = grid_rect.top() + touch.y * grid_rect.height()
                painter.setPen(QPen(QColor(COLOR_AMBER), 2))
                painter.setBrush(QBrush(QColor(COLOR_AMBER)))
                painter.drawEllipse(QPointF(tx, ty), 10, 10)
                painter.setPen(QColor("#121212"))
                painter.setFont(_mono_font(8, bold=True))
                painter.drawText(QRectF(tx - 10, ty - 10, 20, 20), Qt.AlignmentFlag.AlignCenter, str(i + 1))

        self._draw_interaction_chrome(painter, grid_rect, InputSource.TOUCHPAD_CLICK)

    def _draw_finger_rows(self, painter: QPainter, rect: QRectF, state: ControllerState) -> None:
        row_h = rect.height() / 2
        finger_sources = [
            (InputSource.TOUCHPAD_0_X, InputSource.TOUCHPAD_0_Y),
            (InputSource.TOUCHPAD_1_X, InputSource.TOUCHPAD_1_Y),
        ]
        for i, touch in enumerate(state.touchpad[:2]):
            row = QRectF(rect.left(), rect.top() + i * row_h, rect.width(), row_h - 2)
            half_w = row.width() / 2
            x_rect = QRectF(row.left(), row.top(), half_w - 1, row.height())
            y_rect = QRectF(row.left() + half_w + 1, row.top(), half_w - 1, row.height())
            sx, sy = finger_sources[i]
            self._register_region(sx, x_rect)
            self._register_region(sy, y_rect)
            painter.setPen(QPen(QColor(COLOR_BORDER), 1))
            painter.setBrush(QBrush(QColor(COLOR_IDLE)))
            painter.drawRect(row)

            dot_color = QColor(COLOR_AMBER) if touch.active else QColor("#333333")
            painter.setBrush(QBrush(dot_color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(row.left() + 10, row.center().y()), 4, 4)

            painter.setPen(QColor(COLOR_AMBER if touch.active else COLOR_TEXT_DIM))
            painter.setFont(_mono_font(8))
            if touch.active:
                text = f"Finger {i + 1}   X:{touch.x:.2f}   Y:{touch.y:.2f}"
            else:
                text = f"Finger {i + 1}   —"
            painter.drawText(row.adjusted(22, 0, -4, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
            self._draw_interaction_chrome(painter, x_rect, sx)
            self._draw_interaction_chrome(painter, y_rect, sy)

    def _draw_system_row(self, painter: QPainter, inner: QRectF, state: ControllerState) -> None:
        y = inner.top() + inner.height() * 0.52
        h = inner.height() * 0.05
        labels = [
            ("Select", InputSource.SHARE),
            ("Home", InputSource.PS),
            ("Cancel", InputSource.OPTIONS),
        ]
        total_w = inner.width() * 0.5
        bw = total_w / 3 - 4
        x0 = inner.center().x() - total_w / 2

        for i, (label, source) in enumerate(labels):
            rect = QRectF(x0 + i * (bw + 6), y, bw, h)
            self._register_region(source, rect)
            active = _btn(state, source.value)
            if active:
                painter.setPen(QPen(QColor(COLOR_AMBER), 1.5))
                painter.setBrush(QBrush(QColor(COLOR_AMBER)))
                bg = QColor(COLOR_AMBER)
                bg.setAlpha(160)
                painter.setBrush(QBrush(bg))
            else:
                painter.setPen(QPen(QColor(COLOR_IDLE_BORDER), 1))
                painter.setBrush(QBrush(QColor(COLOR_IDLE)))
            painter.drawRoundedRect(rect, 3, 3)
            painter.setPen(QColor("#121212" if active else COLOR_TEXT_DIM))
            painter.setFont(_mono_font(8))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)
            self._draw_interaction_chrome(painter, rect, source)

    def _draw_sticks_row(self, painter: QPainter, inner: QRectF, state: ControllerState) -> None:
        top = inner.top() + inner.height() * 0.60
        h = inner.height() * 0.36
        radius = min(inner.width() * 0.14, h * 0.42)

        sticks = [
            (inner.left() + inner.width() * 0.18, top + h / 2, InputSource.LEFT_STICK_X.value,
             InputSource.LEFT_STICK_Y.value, InputSource.L3.value, "LEFT STICK"),
            (inner.right() - inner.width() * 0.18, top + h / 2, InputSource.RIGHT_STICK_X.value,
             InputSource.RIGHT_STICK_Y.value, InputSource.R3.value, "RIGHT STICK"),
        ]

        for cx, cy, kx, ky, k_click, title in sticks:
            center = QPointF(cx, cy)
            outer = QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2)
            x_source = InputSource(kx)
            y_source = InputSource(ky)
            click_source = InputSource(k_click)
            x_rect = QRectF(outer.left(), outer.top(), outer.width() / 2, outer.height())
            y_rect = QRectF(outer.center().x(), outer.top(), outer.width() / 2, outer.height())
            click_rect = QRectF(
                center.x() - radius * 0.25,
                center.y() - radius * 0.25,
                radius * 0.5,
                radius * 0.5,
            )
            self._register_region(x_source, x_rect)
            self._register_region(y_source, y_rect)
            self._register_region(click_source, click_rect)

            painter.setPen(QPen(QColor(COLOR_IDLE_BORDER), 2))
            painter.setBrush(QBrush(QColor(COLOR_BG_SUBPANEL)))
            painter.drawEllipse(outer)

            # Crosshair
            painter.setPen(QPen(QColor("#444444"), 1))
            painter.drawLine(QPointF(center.x(), outer.top()), QPointF(center.x(), outer.bottom()))
            painter.drawLine(QPointF(outer.left(), center.y()), QPointF(outer.right(), center.y()))

            x_val = _axis(state, kx)
            y_val = _axis(state, ky)
            dot_x = center.x() + x_val * radius * 0.82
            dot_y = center.y() + y_val * radius * 0.82

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(self._accent)))
            painter.drawEllipse(QPointF(dot_x, dot_y), radius * 0.12, radius * 0.12)

            if _btn(state, k_click):
                painter.setPen(QPen(QColor(self._accent), 2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(outer.adjusted(2, 2, -2, -2))

            painter.setPen(QColor(COLOR_TEXT_DIM))
            painter.setFont(_mono_font(7))
            painter.drawText(QRectF(outer.left() - 20, outer.top() - 16, outer.width() + 40, 14),
                             Qt.AlignmentFlag.AlignCenter, title)
            painter.setPen(QColor(self._accent))
            painter.drawText(
                QRectF(outer.left() - 10, outer.bottom() + 4, outer.width() + 20, 14),
                Qt.AlignmentFlag.AlignCenter,
                f"X:{x_val:+.2f}  Y:{y_val:+.2f}",
            )
            btn_active = _btn(state, k_click)
            painter.setPen(QColor(self._accent if btn_active else COLOR_TEXT_MUTED))
            painter.drawText(
                QRectF(outer.left(), outer.bottom() + 18, outer.width(), 12),
                Qt.AlignmentFlag.AlignCenter,
                f"Button: {'ON' if btn_active else 'off'}",
            )
            self._draw_interaction_chrome(painter, x_rect, x_source)
            self._draw_interaction_chrome(painter, y_rect, y_source)
            self._draw_interaction_chrome(painter, click_rect, click_source)


class SensorAxisRow(QFrame):
    """Single axis readout row — label, value, progress bar."""

    clicked = pyqtSignal(object)

    def __init__(
        self,
        axis_label: str,
        source: InputSource,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._source = source
        self.setObjectName("sensorAxisRow")
        self.setMinimumHeight(28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            "QFrame#sensorAxisRow { background: #1a1a1a; border: 1px solid #333; border-radius: 3px; }"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        self.axis_label = QLabel(axis_label)
        self.axis_label.setFixedWidth(14)
        self.axis_label.setStyleSheet("color: #ffaa00; font-weight: 700; font-size: 10px;")
        layout.addWidget(self.axis_label)

        self.value_label = QLabel("+0")
        self.value_label.setMinimumWidth(52)
        self.value_label.setStyleSheet("color: #e8eaed; font-family: monospace; font-size: 10px;")
        layout.addWidget(self.value_label)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        self.bar.setStyleSheet(
            "QProgressBar { background: #0a0a0a; border: 1px solid #333; border-radius: 2px; }"
            "QProgressBar::chunk { background: #ffaa00; border-radius: 2px; }"
        )
        layout.addWidget(self.bar, stretch=1)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._source)
        super().mousePressEvent(event)

    def update_value(self, value: float, enabled: bool) -> None:
        self.value_label.setText(f"{value:+.0f}" if enabled else "—")
        norm = min(abs(value) / 2000.0, 1.0) if enabled else 0.0
        self.bar.setValue(int(norm * 100))
        color = "#ffaa00" if enabled else "#555555"
        self.value_label.setStyleSheet(f"color: {color}; font-family: monospace; font-size: 10px;")


class SensorGroupWidget(QFrame):
    """Gyroscope or accelerometer group with stacked axis rows."""

    source_clicked = pyqtSignal(object)

    def __init__(self, title: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("sensorGroup")
        self.setMinimumHeight(110)
        self.setStyleSheet(
            "QFrame#sensorGroup { background: #141414; border: 1px solid #444; border-radius: 4px; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        header = QLabel(title)
        header.setStyleSheet("color: #ffaa00; font-weight: 700; font-size: 10px; letter-spacing: 0.08em;")
        layout.addWidget(header)

        self._rows: list[SensorAxisRow] = []
        self._enabled_label = QLabel("Enabled: no")
        self._enabled_label.setStyleSheet("color: #666; font-size: 9px;")
        layout.addWidget(self._enabled_label)

    def set_axes(self, axes: list[tuple[str, InputSource]]) -> None:
        layout = self.layout()
        for row in self._rows:
            layout.removeWidget(row)
            row.deleteLater()
        self._rows.clear()
        for axis_label, source in axes:
            row = SensorAxisRow(axis_label, source, self)
            row.clicked.connect(self.source_clicked.emit)
            layout.insertWidget(layout.count() - 1, row)
            self._rows.append(row)

    def update_values(self, values: dict[str, float], enabled: bool) -> None:
        self._enabled_label.setText(f"Enabled: {'yes' if enabled else 'no'}")
        self._enabled_label.setStyleSheet(
            f"color: {'#ffaa00' if enabled else '#666'}; font-size: 9px;"
        )
        for row in self._rows:
            key = row._source.value
            row.update_value(values.get(key, 0.0), enabled)


class VisualizerPanel(QWidget):
    """Left panel — interactive controller visualizer."""

    source_clicked = pyqtSignal(object)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("panel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        title = QLabel("CONTROLLER INPUT")
        title.setObjectName("sectionTitle")
        self._title_label = title
        layout.addWidget(title)

        hint = QLabel("Click any control to edit its MIDI mapping")
        hint.setStyleSheet("color: #8b93a7; font-size: 10px;")
        layout.addWidget(hint)

        self.visualizer = GamepadVisualizerWidget()
        self.visualizer.source_clicked.connect(self.source_clicked.emit)
        layout.addWidget(self.visualizer, stretch=1)

        toggle_row = QHBoxLayout()
        toggle_row.setContentsMargins(0, 0, 0, 0)
        self.sensor_toggle = QPushButton("▸  Sensors")
        self.sensor_toggle.setCheckable(True)
        self.sensor_toggle.setChecked(False)
        self.sensor_toggle.setToolTip("Show gyroscope and accelerometer readouts")
        self.sensor_toggle.setStyleSheet(
            "QPushButton { color: #8b93a7; border: 1px solid #333; border-radius: 3px; padding: 3px 10px; }"
            "QPushButton:checked { color: #ffaa00; border-color: #ffaa00; }"
            "QPushButton:hover { color: #e8eaed; }"
        )
        self.sensor_toggle.toggled.connect(self._toggle_sensors)
        toggle_row.addWidget(self.sensor_toggle)
        toggle_row.addStretch()
        layout.addLayout(toggle_row)

        self.sensor_container = QWidget()
        sensor_outer = QVBoxLayout(self.sensor_container)
        sensor_outer.setContentsMargins(0, 0, 0, 0)
        sensor_row = QHBoxLayout()
        sensor_row.setSpacing(8)
        self.gyro_group = SensorGroupWidget("GYROSCOPE")
        self.gyro_group.set_axes([
            ("X", InputSource.GYRO_PITCH),
            ("Y", InputSource.GYRO_YAW),
            ("Z", InputSource.GYRO_ROLL),
        ])
        self.gyro_group.source_clicked.connect(self.source_clicked.emit)
        self.accel_group = SensorGroupWidget("ACCELEROMETER")
        self.accel_group.set_axes([
            ("X", InputSource.ACCEL_X),
            ("Y", InputSource.ACCEL_Y),
            ("Z", InputSource.ACCEL_Z),
        ])
        self.accel_group.source_clicked.connect(self.source_clicked.emit)
        sensor_row.addWidget(self.gyro_group, stretch=1)
        sensor_row.addWidget(self.accel_group, stretch=1)
        sensor_outer.addLayout(sensor_row)
        self.sensor_container.setVisible(False)
        layout.addWidget(self.sensor_container)

    def _toggle_sensors(self, expanded: bool) -> None:
        self.sensor_container.setVisible(expanded)
        self.sensor_toggle.setText("▾  Sensors" if expanded else "▸  Sensors")

    def update_state(self, state: ControllerState) -> None:
        self.visualizer.update_state(state)
        gyro = state.gyro or {}
        accel = state.accelerometer or {}
        self.gyro_group.update_values(gyro, bool(gyro))
        self.accel_group.update_values(accel, bool(accel))

    def set_mapped_sources(self, sources: set[InputSource]) -> None:
        self.visualizer.set_mapped_sources(sources)

    def set_mapping_labels(self, labels: dict[InputSource, str]) -> None:
        self.visualizer.set_mapping_labels(labels)

    def set_accent_color(self, color: str) -> None:
        self.visualizer.set_accent_color(color)
        self._title_label.setStyleSheet(
            f"color: {color}; font-size: 13px; font-weight: 700; letter-spacing: 0.12em;"
        )

    def set_selected_source(self, source: Optional[InputSource]) -> None:
        self.visualizer.set_selected_source(source)
