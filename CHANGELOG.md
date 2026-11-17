# Changelog

All notable changes to this project are documented here. Format: [Keep a Changelog](https://keepachangelog.com/).

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
