# Changelog

All notable changes to this project are documented here. Format: [Keep a Changelog](https://keepachangelog.com/).

## [0.6.0] - 2026-11-17 - Phase 6: location manager

### Added
- **Location Manager** page:
  - **Presets**: add, edit, delete, favorites, search across name and notes (LIKE wildcards escaped),
    "Copy Coordinates" for pasting into PGSharp, JSON import/export. Import accepts PokePilot's format or a
    plain list with `lat`/`lng` keys, and reports skipped entries.
  - **GPX Files**: import (validated, then copied to `data/gpx`), rename, re-validate, export a copy, delete,
    open folder. Missing files are flagged.
- Coordinate parsing accepts `lat, lon`, `lat; lon`, `(lat, lon)` and `lat lon`, with range, NaN and infinity
  checks.
- GPX parser (GPX 1.0/1.1, namespace-agnostic): counts tracks, routes, waypoints and points, computes distance
  (haversine) and bounds. Rejects DOCTYPE/ENTITY declarations (XXE, "billion laughs"), files over 20 MB,
  malformed XML and invalid coordinates.
- Locations and GPX metadata are stored in SQLite (`location_presets`, `gpx_files`).
- 18 new tests (294 total).

### Notes
- As specified, PokePilot only manages location files and settings. Locations are applied through PGSharp's own
  teleport and GPX screens.

## [0.5.0] - 2026-11-17 - Phase 5: automation engine

### Added
- **Automation Manager** page: profiles (create, rename, duplicate, delete, JSON import/export), an ordered action
  list (add, edit, remove, move), live validation against the calibration, and session controls with a live log,
  duration, current action and last error.
- Action editor generated from each action type's parameter schema, for all 12 action types, with timeout,
  expected state, error policy (STOP, SKIP, RETRY) and retries.
- Sequential engine with an explicit state machine (IDLE, PREPARING, RUNNING, PAUSED, STOPPING, COMPLETED,
  FAILED); pause, resume, graceful stop, emergency stop (interrupts waits immediately) and user confirmation.
- Explicit results: SUCCEEDED only when verified (or inherently certain); taps and swipes without an expected
  state are UNKNOWN.
- Reliability:
  - pre-session checks (device online, profile valid, resolution matches calibration);
  - duplicate-action and single-session protection;
  - connection-loss recovery (30 s, repeats the action once), otherwise pending actions are CANCELLED;
  - a session stops if the selected device changes;
  - closing the app emergency-stops a running session.
- Dashboard session buttons are live and run the current profile; the session card shows state, current action
  and last error.
- SQLite database (`data/pokepilot.db`) with all 9 tables: foreign keys, indexes, CHECK constraints, WAL,
  transactions, versioned migrations, and backup and reset of corrupt files.
- Session history and activity log persistence. Sessions cut off by a crash are marked INTERRUPTED.
- `docs/AUTOMATION_PROFILES.md`. 61 new tests (276 total).

### Fixed
- Calibration marker labels were unreadable on light screenshots.

## [0.4.0] - 2026-11-17 - Phase 4: PGSharp controller and UI calibration

### Added
- **PGSharp Controller** page: launch and check the PGSharp app, then calibrate it on a screenshot canvas.
- UI elements (named tap targets) stored as normalized coordinates, with Add, Move, Remove and Test Tap.
- Screen states: reference regions captured from screenshots and compared as 32x32 grayscale signatures,
  with an adjustable match threshold. **Verify Screen** reports per-state matches and difference scores.
- Feature registry for Joystick, Teleport, Autowalk, Custom GPX, Nearby Radar, Quick Catch, Virtual GO Plus,
  Auto Transfer, Auto Discard and Auto Incubator. Availability starts *Unverified* and is set by the user;
  each feature has open steps, a toggle element and a verify state. **Test Feature** reports
  Success, Failed or Unknown.
- Layout change detection: warns when the aspect ratio or orientation differs from the calibration, and
  after 3 consecutive verifications with no matching state.
- `UiDriver`: synchronous tap, swipe, back, screenshot, verify and wait-for-state primitives with cancellation,
  shared with the automation engine.
- The Dashboard PGSharp card shows the process state and the last verified screen.
- Calibration is stored in `data/pgsharp_layout.json` (atomic save, corrupt files backed up).
- `docs/PGSHARP_SETUP.md`. 30 new tests (215 total).

## [0.3.0] - 2026-11-17 - Phase 3: scrcpy screen mirroring

### Added
- **Screen Monitor** page: start, stop and restart scrcpy for the selected device; live scrcpy output; status
  (Starting, Running, Stopping, Failed) based on scrcpy's own output.
- scrcpy options: max size, frame rate, bitrate, fullscreen, always-on-top, keep awake, view-only (no
  input), UHID keyboard, auto-restart. Arguments adapt to the installed scrcpy version (1.x or 2.x+).
- Process supervision: graceful close followed by a kill after 3 s; automatic restart after a crash (at most 3 in
  2 min); mirroring stops when the selected device changes; scrcpy is stopped when PokePilot exits.
- scrcpy runs with `ADB=<configured adb>` so only one adb version is in use.
- Screenshot capture (`adb exec-out screencap -p`) with PNG validation, a preview, and a folder shortcut.
- Settings: scrcpy Auto-detect (PATH, winget, scoop, `C:\scrcpy`) and Test.
- ADB client: `tap`, `swipe`, `keyevent`, `get-state` and `screencap`, used by later phases.
- Dashboard mirroring card shows live state.
- `docs/SCRCPY_SETUP.md`. 23 new tests (185 total), including a fake scrcpy executable.

## [0.2.0] - 2026-11-17 - Phase 2: devices, reconnection, BlueStacks instances, app launcher

### Added
- Emulator Manager is now split into tabs: **Devices**, **Applications** and **Emulator Instances**.
- Automatic reconnection of TCP/IP devices such as BlueStacks: when the selected or preferred `host:port`
  device disappears or goes offline, PokePilot runs `adb connect`, after `adb disconnect` if the device is
  offline. Attempts are limited to one every 10 s and can be disabled in Settings. A manual **Reconnect**
  button was also added.
- BlueStacks 5 discovery (including MSI App Player): reads `bluestacks.conf` read-only, using the registry
  or `C:\ProgramData\BlueStacks_nxt`. Lists instances, their ADB ports and whether ADB access is enabled.
  Each instance can be connected, launched with `HD-Player.exe --instance <id>`, or set as the default.
- Applications tab: list installed apps (`pm list packages`, optionally including system apps), filter
  them, choose a **target app**, then **Launch** it, **Check Running** (`pidof`, falling back to `ps`)
  or **Force Stop** it (with confirmation).
- A launch reports three separate facts: whether Android accepted the command, whether the process is
  running, and that the UI state was not verified. A launch is never reported as successful unless
  the process is actually running.
- Settings: auto-reconnect toggle and an optional custom `bluestacks.conf` path.
- 54 new tests (162 total).

### Changed
- Automatic device selection no longer overwrites a device the user chose explicitly. That device stays
  the reconnect target.
- A refresh requested while another refresh is running is now queued instead of dropped.
- Long status bar messages are truncated.

## [0.1.0] - 2026-11-17 - Phase 1: application shell and ADB detection

### Added
- PySide6 main window with sidebar navigation for all 8 sections and a live status bar.
- Dashboard: ADB, device, PGSharp, mirroring and session status cards; recent activity log;
  quick actions. Session controls are shown disabled until the Phase 5 automation engine exists.
- Emulator Manager: device scan via `adb devices -l`, multi-device table with state colouring,
  explicit device selection (auto-selected only when exactly one device is online), TCP/IP
  connect with recent-address history, ADB server restart (with confirmation), emulator launch,
  and device info (Android version, API level, manufacturer, model, ABI, resolution).
- Settings: ADB path with Browse / Auto-detect / Test, command timeout, auto-refresh interval,
  emulator executable and arguments, scrcpy path, log level; Save / Revert; unsaved-changes guard.
- Activity Monitor: live, level-filtered log view and log-folder shortcut.
- ADB locator that checks PATH, `ANDROID_SDK_ROOT`, `ANDROID_HOME`, the Android Studio SDK and the
  folders where common emulators bundle `adb.exe`. Every candidate is verified with `adb version`.
- `AdbClient` built on argument-list subprocess calls (no shell), per-command timeouts, no console
  window on Windows, and `-s <serial>` on every device-specific command.
- JSON configuration: per-field type validation, range clamping, atomic writes, and backup and
  reset of corrupted files.
- Background `TaskRunner` (QThreadPool) that delivers results to the GUI thread.
- Rotating file logging (`logs/pokepilot.log`).
- pytest suite of 108 tests: unit, controller, GUI (pytest-qt) and subprocess integration tests.
