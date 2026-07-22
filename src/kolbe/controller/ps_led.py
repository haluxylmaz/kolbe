"""Safe PlayStation lightbar / LED output reports.

Only builds clean LED payloads — never DS4 enhanced-mode enables (0x11 feature
kick), never DualSense init/setup sequences that reset firmware or provoke
Windows USB hotplug storms. Callers must treat writes as best-effort and
non-blocking.

---------------------------------------------------------------------------
TUNE SLOT COLORS HERE
---------------------------------------------------------------------------
Edit ``SLOT_LED_RGB`` (slot number → R,G,B). Optional per-hardware channel
gains below compensate for DualSense vs DS4 lightbar mixing without changing
the theme dictionary.
"""

from __future__ import annotations

import logging
import struct
import zlib
from typing import Mapping

from kolbe.controller.ds4_hid import DS4ConnectionType, PS_OUTPUT_CRC32_SEED

logger = logging.getLogger(__name__)

# =============================================================================
# Slot lightbar theme — tweak these tuples to retune physical LED colors.
# Values are "design intent" RGB; hardware gains below refine the look.
# =============================================================================
SLOT_LED_RGB: dict[int, tuple[int, int, int]] = {
    1: (0, 220, 255),    # Cyan — slightly less green bleed on DS4
    2: (255, 40, 110),   # Magenta / pink — more red so it doesn't read purple
    3: (255, 150, 16),   # Orange / yellow — warm, not muddy brown
    4: (36, 230, 96),    # Green — boosted G (both pads render green dimly)
}

# Channel gains applied at write-time (R, G, B multipliers). Keep near 1.0.
# DualSense lightbars are relatively linear; DS4 under-drives green / over-blues.
_DUALSENSE_CHANNEL_GAIN: tuple[float, float, float] = (1.00, 1.00, 1.00)
_DS4_CHANNEL_GAIN: tuple[float, float, float] = (1.05, 1.20, 0.88)


def led_rgb_for_slot(slot: int) -> tuple[int, int, int]:
    """Return the theme RGB for a slot (1–4), falling back to slot 1."""
    try:
        number = int(slot)
    except (TypeError, ValueError):
        number = 1
    if number in SLOT_LED_RGB:
        return SLOT_LED_RGB[number]
    # Wrap unknown indices into 1..4.
    keys = sorted(SLOT_LED_RGB.keys())
    if not keys:
        return (0, 220, 255)
    return SLOT_LED_RGB[keys[(number - 1) % len(keys)]]


def calibrate_led_rgb(
    r: int,
    g: int,
    b: int,
    *,
    kind: str,
) -> tuple[int, int, int]:
    """Apply hardware channel gains so theme colors match on DualSense / DS4."""
    gains = _DUALSENSE_CHANNEL_GAIN if kind == "dualsense" else _DS4_CHANNEL_GAIN
    return (
        _clamp_byte(round(r * gains[0])),
        _clamp_byte(round(g * gains[1])),
        _clamp_byte(round(b * gains[2])),
    )


# DualSense USB output (hid-playstation.c dualsense_output_report_usb).
_DS5_USB_REPORT_ID = 0x02
_DS5_USB_REPORT_SIZE = 48
_DS5_FLAG1_LIGHTBAR = 0x04  # DS_OUTPUT_VALID_FLAG1_LIGHTBAR_CONTROL_ENABLE
# RGB offsets inside full USB report (report_id at [0], common starts at [1]).
_DS5_USB_R = 45
_DS5_USB_G = 46
_DS5_USB_B = 47

# DualSense BT output 0x31 + CRC32 seed 0xA2.
_DS5_BT_REPORT_ID = 0x31
_DS5_BT_REPORT_SIZE = 78
_DS5_BT_COMMON = 3  # after report_id, seq_tag, tag
_DS5_BT_R = _DS5_BT_COMMON + 44
_DS5_BT_G = _DS5_BT_COMMON + 45
_DS5_BT_B = _DS5_BT_COMMON + 46

# DS4 USB — LED-only valid flag (BIT(1)), no rumble / blink / BT enable.
_DS4_USB_REPORT_ID = 0x05
_DS4_USB_REPORT_SIZE = 32
_DS4_USB_FLAG_LED = 0x02
_DS4_USB_R = 7
_DS4_USB_G = 8
_DS4_USB_B = 9

