"""Kolbe package entry — crash-safe wrapper for frozen EXE launches."""

from __future__ import annotations

import sys


def _bootstrap() -> None:
    """Must run before any pydualsense / hidapi import."""
    try:
        from kolbe.hidapi_bootstrap import ensure_hidapi_loaded

        ensure_hidapi_loaded()
    except Exception:
        pass
    try:
        from kolbe.crash_report import install_excepthook

        install_excepthook()
    except Exception:
        pass


def _run() -> int:
    from kolbe.cli import main

    return int(main() or 0)


if __name__ == "__main__":
    _bootstrap()
    try:
        raise SystemExit(_run())
    except SystemExit:
        raise
    except BaseException as exc:
        try:
            from kolbe.crash_report import report_crash

            report_crash(exc)
        except Exception:
            # Last-ditch: never exit silently.
            import traceback
            from pathlib import Path

            tb = traceback.format_exc()
            try:
                Path.home().joinpath("Desktop", "kolbe_crash.log").write_text(tb, encoding="utf-8")
            except Exception:
                pass
            try:
                print(tb, file=sys.stderr)
                input("\nPress Enter to exit...")
            except Exception:
                pass
        raise SystemExit(1) from exc
