"""PlayStation HID sensor companion — gyro/accel/touch alongside pygame routing.

When multi-pad mode uses pygame (SDL HIDAPI) for buttons/axes, DualSense/DS4
motion is still incomplete from SDL. This companion opens the Sony HID path
for sensors (interrupt reads) and optional *safe* lightbar writes only.

Never send feature/enable/kick reports — those collide with SDL and trigger
Windows USB hotplug loops. LED updates use ``ps_led`` lightbar-only payloads.
"""

from __future__ import annotations

import logging
import struct
import threading
from dataclasses import dataclass, field
from typing import Optional

from kolbe.controller.ds4_hid import (
    DS4ConnectionType,
    DS4HidDeviceInfo,
    DUALSENSE_PRODUCT_IDS,
    DS4_PRODUCT_IDS,
    PS_INPUT_CRC32_SEED,
    SONY_VID,
    has_hidapi,
    is_dualsense_product,
    parse_ds4_input_report,
    read_ds4_hid_report,
    sony_product_id_from_guid,
)
from kolbe.controller.touchpad_smoother import TouchpadSmoother
from kolbe.controller.types import (
    ControllerDevice,
    ControllerState,
    ControllerType,
    InputSource,
    TouchPoint,
)

logger = logging.getLogger(__name__)

# DualSense absolute touchpad resolution (USB / BT full reports).
_DS5_TOUCHPAD_MAX_X = 1920.0
_DS5_TOUCHPAD_MAX_Y = 1080.0

# Paths currently claimed by a companion, keyed by hid path → device.id
_claimed_paths: dict[bytes, str] = {}
_claim_lock = threading.Lock()


@dataclass
class SensorSnapshot:
    gyro: dict[str, float] = field(default_factory=dict)
    accelerometer: dict[str, float] = field(default_factory=dict)
    touchpad: list[TouchPoint] = field(default_factory=lambda: [TouchPoint(), TouchPoint()])
    touch_axes: dict[str, float] = field(default_factory=dict)
    buttons: dict[str, bool] = field(default_factory=dict)
    battery_percent: Optional[int] = None
    battery_label: Optional[str] = None


def _ps_crc32(seed: int, data: bytes) -> int:
    import zlib

    crc = zlib.crc32(bytes([seed]), 0xFFFFFFFF)
    crc = zlib.crc32(data, crc)
    return (~crc) & 0xFFFFFFFF


def _claim_path(path: bytes, device_id: str) -> bool:
    with _claim_lock:
        owner = _claimed_paths.get(path)
        if owner is not None and owner != device_id:
            return False
        _claimed_paths[path] = device_id
        return True


def _release_path(path: Optional[bytes], device_id: str) -> None:
    if path is None:
        return
    with _claim_lock:
        if _claimed_paths.get(path) == device_id:
            _claimed_paths.pop(path, None)


def _connection_type(info: dict) -> DS4ConnectionType:
    """Classify USB vs BT using bus_type first, then interface_number."""
    bus = info.get("bus_type")
    if bus == 2:
        return DS4ConnectionType.BLUETOOTH
    if bus == 1:
        return DS4ConnectionType.USB
    interface = info.get("interface_number", -1)
    if isinstance(interface, int) and interface >= 0:
        return DS4ConnectionType.USB
    return DS4ConnectionType.BLUETOOTH


def enumerate_sony_hid(product_ids: frozenset[int]) -> list[DS4HidDeviceInfo]:
    """List Sony HID interfaces matching the given product IDs."""
    if not has_hidapi():
        return []
    import hid

    candidates: list[DS4HidDeviceInfo] = []
    seen: set[bytes] = set()
    for info in hid.enumerate(SONY_VID, 0):
        pid = info.get("product_id", 0)
        if pid not in product_ids:
            continue
        path = info.get("path")
        if not path or path in seen:
            continue
        seen.add(path)
        candidates.append(
            DS4HidDeviceInfo(
                path=path,
                product_id=pid,
                product_string=info.get("product_string") or "Sony Controller",
                connection_type=_connection_type(info),
            )
        )
    # Prefer USB (more reliable motion) then stable path order.
    candidates.sort(
        key=lambda c: (
            c.connection_type != DS4ConnectionType.USB,
            c.product_id,
            c.path,
        )
    )
    return candidates


