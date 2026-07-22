"""SDL / pygame joystick hints — must run before pygame.init().

Architecture (Windows PlayStation multi-pad):
  - SDL HIDAPI STAYS ON so DualSense/DS4 face buttons, D-Pad, and triggers
    map correctly (DirectInput scrambles that layout).
  - The PlayStation sensor companion opens the same HID path READ-ONLY and
    never sends feature/output reports. Writes collide with SDL and cause the
    Windows USB connect/disconnect ("blüp blüp") loop.
"""

from __future__ import annotations

import logging
import os
import sys

logger = logging.getLogger(__name__)

_APPLIED = False

# Force-assign so stale shell env from earlier experiments cannot win.
_WINDOWS_JOYSTICK_HINTS: dict[str, str] = {
    # REQUIRED: native Sony HIDAPI layout for correct buttons / D-Pad / triggers.
    "SDL_JOYSTICK_HIDAPI": "1",
    "SDL_JOYSTICK_HIDAPI_PS4": "1",
    "SDL_JOYSTICK_HIDAPI_PS5": "1",
    # Leave rumble off — output reports from SDL can also disturb shared HID.
    "SDL_JOYSTICK_HIDAPI_PS4_RUMBLE": "0",
    "SDL_JOYSTICK_HIDAPI_PS5_RUMBLE": "0",
    # Forbidden for PS pads: DirectInput remaps buttons incorrectly.
    "SDL_JOYSTICK_DIRECTINPUT": "0",
    "SDL_DIRECTINPUT_ENABLED": "0",
    "SDL_JOYSTICK_RAWINPUT": "0",
    "SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS": "1",
}


def apply_joystick_hints(*, force: bool = False) -> None:
    """Install process-wide SDL joystick hints (idempotent, pre-pygame.init)."""
    global _APPLIED
    if _APPLIED and not force:
        return
    _APPLIED = True

    # Always prefer HIDAPI for PlayStation button fidelity on every platform.
    for key in (
        "SDL_JOYSTICK_HIDAPI",
        "SDL_JOYSTICK_HIDAPI_PS4",
        "SDL_JOYSTICK_HIDAPI_PS5",
    ):
        os.environ[key] = "1"
    for key in (
        "SDL_JOYSTICK_HIDAPI_PS4_RUMBLE",
        "SDL_JOYSTICK_HIDAPI_PS5_RUMBLE",
    ):
        os.environ[key] = "0"

    if sys.platform == "win32":
        for key, value in _WINDOWS_JOYSTICK_HINTS.items():
            os.environ[key] = value
    else:
        os.environ.setdefault("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1")

    try:
        from pygame._sdl2 import sdl2 as _sdl2  # type: ignore

        setter = getattr(_sdl2, "SDL_SetHint", None) or getattr(_sdl2, "set_hint", None)
        if callable(setter):
            hints = (
                _WINDOWS_JOYSTICK_HINTS
                if sys.platform == "win32"
                else {
                    "SDL_JOYSTICK_HIDAPI": "1",
                    "SDL_JOYSTICK_HIDAPI_PS4": "1",
                    "SDL_JOYSTICK_HIDAPI_PS5": "1",
                    "SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS": "1",
                }
            )
            for key, value in hints.items():
                try:
                    setter(key.encode("utf-8"), value.encode("utf-8"))
                except Exception:
                    try:
                        setter(key, value)
                    except Exception:
                        pass
    except Exception:
        logger.debug("Could not push SDL_SetHint via pygame._sdl2", exc_info=True)

    logger.info(
        "SDL joystick hints applied (HIDAPI=on, DirectInput=off) — "
        "correct PS button maps; companion stays read-only for sensors"
    )
