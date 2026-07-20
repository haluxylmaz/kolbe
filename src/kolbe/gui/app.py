"""PyQt6 application entry point."""

from __future__ import annotations

import logging
import sys

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from kolbe import APP_NAME
from kolbe.gui.main_window import MainWindow
from kolbe.gui.scroll_guard import install_scroll_focus_guard
from kolbe.gui.styles import DARK_STYLESHEET
from kolbe.paths import is_frozen, resource_path
from kolbe.utils.project_cleanup import cleanup_project

logger = logging.getLogger(__name__)


def _resolve_icon_path():
    """Locate icon.ico for source runs and frozen PyInstaller builds."""
    path = resource_path("icon.ico")
    return path if path.is_file() else None


def run_app() -> int:
    """Launch the Kolbe GUI."""
    from kolbe.crash_report import install_excepthook

    install_excepthook()

    if not is_frozen():
        removed = cleanup_project()
        if removed:
            logger.info("Startup cleanup removed %d junk path(s)", len(removed))

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("Kolbe")
    app.setStyleSheet(DARK_STYLESHEET)
    install_scroll_focus_guard(app)

    icon_path = _resolve_icon_path()
    if icon_path is not None:
        icon = QIcon(str(icon_path))
        app.setWindowIcon(icon)
    else:
        logger.debug("icon.ico not found — using default window icon")

    window = MainWindow()
    if icon_path is not None:
        window.setWindowIcon(QIcon(str(icon_path)))
    window.show()

    return app.exec()


if __name__ == "__main__":
    try:
        raise SystemExit(run_app())
    except SystemExit:
        raise
    except BaseException as exc:
        from kolbe.crash_report import report_crash

        report_crash(exc)
        raise SystemExit(1) from exc
