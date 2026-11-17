# User Manual (v0.2.0, Phase 2)

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

### Reconnect
**Reconnect** re-runs `adb connect` for the selected TCP/IP device. With *Automatically reconnect* enabled
(the default), PokePilot does this by itself, at most once every 10 seconds, whenever your selected or
preferred `host:port` device is missing or offline. Devices named `emulator-NNNN` do not need it.

## Emulator Manager: Applications tab
1. Select an online device, then press **Load Apps**. Only user-installed apps are listed unless
   *Include system apps* is ticked.
2. Type in the filter box, select your app, and press **Set as Target App** (or double-click it).
   PokePilot does not guess which package is PGSharp. You choose it.
3. **Launch** starts the app, then waits up to 10 s for its process. The result is one of:
   * *Running*: Android accepted the launch and the process exists. The screen content is **not** verified.
   * *Not running*: Android accepted the launch, but the process did not appear.
   * *Unknown*: the process state could not be determined.
   * If Android rejected the launch, the error message is shown.
4. **Check Running** re-checks the process. **Force Stop** runs `am force-stop` after confirmation and
   reports whether the process actually ended.

## Emulator Manager: Emulator Instances tab
**Scan** reads BlueStacks' `bluestacks.conf`. For each instance you see its ADB address, whether ADB
access is enabled, and whether it is currently connected. **Connect** runs `adb connect`. **Launch
Instance** starts `HD-Player.exe --instance <id>`. **Use as Default** stores that instance as the
emulator launcher (Settings) and as the preferred device.

## Settings
Changes take effect when you press **Save Settings**. **Revert** discards unsaved edits. Closing the
window with unsaved edits asks for confirmation.

## Activity Monitor
A live log for the current run. Filter by level, clear the view, or open the log folder. Log files
rotate at 2 MB and the last 5 files are kept.
