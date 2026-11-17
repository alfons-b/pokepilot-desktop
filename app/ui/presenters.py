"""Map domain state to display (level, text) pairs. Kept separate for testing."""

from __future__ import annotations

from app.core.device_controller import AdbStatus
from app.emulator.models import AdbDevice, DeviceState

_ADB_LEVELS = {
    AdbStatus.OK: "ok",
    AdbStatus.UNKNOWN: "idle",
    AdbStatus.NOT_CONFIGURED: "warn",
    AdbStatus.NOT_FOUND: "error",
    AdbStatus.TIMEOUT: "error",
    AdbStatus.ERROR: "error",
}

_STATE_LEVELS = {
    DeviceState.DEVICE: "ok",
    DeviceState.OFFLINE: "error",
    DeviceState.UNAUTHORIZED: "warn",
    DeviceState.AUTHORIZING: "warn",
    DeviceState.CONNECTING: "warn",
    DeviceState.NO_PERMISSIONS: "error",
}

_STATE_HELP = {
    DeviceState.OFFLINE: "Device is offline. Try Restart ADB Server or restart the emulator.",
    DeviceState.UNAUTHORIZED: "Accept the USB debugging prompt inside the emulator.",
    DeviceState.NO_PERMISSIONS: "ADB lacks permission for this device.",
}


def adb_status_display(status: AdbStatus) -> str:
    return _ADB_LEVELS.get(status, "idle")


def device_state_display(state: DeviceState) -> str:
    return _STATE_LEVELS.get(state, "idle")


def device_display(device: AdbDevice | None, selected_serial: str | None) -> tuple[str, str, str]:
    """Return (level, headline, detail) for the selected device."""
    if not selected_serial:
        return "idle", "No device selected", "Open Emulator Manager to choose a device."
    if device is None:
        return "error", "Disconnected", f"{selected_serial} is not currently reported by ADB."
    level = device_state_display(device.state)
    headline = "Online" if device.is_online else device.raw_state.capitalize() or "Unknown"
    detail = device.display_name
    if device.state in _STATE_HELP:
        detail += f"\n{_STATE_HELP[device.state]}"
    return level, headline, detail
