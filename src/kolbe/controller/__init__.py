"""Controller input package."""

from kolbe.controller.detector import (
    detect_controllers,
    has_dualsense_backend_available,
    has_dualshock4_backend_available,
)
from kolbe.controller.manager import ControllerManager
from kolbe.controller.multi_manager import MultiControllerManager
from kolbe.controller.slots import MAX_CONTROLLER_SLOTS, SlotRegistry, slot_id
from kolbe.controller.types import ControllerDevice, ControllerState, ControllerType, InputSource

__all__ = [
    "MAX_CONTROLLER_SLOTS",
    "ControllerDevice",
    "ControllerManager",
    "ControllerState",
    "ControllerType",
    "InputSource",
    "MultiControllerManager",
    "SlotRegistry",
    "detect_controllers",
    "has_dualsense_backend_available",
    "has_dualshock4_backend_available",
    "slot_id",
]
