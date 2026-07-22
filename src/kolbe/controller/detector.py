"""Controller detection and enumeration."""

from __future__ import annotations

import logging
import re
from typing import Optional

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


def make_hardware_id(guid: str, name: str, index: int) -> str:
    """Stable-ish hardware id (prefer SDL GUID over pygame index)."""
    cleaned = (guid or "").strip()
    if cleaned:
        return f"guid:{cleaned}"
    safe_name = (name or "controller").strip() or "controller"
    return f"name:{safe_name}|idx:{index}"


def _classify_controller(name: str, guid: str = "", ds4_hid_present: bool = False) -> ControllerType:
    combined = f"{name} {guid}".lower()
    if ds4_hid_present and "controller" in combined:
        return ControllerType.PLAYSTATION
    if any(re.search(p, combined) for p in _DUALSENSE_PATTERNS):
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


def detect_controllers(
    *,
    release_after_probe: bool = False,
    keep_open_indices: Optional[set[int]] = None,
) -> list[ControllerDevice]:
    """
    Enumerate connected gamepads.

    ``release_after_probe=False`` (default) leaves joysticks initialized so
    already-open multi-controller pygame backends are not torn down mid-session.
    Pass ``keep_open_indices`` to never quit those SDL indices even when releasing.
    """
    if not pygame.get_init():
        pygame.init()
    if not pygame.joystick.get_init():
        pygame.joystick.init()

    devices: list[ControllerDevice] = []
    count = pygame.joystick.get_count()
    ds4_hid_present = find_ds4_hid_device() is not None
    protected = keep_open_indices or set()

    for index in range(count):
        joy = pygame.joystick.Joystick(index)
        joy.init()
        try:
            name = joy.get_name()
            guid = joy.get_guid() if hasattr(joy, "get_guid") else ""
            instance_id = None
            if hasattr(joy, "get_instance_id"):
                try:
                    instance_id = int(joy.get_instance_id())
                except Exception:
                    instance_id = None
            controller_type = _classify_controller(name, guid, ds4_hid_present=ds4_hid_present)
            backend = _resolve_backend(name, controller_type)
            hardware_id = make_hardware_id(guid, name, index)

            devices.append(
                ControllerDevice(
                    id=hardware_id,
                    name=name,
                    controller_type=controller_type,
                    backend=backend,
                    pygame_index=index,
                    guid=guid or None,
                    instance_id=instance_id,
                    num_buttons=joy.get_numbuttons(),
                    num_axes=joy.get_numaxes(),
                    num_hats=joy.get_numhats(),
                )
            )
            logger.debug(
                "Detected controller [%d]: %s (%s, backend=%s, id=%s)",
                index,
                name,
                controller_type.value,
                backend,
                hardware_id,
            )
        finally:
            # Never quit indices owned by live pygame backends.
            if release_after_probe and index not in protected:
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
        logger.debug("DualSense backend unavailable: %s", exc)
        return False


def has_dualshock4_backend_available() -> bool:
    """Check if DS4 HID backend can run."""
    return has_hidapi() and find_ds4_hid_device() is not None
