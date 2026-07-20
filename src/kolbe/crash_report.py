"""Crash reporting for packaged (windowed) Windows builds."""

from __future__ import annotations

import sys
import traceback
from pathlib import Path


def crash_log_path() -> Path:
    from kolbe.paths import app_dir, is_frozen

    if getattr(sys, "frozen", False) or is_frozen():
        return app_dir() / "kolbe_crash.log"
    return Path.cwd() / "kolbe_crash.log"


def write_crash_report(exc: BaseException | None = None) -> Path:
    """Write full traceback to disk; return the log path used."""
    tb = traceback.format_exc()
    path = crash_log_path()
    text = tb if tb.strip() != "NoneType: None" else (f"{type(exc).__name__}: {exc}\n" if exc else "Unknown error\n")
    try:
        path.write_text(text, encoding="utf-8")
        return path
    except OSError:
        fallback = Path.home() / "Desktop" / "kolbe_crash.log"
        try:
            fallback.write_text(text, encoding="utf-8")
            return fallback
        except OSError:
            return path


def report_crash(exc: BaseException) -> None:
    """Log crash, try a message box, and optionally wait for Enter on a console."""
    path = write_crash_report(exc)
    message = f"{type(exc).__name__}: {exc}\n\nFull traceback saved to:\n{path}"
    try:
        print(traceback.format_exc(), file=sys.stderr)
        print(f"\nCrash log written to: {path}", file=sys.stderr)
    except Exception:
        pass

    _try_message_box("Kolbe crashed", message)
    _wait_for_enter()


def install_excepthook() -> None:
    """Install a global hook so uncaught errors also write a crash log."""

    def _hook(exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        try:
            text = "".join(traceback.format_exception(exc_type, exc, tb))
            path = crash_log_path()
            path.write_text(text, encoding="utf-8")
            print(text, file=sys.stderr)
            print(f"Crash log written to: {path}", file=sys.stderr)
            _try_message_box("Kolbe crashed", f"{exc_type.__name__}: {exc}\n\n{path}")
            _wait_for_enter()
        except Exception:
            pass

    sys.excepthook = _hook


def _try_message_box(title: str, message: str) -> None:
    try:
        from PyQt6.QtWidgets import QApplication, QMessageBox

        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)
        QMessageBox.critical(None, title, message)
        return
    except Exception:
        pass

    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)
    except Exception:
        pass


def _wait_for_enter() -> None:
    try:
        if sys.stdin is not None and sys.stdin.isatty():
            input("\nPress Enter to exit...")
            return
    except Exception:
        pass
    try:
        import time

        time.sleep(2)
    except Exception:
        pass
