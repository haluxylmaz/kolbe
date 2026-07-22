"""Kolbe package entry — crash-safe wrapper for frozen EXE launches."""

from __future__ import annotations

# MUST be first: SDL HIDAPI ON before any pygame/SDL import.
# DirectInput is forbidden — it scrambles PlayStation D-Pad / face buttons.
import os

os.environ["SDL_JOYSTICK_HIDAPI"] = "1"
os.environ["SDL_JOYSTICK_HIDAPI_PS4"] = "1"
os.environ["SDL_JOYSTICK_HIDAPI_PS5"] = "1"
os.environ["SDL_JOYSTICK_HIDAPI_PS4_RUMBLE"] = "0"
os.environ["SDL_JOYSTICK_HIDAPI_PS5_RUMBLE"] = "0"
os.environ["SDL_JOYSTICK_DIRECTINPUT"] = "0"
os.environ["SDL_DIRECTINPUT_ENABLED"] = "0"
os.environ["SDL_JOYSTICK_RAWINPUT"] = "0"

import sys


def _bootstrap() -> None:
    """Must run before any pygame / pydualsense / hidapi import."""
    try:
        from kolbe.sdl_bootstrap import apply_joystick_hints

        apply_joystick_hints(force=True)
    except Exception:
        pass
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
    try:
        import atexit

        from kolbe.controller.hid_lifecycle import force_close_all_hid_handles

        atexit.register(force_close_all_hid_handles)
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
