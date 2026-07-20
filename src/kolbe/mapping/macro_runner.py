"""QTimer-based macro sequence runner."""

from __future__ import annotations

from typing import Callable, Optional

from PyQt6.QtCore import QObject, QTimer

from kolbe.mapping.models import MacroActionType, MacroStep


class MacroRunner(QObject):
    """Executes macro steps sequentially without blocking the GUI thread."""

    def __init__(
        self,
        execute_step: Callable[[MacroStep], None],
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._execute_step = execute_step
        self._steps: list[MacroStep] = []
        self._index = 0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._advance)

    def is_running(self) -> bool:
        return self._index < len(self._steps) or self._timer.isActive()

    def start(self, steps: list[MacroStep]) -> None:
        self.stop()
        self._steps = list(steps)
        self._index = 0
        self._advance()

    def stop(self) -> None:
        self._timer.stop()
        self._steps = []
        self._index = 0

    def _advance(self) -> None:
        if self._index >= len(self._steps):
            return

        step = self._steps[self._index]
        self._index += 1

        if step.action == MacroActionType.DELAY:
            delay = max(0, step.delay_ms)
            if delay > 0:
                self._timer.start(delay)
            else:
                self._advance()
            return

        self._execute_step(step)
        delay = max(0, step.delay_ms)
        if delay > 0:
            self._timer.start(delay)
        else:
            self._advance()
