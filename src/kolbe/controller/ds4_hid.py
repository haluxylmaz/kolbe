"""DualShock 4 raw HID report parsing and device discovery."""

from __future__ import annotations

import logging
import struct
import time
import zlib
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from kolbe.controller.axis_utils import normalize_trigger_axis

logger = logging.getLogger(__name__)

SONY_VID = 0x054C

DS4_PRODUCT_IDS = frozenset(
    {
        0x05C4,  # DS4
        0x09CC,  # DS4 v2
        0x0BA0,  # Wireless adapter
    }
)

DUALSENSE_PRODUCT_IDS = frozenset(
    {
        0x0CE6,
        0x0DF2,
    }
)

DS4_TOUCHPAD_MAX_X = 1920
DS4_TOUCHPAD_MAX_Y = 943

PS_INPUT_CRC32_SEED = 0xA1
PS_OUTPUT_CRC32_SEED = 0xA2


class DS4ConnectionType(str, Enum):
    USB = "usb"
    BLUETOOTH = "bluetooth"


@dataclass
class DS4HidDeviceInfo:
    path: bytes
    product_id: int
    product_string: str
    connection_type: DS4ConnectionType


def has_hidapi() -> bool:
    """True when the ``hid`` module can load (DLL preloaded when possible)."""
    try:
        from kolbe.hidapi_bootstrap import ensure_hidapi_loaded

        ensure_hidapi_loaded()
        import hid  # noqa: F401

        return True
    except (ImportError, OSError):
        return False


def sony_product_id_from_guid(guid: Optional[str]) -> Optional[int]:
    """Extract USB product id from an SDL joystick GUID (LE bytes 8–9).

    Example DualSense: ``0300....4c050000e60c0000...`` → ``0x0CE6``.
    """
    if not guid:
        return None
    hex_str = guid.strip().lower().replace("-", "")
    if len(hex_str) < 20:
        return None
    try:
        # GUID bytes 8–9 are product id little-endian (chars 16–19).
        return int(hex_str[18:20] + hex_str[16:18], 16)
    except ValueError:
        return None


def is_dualsense_product(product_id: int) -> bool:
    return product_id in DUALSENSE_PRODUCT_IDS


def is_ds4_product(product_id: int) -> bool:
    return product_id in DS4_PRODUCT_IDS


def _ps_crc32(seed: int, data: bytes) -> int:
    crc = zlib.crc32(bytes([seed]), 0xFFFFFFFF)
    crc = zlib.crc32(data, crc)
    return (~crc) & 0xFFFFFFFF


def _parse_dpad(hat: int) -> tuple[bool, bool, bool, bool]:
    """Return up, down, left, right from DS4 hat nibble (0-8)."""
    if hat >= 8:
        return False, False, False, False
    up = hat in (0, 1, 7)
    right = hat in (1, 2, 3)
    down = hat in (3, 4, 5)
    left = hat in (5, 6, 7)
    return up, down, left, right


def _normalize_stick(value: int) -> float:
    return max(-1.0, min(1.0, (value - 128) / 128.0))


def _parse_touch_point(data: bytes, offset: int) -> tuple[bool, float, float, int]:
    if offset + 4 > len(data):
        return False, 0.0, 0.0, 0
    contact = data[offset]
    active = (contact & 0x80) == 0
    finger_id = contact & 0x7F
    if not active:
        # Ignore cleared X/Y on lift — tracker holds last known good position.
        return False, 0.0, 0.0, finger_id
    x_lo = data[offset + 1]
    x_hi_y_lo = data[offset + 2]
    y_hi = data[offset + 3]
    x = ((x_hi_y_lo & 0x0F) << 8) | x_lo
    y = (y_hi << 4) | ((x_hi_y_lo & 0xF0) >> 4)
    return (
        True,
        max(0.0, min(1.0, x / DS4_TOUCHPAD_MAX_X)),
        max(0.0, min(1.0, y / DS4_TOUCHPAD_MAX_Y)),
        finger_id,
    )


@dataclass
class ParsedDS4Report:
    buttons: dict[str, bool]
    axes: dict[str, float]
    gyro: dict[str, float]
    accelerometer: dict[str, float]
    touchpad: list[tuple[bool, float, float, int]]
    battery_percent: Optional[int] = None


def _report_common_offset(report: bytes) -> Optional[int]:
    if len(report) < 10:
        return None
    rid = report[0]
    if rid == 0x01 and len(report) >= 64:
        return 1
    if rid == 0x11 and len(report) >= 78:
        return 3
    if rid == 0x01 and len(report) == 10:
        return 1  # minimal BT — no motion/touch
    return None


