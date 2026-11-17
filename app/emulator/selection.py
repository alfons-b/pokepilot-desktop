"""Device selection policy (pure logic)."""

from __future__ import annotations

from collections.abc import Sequence

from app.emulator.models import AdbDevice


def choose_selected_serial(
    devices: Sequence[AdbDevice],
    current: str | None,
    preferred: str | None,
) -> str | None:
    """Decide which device serial should be selected after a device list refresh.

    Rules, in order:

    1. Keep the current selection while it is still listed (even if temporarily
       offline), so the user's choice is never silently switched to another device.
    2. Restore the user's saved preferred device when it is listed.
    3. Auto-select only when exactly one device is online - with several devices
       the user must choose explicitly.
    4. Otherwise nothing is selected.
    """
    listed = {d.serial for d in devices}
    if current and current in listed:
        return current
    if preferred and preferred in listed:
        return preferred
    online = [d for d in devices if d.is_online]
    if len(online) == 1:
        return online[0].serial
    return None
