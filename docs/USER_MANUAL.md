# User Manual (v0.1.0, Phase 1)

## Dashboard
* **ADB**: whether PokePilot could run adb. *Connected* means the last `adb devices` call succeeded.
* **Emulator / Device**: state of the *selected* device (Online, Offline, Unauthorized, Disconnected).
* **PGSharp / Screen Mirroring / Automation Session**: show *Not checked*, *Not running* or *Idle*
  until their modules arrive. PokePilot never shows a state it has not verified.
* **Session Controls**: disabled until the automation engine (Phase 5).
* **Recent Activity**: the latest 100 log messages.

## Emulator Manager
* **Refresh**: runs `adb devices -l`. With auto-refresh enabled this also runs every few seconds.
* **Restart ADB Server**: `adb kill-server` then `adb start-server`. TCP devices must be connected again afterwards.
* **Launch Emulator**: starts the executable configured in Settings.
* **Connect over TCP/IP**: `adb connect host:port`. Successful addresses are remembered.
* **Detected Devices**: click a row to select it. The selection is saved and restored on the next start.
  * If exactly one device is online and none is selected, it is selected automatically.
  * With several devices, nothing is selected until you choose one.
  * If the selected device disappears, PokePilot does not silently switch to a different device
    (unless exactly one other device is online).
* **Read Device Info**: Android version, API level, manufacturer, model, CPU ABI, screen resolution, QEMU flag.

## Settings
Changes take effect when you press **Save Settings**. **Revert** discards unsaved edits. Closing the
window with unsaved edits asks for confirmation.

## Activity Monitor
A live log for the current run. Filter by level, clear the view, or open the log folder. Log files
rotate at 2 MB and the last 5 files are kept.