def _resolve_sensor_kind(device: ControllerDevice) -> tuple[str, frozenset[int], Optional[int]]:
    """Return (kind, product_ids, preferred_pid) for this pygame device."""
    preferred = sony_product_id_from_guid(device.guid)
    if preferred is not None and is_dualsense_product(preferred):
        return "dualsense", DUALSENSE_PRODUCT_IDS, preferred
    if preferred is not None and preferred in DS4_PRODUCT_IDS:
        return "ds4", DS4_PRODUCT_IDS, preferred

    name = (device.name or "").lower()
    if device.controller_type == ControllerType.DUALSENSE or "dualsense" in name or "ps5" in name:
        return "dualsense", DUALSENSE_PRODUCT_IDS, preferred
    return "ds4", DS4_PRODUCT_IDS, preferred


def _pick_unclaimed_path(
    candidates: list[DS4HidDeviceInfo],
    device_id: str,
    preferred_product_id: Optional[int] = None,
) -> Optional[DS4HidDeviceInfo]:
    ordered = list(candidates)
    if preferred_product_id is not None:
        matched = [c for c in ordered if c.product_id == preferred_product_id]
        rest = [c for c in ordered if c.product_id != preferred_product_id]
        ordered = matched + rest
    for candidate in ordered:
        if _claim_path(candidate.path, device_id):
            return candidate
    return None


def _parse_touch_point_ds5(
    data: bytes, offset: int
) -> tuple[bool, float, float, int]:
    if offset + 4 > len(data):
        return False, 0.0, 0.0, 0
    contact = data[offset]
    active = (contact & 0x80) == 0
    finger_id = contact & 0x7F
    if not active:
        return False, 0.0, 0.0, finger_id
    x_lo = data[offset + 1]
    x_hi_y_lo = data[offset + 2]
    y_hi = data[offset + 3]
    x = ((x_hi_y_lo & 0x0F) << 8) | x_lo
    y = (y_hi << 4) | ((x_hi_y_lo & 0xF0) >> 4)
    return (
        True,
        max(0.0, min(1.0, x / _DS5_TOUCHPAD_MAX_X)),
        max(0.0, min(1.0, y / _DS5_TOUCHPAD_MAX_Y)),
        finger_id,
    )


def parse_dualsense_sensors(
    report: bytes,
    *,
    force_wired: bool = False,
) -> tuple[Optional[SensorSnapshot], list[tuple[bool, float, float, int]]]:
    """Extract motion / touch / battery / click from DualSense USB 0x01 or BT 0x31 reports."""
    if not report:
        return None, []
    rid = report[0]
    if rid == 0x01 and len(report) >= 64:
        base = 0
        report_is_usb = True
    elif rid == 0x31 and len(report) >= 78:
        expected = struct.unpack_from("<I", report, len(report) - 4)[0]
        if _ps_crc32(PS_INPUT_CRC32_SEED, report[:-4]) != expected:
            logger.debug("DualSense BT CRC mismatch — skipping report")
            return None, []
        base = 1
        report_is_usb = False
    else:
        return None, []

    g0 = base + 16
    a0 = base + 22
    if a0 + 6 > len(report):
        return None, []

    gyro = {
        InputSource.GYRO_PITCH.value: float(struct.unpack_from("<h", report, g0)[0]),
        InputSource.GYRO_YAW.value: float(struct.unpack_from("<h", report, g0 + 2)[0]),
        InputSource.GYRO_ROLL.value: float(struct.unpack_from("<h", report, g0 + 4)[0]),
    }
    accelerometer = {
        InputSource.ACCEL_X.value: float(struct.unpack_from("<h", report, a0)[0]),
        InputSource.ACCEL_Y.value: float(struct.unpack_from("<h", report, a0 + 2)[0]),
        InputSource.ACCEL_Z.value: float(struct.unpack_from("<h", report, a0 + 4)[0]),
    }

    # Face/shoulder bytes (same layout pydualsense uses after report-id base).
    buttons: dict[str, bool] = {}
    misc2_off = base + 10
    if misc2_off < len(report):
        misc2 = report[misc2_off]
        buttons[InputSource.PS.value] = bool(misc2 & 0x01)
        buttons[InputSource.TOUCHPAD_CLICK.value] = bool(misc2 & 0x02)
        buttons[InputSource.MICROPHONE.value] = bool(misc2 & 0x04)

    touch_raw: list[tuple[bool, float, float, int]] = []
    touch_base = base + 33
    if touch_base + 8 <= len(report):
        touch_raw = [
            _parse_touch_point_ds5(report, touch_base),
            _parse_touch_point_ds5(report, touch_base + 4),
        ]

    battery_percent: Optional[int] = None
    battery_label: Optional[str] = None
    batt_off = base + 53
    # USB cable: report 0x01 and/or enumerated bus_type — never show draining %.
    wired = force_wired or report_is_usb
    if batt_off < len(report):
        status = report[batt_off]
        level = status & 0x0F
        charging = bool(status & 0x10)
        fully_charged = bool(status & 0x20)
        # Cable present: charging/full bits, or USB transport.
        if wired or charging or fully_charged:
            battery_percent = None
            battery_label = "Wired"
        elif level:
            battery_percent = min(level * 10 + 5, 100)
            battery_label = f"{battery_percent}%"
        else:
            battery_percent = None
            battery_label = "Wired"
    elif wired:
        battery_label = "Wired"

    snap = SensorSnapshot(
        gyro=gyro,
        accelerometer=accelerometer,
        buttons=buttons,
        battery_percent=battery_percent,
        battery_label=battery_label,
    )
    return snap, touch_raw


