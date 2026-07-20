"""Controller detection and enumeration."""

from __future__ import annotations

import logging
import re

import pygame

from kolbe.controller.ds4_hid import find_ds4_hid_device, has_hidapi
from kolbe.controller.types import ControllerDevice, ControllerType

logger = logging.getLogger(__name__)

_DUALSENSE_PATTERNS = (
    r"dualsense",
    r"dual\s*sense",
    r"wireless\s*controller",
    r"ps5",
)
_XBOX_PATTERNS = (
    r"xbox",
    r"xinput",
    r"microsoft",
)
_PLAYSTATION_PATTERNS = (
    r"dualshock",
    r"playstation",
    r"ps4",
    r"ps4 controller",
    r"sony",
)
_DS4_NAME_PATTERNS = (
    r"ps4",
    r"dualshock",
    r"wireless controller",
)


def _classify_controller(name: str, guid: str = "", ds4_hid_present: bool = False) -> ControllerType:
    combined = f"{name} {guid}".lower()
    if ds4_hid_present and "controller" in combined:
        return ControllerType.PLAYSTATION
    if any(re.search(p, combined) for p in _DUALSENSE_PATTERNS):
        # PS4 "Wireless Controller" must not match PS5 dualsense heuristic alone
        if "ps4" in combined or "dualshock" in combined:
            return ControllerType.PLAYSTATION
        if "dualsense" in combined or "ps5" in combined:
            return ControllerType.DUALSENSE
    if any(re.search(p, combined) for p in _XBOX_PATTERNS):
        return ControllerType.XBOX
    if any(re.search(p, combined) for p in _PLAYSTATION_PATTERNS):
        return ControllerType.PLAYSTATION
    return ControllerType.GENERIC


def _is_dualsense(device: ControllerDevice) -> bool:
    return device.controller_type == ControllerType.DUALSENSE


def _is_ds4_candidate(name: str, controller_type: ControllerType) -> bool:
    if controller_type != ControllerType.PLAYSTATION:
        return False
    lower = name.lower()
    return any(re.search(p, lower) for p in _DS4_NAME_PATTERNS) or "controller" in lower


def _resolve_backend(name: str, controller_type: ControllerType) -> str:
    if _is_dualsense(
        ControllerDevice(id="", name=name, controller_type=controller_type, backend="pygame")
    ):
        if has_dualsense_backend_available():
            return "dualsense"
    if _is_ds4_candidate(name, controller_type) and has_hidapi() and find_ds4_hid_device():
        return "dualshock4"
    return "pygame"


def detect_controllers() -> list[ControllerDevice]:
    """Enumerate connected gamepads. Releases pygame handles after probing."""
    if not pygame.get_init():
        pygame.init()
    if not pygame.joystick.get_init():
        pygame.joystick.init()

    devices: list[ControllerDevice] = []
    count = pygame.joystick.get_count()
    ds4_hid_present = find_ds4_hid_device() is not None

    for index in range(count):
        joy = pygame.joystick.Joystick(index)
        joy.init()
        try:
            name = joy.get_name()
            guid = joy.get_guid() if hasattr(joy, "get_guid") else ""
            controller_type = _classify_controller(name, guid, ds4_hid_present=ds4_hid_present)
            backend = _resolve_backend(name, controller_type)

            devices.append(
                ControllerDevice(
                    id=f"pygame-{index}",
                    name=name,
                    controller_type=controller_type,
                    backend=backend,
                    pygame_index=index,
                    guid=guid or None,
                    num_buttons=joy.get_numbuttons(),
                    num_axes=joy.get_numaxes(),
                    num_hats=joy.get_numhats(),
                )
            )
            logger.debug(
                "Detected controller [%d]: %s (%s, backend=%s)",
                index,
                name,
                controller_type.value,
                backend,
            )
        finally:
            # Release SDL handle so HID backends can claim the device (critical on macOS).
            joy.quit()

    return devices


def has_dualsense_backend_available() -> bool:
    """Check if pydualsense (and its hidapi.dll) can be imported."""
    try:
        from kolbe.hidapi_bootstrap import ensure_hidapi_loaded

        ensure_hidapi_loaded()
        import pydualsense  # noqa: F401

        return True
    except (ImportError, OSError) as exc:
        # OSError: ``Could not find any hidapi library`` when the DLL is missing.
        logger.debug("DualSense backend unavailable: %s", exc)
        return False


def has_dualshock4_backend_available() -> bool:
    """Check if DS4 HID backend can run."""
    return has_hidapi() and find_ds4_hid_device() is not None
