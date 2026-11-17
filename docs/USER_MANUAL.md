# User Manual (v1.0.0)

## Dashboard
* **ADB**: whether PokePilot could run adb. *Connected* means the last `adb devices` call succeeded.
* **Emulator / Device**: state of the *selected* device (Online, Offline, Unauthorized, Disconnected).
* **PGSharp**: the target app's process state (after a check) and the last verified screen.
* **Screen Mirroring**: scrcpy state.
* **Automation Session**: current profile, state, current action and last error. PokePilot never shows a
  state it has not checked: *Not checked* means exactly that.
* **Session Controls**: run the profile selected in Automation Manager (see
  [AUTOMATION_PROFILES.md](AUTOMATION_PROFILES.md)). **Stop** finishes the current action first;
  **Emergency Stop** interrupts immediately.
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

## Screen Monitor
Start, stop or restart scrcpy for the selected device and set its options. Control the emulator with your mouse
and keyboard directly in the scrcpy window. **Capture Screenshot** saves a PNG. Details:
[SCRCPY_SETUP.md](SCRCPY_SETUP.md).

## PGSharp Controller
Launch PGSharp, then calibrate tap targets (**UI Elements**), reference screens (**Screen States**) and
**Features** on a captured screenshot. **Verify Screen** shows which calibrated screen is currently open.
Details: [PGSHARP_SETUP.md](PGSHARP_SETUP.md).

## Automation Manager
Create profiles of ordered actions and run them. Details: [AUTOMATION_PROFILES.md](AUTOMATION_PROFILES.md).

## Location Manager
**Presets**: store named coordinates. Type or paste coordinates as `latitude, longitude`. Search filters by name
and notes. Favorites are listed first. **Copy Coordinates** puts `lat, lon` on the clipboard for PGSharp's
teleport field. Import/Export uses JSON (see the CHANGELOG for accepted formats).

**GPX Files**: **Import GPX** validates the file (XML structure, coordinates, size, no DOCTYPE/ENTITY) before
copying it to `data\gpx\`. The table shows points, tracks/routes and distance. To use a route, load the file
through PGSharp's Custom GPX screen. You may need to copy it to the emulator first; BlueStacks has a "Media
Manager / Import files" feature for this.

## Settings
Changes take effect when you press **Save Settings**. **Revert** discards unsaved edits. Closing the
window with unsaved edits asks for confirmation.

## Activity Monitor
* **Live Status**: ADB, emulator/device, PGSharp process, Pokémon GO process (only when the official package
  `com.nianticlabs.pokemongo` is installed and detectable), scrcpy, current profile, session state, current
  action, session duration, last successful UI verification and last error. App processes are checked every
  15 s while a device is online, or immediately with **Check Apps Now**.
* **Live Log**: messages from this run. Filter by level, clear the view, or open the log folder. Log files
  rotate at 2 MB and the last 5 files are kept.
* **Session History**: every session with its result and action counts. Select a session to see its stored log.
  The counts are PokePilot controller actions, **not** game statistics.
* **Stored Warnings & Errors**: WARNING and higher messages kept in the database across restarts.
