# PokePilot Desktop

A Windows desktop controller for an **existing** Android emulator (for example BlueStacks) running PGSharp and
Pokémon GO. It is built with Python and PySide6, talks to the emulator only through **ADB**, and mirrors the
screen with **scrcpy**.

PokePilot does **not** include or modify an emulator, does not modify or inspect any APK, does not touch game
network traffic or private APIs, and has no stealth or anti-detection features. Automation works only through
on-screen, user-facing UI actions that you configure. Using PGSharp may violate Pokémon GO's Terms of Service;
that risk to your account is yours to assess.

**Version 1.0.0**: all eight development phases are complete. See [CHANGELOG.md](CHANGELOG.md).

## Features
| Section | What it does |
|---|---|
| Dashboard | Live ADB, device, PGSharp, mirroring and session status; Start, Pause, Resume, Stop and Emergency Stop for the current profile; recent activity |
| Emulator Manager: Devices | `adb devices` scan, multi-device selection, TCP/IP connect, automatic and manual reconnection, restart ADB server, launch emulator, device info (Android version, API level, resolution) |
| Emulator Manager: Applications | List installed apps, choose your PGSharp app as the target, launch it (process verified), check it, force-stop it |
| Emulator Manager: Emulator Instances | Finds BlueStacks 5 instances and their ADB ports in `bluestacks.conf`; connect, launch or set as default |
| Screen Monitor | scrcpy mirroring with mouse and keyboard control; size, FPS, bitrate, fullscreen and view-only options; crash auto-restart; screenshots |
| PGSharp Controller | Calibrate tap targets and screen states on a screenshot; feature registry (availability set by you); test features; layout change warnings |
| Automation Manager | Profiles of ordered actions (12 types) with timeouts, expected states and error policies; JSON import/export; sessions with verification-based results and connection recovery |
| Location Manager | Location presets (favorites, search, copy coordinates, JSON import/export); validated GPX file management |
| Activity Monitor | Live status, live log, session history, stored warnings and errors |
| Settings | Paths to adb, emulator and scrcpy (auto-detect and test), timeouts, auto-refresh and auto-reconnect, log level |

## Quick start (Windows)

### A. Use the pre-built exe
1. On GitHub, open **Actions > Windows test & build**, pick the latest green run, and download the
   **PokePilot-windows-x64** artifact.
2. Extract it and run `PokePilot.exe`. Keep the whole folder together.

### B. Run from source
Install Python 3.12+ (tick *"Add python.exe to PATH"*), then in PowerShell in this folder:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m app
```
Or double-click **`run.bat`**, which sets everything up on first use. If PowerShell blocks `Activate.ps1`, run
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once.

### First-time setup (about 15 minutes)
1. **BlueStacks**: Settings > Advanced > enable *Android Debug Bridge*. See [docs/BLUESTACKS_SETUP.md](docs/BLUESTACKS_SETUP.md).
2. **Settings** in PokePilot: ADB **Auto-detect** then **Test**; scrcpy **Auto-detect** then **Test** (install scrcpy
   first, see [docs/SCRCPY_SETUP.md](docs/SCRCPY_SETUP.md)).
3. **Emulator Manager > Emulator Instances > Scan**, select your instance, then **Connect** and **Use as Default**.
4. **Emulator Manager > Applications > Load Apps**, select PGSharp, then **Set as Target App**.
5. **PGSharp Controller**: calibrate the buttons and screens you want to automate. See
   [docs/PGSHARP_SETUP.md](docs/PGSHARP_SETUP.md).
6. **Automation Manager**: build a profile and press **Start**. See [docs/AUTOMATION_PROFILES.md](docs/AUTOMATION_PROFILES.md).

## External dependencies
| Dependency | Purpose | Installed by |
|---|---|---|
| Python 3.12+ | Runs PokePilot from source (not needed for the exe) | You |
| PySide6 | GUI | `pip install -r requirements.txt` |
| adb.exe | Device communication | You: Platform-Tools or the emulator's bundled adb ([guide](docs/ADB_SETUP.md)) |
| scrcpy | Screen mirroring | You ([guide](docs/SCRCPY_SETUP.md)) |
| pytest, pytest-qt, ruff | Development | `pip install -r requirements-dev.txt` |
| PyInstaller | Packaging | `pip install -r requirements-build.txt` |

## Documentation
* [Installation](docs/INSTALLATION.md)
* [ADB configuration](docs/ADB_SETUP.md)
* [Existing emulator compatibility](docs/EMULATOR_COMPATIBILITY.md)
* [BlueStacks setup](docs/BLUESTACKS_SETUP.md)
* [scrcpy setup](docs/SCRCPY_SETUP.md)
* [PGSharp setup and calibration](docs/PGSHARP_SETUP.md)
* [User manual](docs/USER_MANUAL.md)
* [Automation profiles](docs/AUTOMATION_PROFILES.md)
* [Troubleshooting](docs/TROUBLESHOOTING.md)
* [Build instructions](docs/BUILD.md)
* [Testing](docs/TESTING.md)

## Development
```powershell
pip install -r requirements-dev.txt
python -m pytest
ruff check app tests
```
More than 300 tests run headless with simulated ADB, scrcpy and devices; no emulator or game account is needed.
CI (`.github/workflows/windows.yml`) runs them on Windows and builds the exe.

## Project layout
```
app/
  core/         configuration, logging, background task runner, device and app controllers
  emulator/     ADB client and parsers, adb locator, device selection, reconnect policy,
                BlueStacks discovery, app launcher, emulator launcher
  screen/       scrcpy command builder and process supervisor, screenshots
  pgsharp/      calibration layout, screen-region verification, UI driver, feature registry
  automation/   action models and validation, state machine, engine, executor, session manager
  locations/    location presets and GPX validation and storage
  monitoring/   session history, activity logs, status monitor, repositories
  database/     SQLite connection, schema and migrations
  ui/           PySide6 pages and widgets (no business logic)
tests/          pytest suite and fakes
assets/         icons
docs/           guides
pokepilot.spec  PyInstaller build definition
```
Runtime data lives in `data/` and `logs/` next to the source, or in `%LOCALAPPDATA%\PokePilot` for the packaged
exe. Override the location with `POKEPILOT_HOME`.