def parse_ds4_input_report(report: bytes) -> Optional[ParsedDS4Report]:
    """Parse USB 0x01 or Bluetooth 0x11 DS4 input reports."""
    if not report:
        return None

    rid = report[0]
    if rid == 0x11 and len(report) >= 78:
        expected_crc = struct.unpack_from("<I", report, len(report) - 4)[0]
        if _ps_crc32(PS_INPUT_CRC32_SEED, report[:-4]) != expected_crc:
            logger.debug("DS4 BT input CRC mismatch — skipping report")
            return None

    off = _report_common_offset(report)
    if off is None or off + 32 > len(report):
        return None

    data = report
    lx, ly, rx, ry = data[off], data[off + 1], data[off + 2], data[off + 3]
    btn0, btn1, btn2 = data[off + 4], data[off + 5], data[off + 6]
    l2_analog, r2_analog = data[off + 7], data[off + 8]

    hat = btn0 & 0x0F
    dpad_up, dpad_down, dpad_left, dpad_right = _parse_dpad(hat)

    buttons = {
        "square": bool(btn0 & 0x10),
        "cross": bool(btn0 & 0x20),
        "circle": bool(btn0 & 0x40),
        "triangle": bool(btn0 & 0x80),
        "l1": bool(btn1 & 0x01),
        "r1": bool(btn1 & 0x02),
        "l2": bool(btn1 & 0x04),
        "r2": bool(btn1 & 0x08),
        "share": bool(btn1 & 0x10),
        "options": bool(btn1 & 0x20),
        "l3": bool(btn1 & 0x40),
        "r3": bool(btn1 & 0x80),
        "ps": bool(btn2 & 0x01),
        "touchpad_click": bool(btn2 & 0x02),
        "dpad_up": dpad_up,
        "dpad_down": dpad_down,
        "dpad_left": dpad_left,
        "dpad_right": dpad_right,
    }

    axes = {
        "left_stick_x": _normalize_stick(lx),
        "left_stick_y": _normalize_stick(ly),
        "right_stick_x": _normalize_stick(rx),
        "right_stick_y": _normalize_stick(ry),
        "l2": normalize_trigger_axis(l2_analog / 255.0, bipolar=False),
        "r2": normalize_trigger_axis(r2_analog / 255.0, bipolar=False),
    }

    gyro: dict[str, float] = {}
    accelerometer: dict[str, float] = {}
    if off + 24 <= len(data):
        gyro = {
            "gyro_pitch": float(struct.unpack_from("<h", data, off + 12)[0]),
            "gyro_yaw": float(struct.unpack_from("<h", data, off + 14)[0]),
            "gyro_roll": float(struct.unpack_from("<h", data, off + 16)[0]),
        }
        accelerometer = {
            "accel_x": float(struct.unpack_from("<h", data, off + 18)[0]),
            "accel_y": float(struct.unpack_from("<h", data, off + 20)[0]),
            "accel_z": float(struct.unpack_from("<h", data, off + 22)[0]),
        }

    touchpad: list[tuple[bool, float, float, int]] = []
    if rid in (0x01, 0x11) and len(data) >= off + 42:
        # First touch point in touch_reports[0] starts at common + 33 bytes
        touch_base = off + 33
        t0 = _parse_touch_point(data, touch_base)
        t1 = _parse_touch_point(data, touch_base + 4)
        touchpad = [t0, t1]

    if touchpad:
        if touchpad[0][0]:
            axes["touchpad_0_x"] = touchpad[0][1]
            axes["touchpad_0_y"] = touchpad[0][2]
        if len(touchpad) > 1 and touchpad[1][0]:
            axes["touchpad_1_x"] = touchpad[1][1]
            axes["touchpad_1_y"] = touchpad[1][2]

    battery_percent = None
    if off + 31 <= len(data):
        status = data[off + 30]
        level = status & 0x0F
        if level:
            battery_percent = min(level * 10 + 5, 100)

    return ParsedDS4Report(
        buttons=buttons,
        axes=axes,
        gyro=gyro,
        accelerometer=accelerometer,
        touchpad=touchpad,
        battery_percent=battery_percent,
    )


def find_ds4_hid_device(
    *,
    preferred_product_id: Optional[int] = None,
) -> Optional[DS4HidDeviceInfo]:
    """Locate a DualShock 4 HID interface, optionally matching a product id."""
    if not has_hidapi():
        return None
    import hid

    candidates: list[DS4HidDeviceInfo] = []
    for info in hid.enumerate(SONY_VID, 0):
        pid = info.get("product_id", 0)
        if pid not in DS4_PRODUCT_IDS:
            continue
        path = info.get("path")
        if not path:
            continue
        interface = info.get("interface_number", -1)
        # Prefer hidapi bus_type when present (1=USB, 2=Bluetooth).
        bus = info.get("bus_type")
        if bus == 2:
            conn = DS4ConnectionType.BLUETOOTH
        elif bus == 1:
            conn = DS4ConnectionType.USB
        elif isinstance(interface, int) and interface >= 0:
            conn = DS4ConnectionType.USB
        else:
            conn = DS4ConnectionType.BLUETOOTH
        product = info.get("product_string") or "DualShock 4"
        candidates.append(
            DS4HidDeviceInfo(
                path=path,
                product_id=pid,
                product_string=product,
                connection_type=conn,
            )
        )

    if not candidates:
        return None

    if preferred_product_id is not None:
        matched = [c for c in candidates if c.product_id == preferred_product_id]
        if matched:
            candidates = matched

    # Prefer USB (stable motion reports) then product / path for determinism.
    candidates.sort(
        key=lambda c: (
            c.connection_type != DS4ConnectionType.USB,
            c.product_id,
            c.path,
        )
    )
    return candidates[0]