# DS4 BT output 0x11 (LED bytes in hid-sony layout) + CRC — still LED-only flags.
_DS4_BT_REPORT_ID = 0x11
_DS4_BT_REPORT_SIZE = 78
_DS4_BT_FLAG_LED = 0x02
_DS4_BT_R = 9
_DS4_BT_G = 10
_DS4_BT_B = 11


def _clamp_byte(value: int) -> int:
    return max(0, min(255, int(value)))


def _ps_crc32(seed: int, data: bytes) -> int:
    crc = zlib.crc32(bytes([seed]), 0xFFFFFFFF)
    crc = zlib.crc32(data, crc)
    return (~crc) & 0xFFFFFFFF


def build_dualsense_led_report(
    r: int,
    g: int,
    b: int,
    connection_type: DS4ConnectionType,
) -> bytes:
    """Lightbar-only DualSense output (no rumble / triggers / setup kicks)."""
    r, g, b = _clamp_byte(r), _clamp_byte(g), _clamp_byte(b)
    if connection_type == DS4ConnectionType.USB:
        report = bytearray(_DS5_USB_REPORT_SIZE)
        report[0] = _DS5_USB_REPORT_ID
        report[2] = _DS5_FLAG1_LIGHTBAR
        report[_DS5_USB_R] = r
        report[_DS5_USB_G] = g
        report[_DS5_USB_B] = b
        return bytes(report)

    report = bytearray(_DS5_BT_REPORT_SIZE)
    report[0] = _DS5_BT_REPORT_ID
    report[1] = 0x10  # seq/tag nibble style used by hid-playstation
    report[2] = 0x10
    report[_DS5_BT_COMMON + 1] = _DS5_FLAG1_LIGHTBAR  # valid_flag1 inside common
    report[_DS5_BT_R] = r
    report[_DS5_BT_G] = g
    report[_DS5_BT_B] = b
    crc = _ps_crc32(PS_OUTPUT_CRC32_SEED, bytes(report[:-4]))
    struct.pack_into("<I", report, _DS5_BT_REPORT_SIZE - 4, crc)
    return bytes(report)


def build_ds4_led_report(
    r: int,
    g: int,
    b: int,
    connection_type: DS4ConnectionType,
) -> bytes:
    """Lightbar-only DS4 output — never the BT feature-enable / USB kick combo."""
    r, g, b = _clamp_byte(r), _clamp_byte(g), _clamp_byte(b)
    if connection_type == DS4ConnectionType.USB:
        report = bytearray(_DS4_USB_REPORT_SIZE)
        report[0] = _DS4_USB_REPORT_ID
        report[1] = _DS4_USB_FLAG_LED
        report[_DS4_USB_R] = r
        report[_DS4_USB_G] = g
        report[_DS4_USB_B] = b
        return bytes(report)

    report = bytearray(_DS4_BT_REPORT_SIZE)
    report[0] = _DS4_BT_REPORT_ID
    report[1] = 0xC0
    report[3] = _DS4_BT_FLAG_LED
    report[_DS4_BT_R] = r
    report[_DS4_BT_G] = g
    report[_DS4_BT_B] = b
    crc = _ps_crc32(PS_OUTPUT_CRC32_SEED, bytes(report[:-4]))
    struct.pack_into("<I", report, _DS4_BT_REPORT_SIZE - 4, crc)
    return bytes(report)


def write_led_report(hid_dev: object, payload: bytes) -> bool:
    """Best-effort non-blocking HID write. Never raises to callers."""
    if hid_dev is None or not payload:
        return False
    try:
        written = hid_dev.write(payload)  # type: ignore[attr-defined]
        if written is not None and written < 0:
            logger.debug("LED HID write returned %s", written)
            return False
        return True
    except Exception:
        logger.debug("LED HID write failed", exc_info=True)
        return False


def set_led_on_device(
    hid_dev: object,
    *,
    kind: str,
    connection_type: DS4ConnectionType,
    r: int,
    g: int,
    b: int,
) -> bool:
    """Dispatch calibrated DualSense / DS4 LED payload for an open hid handle."""
    cr, cg, cb = calibrate_led_rgb(r, g, b, kind=kind)
    if kind == "dualsense":
        payload = build_dualsense_led_report(cr, cg, cb, connection_type)
    else:
        payload = build_ds4_led_report(cr, cg, cb, connection_type)
    return write_led_report(hid_dev, payload)


def iter_slot_led_theme() -> Mapping[int, tuple[int, int, int]]:
    """Read-only view of the tunable theme dictionary."""
    return SLOT_LED_RGB