def device_wants_ps_sensors(device: ControllerDevice) -> bool:
    if device.controller_type in (ControllerType.DUALSENSE, ControllerType.PLAYSTATION):
        return True
    pid = sony_product_id_from_guid(device.guid)
    if pid is not None and (is_dualsense_product(pid) or pid in DS4_PRODUCT_IDS):
        return True
    name = (device.name or "").lower()
    return "dualsense" in name or "dualshock" in name or "ps4" in name or "ps5" in name


class PlayStationSensorCompanion:
    """HID reader that only contributes sensors to a pygame-driven ControllerState."""

    def __init__(self, device: ControllerDevice) -> None:
        self.device = device
        self._hid: Optional[object] = None
        self._hid_info: Optional[DS4HidDeviceInfo] = None
        kind, _pids, _pref = _resolve_sensor_kind(device)
        self._kind: str = kind
        self._last_report: Optional[bytes] = None
        self._last_snap = SensorSnapshot()
        self._touchpad_smoother = TouchpadSmoother()
        self._closed = False
        self._reads_attempted = 0
        self._reads_ok = 0
        self._warned_no_data = False
        self._last_led: Optional[tuple[int, int, int]] = None
        self._lifecycle_closer = None

    @classmethod
    def try_open(cls, device: ControllerDevice) -> Optional["PlayStationSensorCompanion"]:
        if not device_wants_ps_sensors(device):
            return None

        from kolbe.hidapi_bootstrap import ensure_hidapi_loaded

        dll = ensure_hidapi_loaded()
        if not has_hidapi():
            logger.warning(
                "PS sensor companion skipped for %s — hidapi unavailable "
                "(dll=%s). Gyro/accel will stay empty.",
                device.name,
                dll,
            )
            return None

        companion = cls(device)
        try:
            companion.open()
        except Exception:
            logger.warning(
                "PS sensor companion unavailable for %s (%s)",
                device.name,
                device.id,
                exc_info=True,
            )
            companion.close()
            return None
        return companion

    def open(self) -> None:
        from kolbe.hidapi_bootstrap import ensure_hidapi_loaded

        ensure_hidapi_loaded()
        import hid

        kind, product_ids, preferred_pid = _resolve_sensor_kind(self.device)
        self._kind = kind
        candidates = enumerate_sony_hid(product_ids)
        if not candidates:
            raise RuntimeError(f"No HID interfaces found for {kind} (pids={sorted(product_ids)})")

        picked = _pick_unclaimed_path(candidates, self.device.id, preferred_pid)
        if picked is None:
            raise RuntimeError(f"All {kind} HID paths already claimed")

        self._hid_info = picked
        self._hid = hid.device()
        try:
            self._hid.open_path(picked.path)
            self._hid.set_nonblocking(True)
        except Exception:
            _release_path(picked.path, self.device.id)
            self._hid_info = None
            self._hid = None
            raise

        from kolbe.controller.hid_lifecycle import register_hid_closer

        self._lifecycle_closer = self.close
        register_hid_closer(self._lifecycle_closer)

        # Sensors via interrupt read. LED color may be written later via set_led()
        # using lightbar-only payloads (never feature/enable kicks).
        logger.info(
            "PS sensor companion open (sensors + safe LED): %s → %s pid=0x%04X (%s, guid=%s, preferred=0x%04X)",
            self.device.name,
            picked.product_string,
            picked.product_id,
            picked.connection_type.value,
            self.device.guid,
            preferred_pid or 0,
        )

    def set_led(self, r: int, g: int, b: int) -> bool:
        """Apply lightbar RGB. Non-blocking; skips duplicate colors; never raises."""
        if self._closed or self._hid is None or self._hid_info is None:
            return False
        color = (max(0, min(255, int(r))), max(0, min(255, int(g))), max(0, min(255, int(b))))
        if self._last_led == color:
            return True
        from kolbe.controller.ps_led import set_led_on_device

        ok = set_led_on_device(
            self._hid,
            kind=self._kind,
            connection_type=self._hid_info.connection_type,
            r=color[0],
            g=color[1],
            b=color[2],
        )
        if ok:
            self._last_led = color
            logger.debug(
                "Slot LED set for %s → rgb(%d,%d,%d)",
                self.device.name,
                color[0],
                color[1],
                color[2],
            )
        return ok

    def clear_led(self) -> None:
        """Dim lightbar before disconnect (best-effort)."""
        try:
            self.set_led(0, 0, 0)
        except Exception:
            pass
        self._last_led = None

    def close(self) -> None:
        if self._closed and self._hid is None:
            return
        self.clear_led()
        self._closed = True
        closer = getattr(self, "_lifecycle_closer", None)
        if closer is not None:
            try:
                from kolbe.controller.hid_lifecycle import unregister_hid_closer

                unregister_hid_closer(closer)
            except Exception:
                pass
            self._lifecycle_closer = None
        path = self._hid_info.path if self._hid_info is not None else None
        hid_dev = self._hid
        self._hid = None
        self._hid_info = None
        if hid_dev is not None:
            try:
                hid_dev.close()
            except Exception:
                logger.debug("Error closing PS sensor HID", exc_info=True)
        _release_path(path, self.device.id)

    def poll_sensors(self) -> SensorSnapshot:
        if self._closed or self._hid is None:
            return self._last_snap

        report = self._read_latest()
        self._reads_attempted += 1
        if report is not None:
            self._last_report = report
            self._reads_ok += 1

        if self._last_report is None:
            if (
                not self._warned_no_data
                and self._reads_attempted >= 40
                and self._reads_ok == 0
            ):
                self._warned_no_data = True
                logger.warning(
                    "PS sensor companion for %s opened HID but received no input "
                    "reports — gyro/accel unavailable (read-only; no feature/enable "
                    "writes, to avoid colliding with SDL HIDAPI)",
                    self.device.name,
                )
            return self._last_snap

        if self._kind == "ds4":
            snap = self._from_ds4(self._last_report)
        else:
            snap = self._from_dualsense(self._last_report)

        if snap is not None:
            self._last_snap = snap
        return self._last_snap

    def merge_into(self, state: ControllerState) -> ControllerState:
        """Overlay sensors/touch/click onto a pygame state without replacing sticks."""
        try:
            snap = self.poll_sensors()
        except Exception:
            logger.debug(
                "PS sensor poll failed for %s — leaving pygame state unchanged",
                self.device.name,
                exc_info=True,
            )
            return state

        has_motion = bool(snap.gyro or snap.accelerometer)
        has_touch = bool(snap.touch_axes) or any(t.active for t in snap.touchpad)
        has_buttons = bool(snap.buttons)
        has_battery = snap.battery_label is not None or snap.battery_percent is not None

        if not has_motion and not has_touch and not has_buttons and not has_battery:
            return state

        axes = dict(state.axes)
        if snap.touch_axes:
            axes.update(snap.touch_axes)

        buttons = dict(state.buttons)
        # HID is authoritative for touchpad click (pygame often misses it when the
        # companion holds the DualSense/DS4 HID interface for sensors).
        for key, pressed in snap.buttons.items():
            if key == InputSource.TOUCHPAD_CLICK.value or key not in buttons:
                buttons[key] = pressed
            else:
                buttons[key] = bool(buttons[key] or pressed)

        batt_percent, batt_label = self._battery_overlay(snap, state)

        return ControllerState(
            device=state.device,
            buttons=buttons,
            axes=axes,
            touchpad=snap.touchpad if any(t.active for t in snap.touchpad) else state.touchpad,
            gyro=dict(snap.gyro) if snap.gyro else state.gyro,
            accelerometer=dict(snap.accelerometer) if snap.accelerometer else state.accelerometer,
            battery_percent=batt_percent,
            battery_label=batt_label,
        )

    def _battery_overlay(
        self, snap: SensorSnapshot, state: ControllerState
    ) -> tuple[Optional[int], Optional[str]]:
        """Companion battery wins; USB / Wired must not fall back to pygame percent."""
        usb = (
            self._hid_info is not None
            and self._hid_info.connection_type == DS4ConnectionType.USB
        )
        if usb or snap.battery_label == "Wired":
            return None, "Wired"
        if snap.battery_label is not None:
            return snap.battery_percent, snap.battery_label
        return state.battery_percent, state.battery_label

    def _from_ds4(self, report: bytes) -> Optional[SensorSnapshot]:
        parsed = parse_ds4_input_report(report)
        if parsed is None:
            return None
        touchpad = self._touchpad_smoother.process_pair(parsed.touchpad or [])
        touch_axes: dict[str, float] = {}
        if touchpad[0].active:
            touch_axes[InputSource.TOUCHPAD_0_X.value] = touchpad[0].x
            touch_axes[InputSource.TOUCHPAD_0_Y.value] = touchpad[0].y
        if touchpad[1].active:
            touch_axes[InputSource.TOUCHPAD_1_X.value] = touchpad[1].x
            touch_axes[InputSource.TOUCHPAD_1_Y.value] = touchpad[1].y
        usb = (
            self._hid_info is not None
            and self._hid_info.connection_type == DS4ConnectionType.USB
        ) or (report and report[0] == 0x01)
        if usb:
            percent: Optional[int] = None
            label = "Wired"
        elif parsed.battery_percent is not None:
            percent = parsed.battery_percent
            label = f"{parsed.battery_percent}%"
        else:
            percent = None
            label = "Wired"
        buttons = {
            InputSource.TOUCHPAD_CLICK.value: bool(
                parsed.buttons.get("touchpad_click", False)
            ),
            InputSource.PS.value: bool(parsed.buttons.get("ps", False)),
        }
        return SensorSnapshot(
            gyro=dict(parsed.gyro),
            accelerometer=dict(parsed.accelerometer),
            touchpad=touchpad,
            touch_axes=touch_axes,
            buttons=buttons,
            battery_percent=percent,
            battery_label=label,
        )

    def _from_dualsense(self, report: bytes) -> Optional[SensorSnapshot]:
        force_wired = (
            self._hid_info is not None
            and self._hid_info.connection_type == DS4ConnectionType.USB
        )
        snap, touch_raw = parse_dualsense_sensors(report, force_wired=force_wired)
        if snap is None:
            return None
        touchpad = self._touchpad_smoother.process_pair(touch_raw)
        touch_axes: dict[str, float] = {}
        if touchpad[0].active:
            touch_axes[InputSource.TOUCHPAD_0_X.value] = touchpad[0].x
            touch_axes[InputSource.TOUCHPAD_0_Y.value] = touchpad[0].y
        if touchpad[1].active:
            touch_axes[InputSource.TOUCHPAD_1_X.value] = touchpad[1].x
            touch_axes[InputSource.TOUCHPAD_1_Y.value] = touchpad[1].y
        snap.touchpad = touchpad
        snap.touch_axes = touch_axes
        return snap

    def _read_latest(self) -> Optional[bytes]:
        if self._hid is None:
            return None
        if self._kind == "ds4":
            return read_ds4_hid_report(self._hid, allow_get_input_report=False)

        latest: Optional[bytes] = None
        try:
            while True:
                chunk = self._hid.read(128)
                if not chunk:
                    break
                latest = bytes(chunk)
        except OSError:
            logger.debug("PS sensor HID read error", exc_info=True)
        return latest