def build_bt_enable_report() -> bytes:
    """Initial BT output report so the controller sends full 0x11 input (gyro/touch)."""
    report = bytearray(78)
    report[0] = 0x11
    report[1] = 0xC0
    report[2] = 0x20
    report[3] = 0xF3  # enable extension features
    report[4] = 0x04
    report[21] = 0x43
    report[22] = 0x43
    report[24] = 0x4D
    crc = _ps_crc32(PS_OUTPUT_CRC32_SEED, bytes(report[:-4]))
    struct.pack_into("<I", report, 74, crc)
    return bytes(report)


def build_usb_kick_report() -> bytes:
    """USB DS4 output report (LED/rumble init) — can wake input streaming on Windows."""
    report = bytearray(32)
    report[0] = 0x05
    report[1] = 0xFF  # enable flags
    return bytes(report)


def coerce_ds4_input_report(data: bytes) -> Optional[bytes]:
    """Normalize raw HID bytes into a parseable DS4 USB/BT input report."""
    if not data:
        return None
    raw = bytes(data)
    if raw[0] in (0x01, 0x11) and len(raw) >= 10:
        return raw
    # Windows HidD_GetInputReport sometimes prepends a 0x00 status byte.
    if len(raw) >= 11 and raw[0] == 0x00 and raw[1] in (0x01, 0x11):
        return raw[1:]
    return None


def _plausible_ds4_live_report(report: bytes) -> bool:
    """Reject descriptor-like get_input_report payloads that aren't live pad state."""
    if report[0] == 0x01 and len(report) >= 64:
        off = 1
    elif report[0] == 0x11 and len(report) >= 78:
        off = 3
    else:
        return False
    sticks = report[off : off + 4]
    # Resting / near-rest sticks sit around 0x80. Descriptor junk is often 00/01/03/05.
    near_center = sum(1 for value in sticks if 40 <= value <= 215) >= 3
    return near_center


def enable_ds4_input_streaming(hid_dev: object, connection_type: DS4ConnectionType) -> None:
    """Best-effort USB kick + BT feature enable so motion reports start flowing."""
    try:
        written = hid_dev.write(build_usb_kick_report())  # type: ignore[attr-defined]
        logger.debug("DS4 USB kick write returned %s", written)
        time.sleep(0.03)
    except OSError:
        logger.debug("DS4 USB kick write failed", exc_info=True)

    # Always attempt BT enable as well — some Windows stacks report USB bus_type
    # for Bluetooth DS4s that still need the 0x11 feature report.
    try:
        written = hid_dev.write(build_bt_enable_report())  # type: ignore[attr-defined]
        if written is not None and written < 0:
            logger.debug(
                "DS4 BT enable write returned %s (conn=%s)",
                written,
                connection_type.value,
            )
        time.sleep(0.05)
    except OSError:
        logger.debug("DS4 BT enable write failed", exc_info=True)


def read_ds4_hid_report(
    hid_dev: object,
    *,
    allow_get_input_report: bool = True,
) -> Optional[bytes]:
    """
    Read the newest DS4 input report.

    Prefer interrupt ``read()``. ``get_input_report`` is optional — the sensor
    companion must leave it off (passive share with SDL HIDAPI). The exclusive
    DualShock4Controller backend may enable it as a fallback.
    """
    latest: Optional[bytes] = None
    try:
        while True:
            chunk = hid_dev.read(128)  # type: ignore[attr-defined]
            if not chunk:
                break
            coerced = coerce_ds4_input_report(bytes(chunk))
            if coerced is not None:
                latest = coerced
    except OSError:
        logger.debug("DS4 HID interrupt read error", exc_info=True)

    if latest is not None:
        return latest

    if not allow_get_input_report:
        return None

    getter = getattr(hid_dev, "get_input_report", None)
    if not callable(getter):
        return None

    for report_id, size in ((0x01, 64), (0x01, 78), (0x11, 78), (0x11, 547)):
        try:
            raw = getter(report_id, size)
        except Exception:
            continue
        if not raw:
            continue
        coerced = coerce_ds4_input_report(bytes(raw))
        if coerced is None or not _plausible_ds4_live_report(coerced):
            continue
        if parse_ds4_input_report(coerced) is None:
            continue
        return coerced
    return None
