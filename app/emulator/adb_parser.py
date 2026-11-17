"""Pure parsing functions for ADB command output (no I/O, fully unit-testable)."""

from __future__ import annotations

import re

from app.emulator.models import AdbDevice, DeviceState

_KNOWN_KV_KEYS = {"product", "model", "device", "transport_id"}
_GETPROP_RE = re.compile(r"^\[(?P<key>[^\]]+)\]:\s*\[(?P<value>.*)\]\s*$")
_SIZE_RE = re.compile(r"(?P<w>\d+)\s*x\s*(?P<h>\d+)")
_VERSION_RE = re.compile(r"Android Debug Bridge version\s+(?P<v>[\d.]+)")
_REVISION_RE = re.compile(r"Version\s+(?P<v>[\w.\-]+)")


def parse_devices_output(text: str) -> list[AdbDevice]:
    """Parse ``adb devices -l`` output.

    Example lines::

        List of devices attached
        emulator-5554  device product:sdk_gphone64 model:Pixel_7 device:emu64 transport_id:1
        127.0.0.1:5555 offline
        R58M123        no permissions (missing udev rules?); see [http://...]
        * daemon not running; starting now at tcp:5037
    """
    devices: list[AdbDevice] = []
    seen: set[str] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("*") or line.lower().startswith("list of devices"):
            continue
        if line.lower().startswith(("adb server", "error:", "warning:")):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        serial = parts[0]
        rest = parts[1:]
        if rest[0].lower() == "no" and len(rest) > 1 and rest[1].lower().startswith("permissions"):
            raw_state = "no permissions"
            rest = []  # remainder is a free-text explanation, not key:value data
        else:
            raw_state = rest[0]
            rest = rest[1:]

        kv: dict[str, str] = {}
        for token in rest:
            if ":" in token:
                key, _, value = token.partition(":")
                kv[key] = value
        if serial in seen:
            continue
        seen.add(serial)
        devices.append(
            AdbDevice(
                serial=serial,
                state=DeviceState.parse(raw_state),
                raw_state=raw_state,
                product=kv.get("product", ""),
                model=kv.get("model", ""),
                device=kv.get("device", ""),
                transport_id=kv.get("transport_id", ""),
                extra={k: v for k, v in kv.items() if k not in _KNOWN_KV_KEYS},
            )
        )
    return devices


def parse_getprop_output(text: str) -> dict[str, str]:
    """Parse full ``getprop`` output into a dict."""
    props: dict[str, str] = {}
    for line in text.splitlines():
        m = _GETPROP_RE.match(line.strip())
        if m:
            props[m.group("key")] = m.group("value")
    return props


def parse_wm_size(text: str) -> tuple[tuple[int, int] | None, tuple[int, int] | None]:
    """Parse ``wm size`` output into (physical, override) resolutions."""
    physical: tuple[int, int] | None = None
    override: tuple[int, int] | None = None
    for line in text.splitlines():
        m = _SIZE_RE.search(line)
        if not m:
            continue
        size = (int(m.group("w")), int(m.group("h")))
        lower = line.lower()
        if lower.startswith("physical size"):
            physical = size
        elif lower.startswith("override size"):
            override = size
        elif physical is None:
            physical = size
    return physical, override


def parse_adb_version(text: str) -> str | None:
    """Return a version string like ``1.0.41 (35.0.2)`` or None if not adb output."""
    m = _VERSION_RE.search(text)
    if not m:
        return None
    version = m.group("v")
    rev = _REVISION_RE.search(text)
    return f"{version} ({rev.group('v')})" if rev else version
