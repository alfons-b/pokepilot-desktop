"""Reconnection policy for TCP/IP devices (pure logic).

Emulators such as BlueStacks expose ADB over TCP. Those connections are lost
whenever the ADB server restarts or the emulator restarts, and must be
re-established with ``adb connect``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.emulator.adb_client import validate_address
from app.emulator.models import AdbDevice, DeviceState

RECONNECT_INTERVAL_S = 10.0


@dataclass(frozen=True)
class ReconnectAction:
    address: str
    disconnect_first: bool  # True when ADB lists the device as offline


def is_tcp_address(serial: str | None) -> bool:
    if not serial:
        return False
    try:
        validate_address(serial)
    except ValueError:
        return False
    return True


def plan_reconnect(
    devices: Sequence[AdbDevice],
    selected: str | None,
    preferred: str | None,
    last_attempt: float | None,
    now: float,
    interval: float = RECONNECT_INTERVAL_S,
) -> ReconnectAction | None:
    """Return the reconnect to attempt now, or None.

    The target is the selected device, otherwise the user's preferred device.
    Only TCP addresses can be reconnected. Attempts are rate-limited.
    """
    target = selected or preferred
    if not is_tcp_address(target):
        return None
    if last_attempt is not None and now - last_attempt < interval:
        return None
    device = next((d for d in devices if d.serial == target), None)
    if device is None:
        return ReconnectAction(target, disconnect_first=False)
    if device.state is DeviceState.OFFLINE:
        return ReconnectAction(target, disconnect_first=True)
    return None
