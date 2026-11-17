# PokePilot Desktop

A Windows desktop controller for an **existing** Android emulator, built with Python and PySide6.
PokePilot talks to the emulator only through **ADB** (and, from Phase 3, **scrcpy**). It does not
include or modify an emulator, does not modify any APK, and does not touch game network traffic.

> **Status: Phase 4 of 8 complete (v0.4.0).** Device management, BlueStacks support, the app launcher,
> scrcpy mirroring and PGSharp UI calibration and verification are working. The other modules are listed in the app as scheduled for later phases. See
> [CHANGELOG.md](CHANGELOG.md).

## What works today

| Area | Working in v0.1.0 |
|---|---|
| Navigation | Sidebar with all 8 sections, status bar showing ADB and device state |
| Dashboard | Live ADB and device status, recent activity log. Session buttons are present but disabled until Phase 5 |
| Emulator Manager: Devices | Device scan (`adb devices -l`), multi-device table, device selection, TCP/IP connect, manual and automatic reconnection, restart ADB server, launch your emulator, read Android version, API level and screen resolution |
| Emulator Manager: Applications | List installed apps, choose a target app (for example your PGSharp install), launch it and confirm its process is running, check running state, force stop |
| Emulator Manager: Emulator Instances | Finds BlueStacks 5 instances and their ADB ports in `bluestacks.conf`; connect, launch or set as default |
| Screen Monitor | scrcpy mirroring with mouse and keyboard control, options (size, FPS, bitrate, fullscreen, view-only), crash auto-restart, screenshots |
| PGSharp Controller | Launch and check PGSharp; calibrate tap targets and screen states on a screenshot; map and test features; layout change warnings |
| Settings | ADB path (browse / auto-detect / test), command timeout, auto-refresh, emulator executable and arguments, scrcpy path (stored for Phase 3), log level |
| Activity Monitor | Live, filterable application log; opens the log folder |
| Reliability | All ADB work runs on background threads; JSON config is validated, saved atomically, and backed up and reset if it is corrupted |

## Requirements

* Windows 10 or 11, 64-bit
* Python **3.12 or newer**: <https://www.python.org/downloads/>. Tick *"Add python.exe to PATH"* in the installer.
* An Android emulator you already have installed, with ADB access. See
  [docs/EMULATOR_COMPATIBILITY.md](docs/EMULATOR_COMPATIBILITY.md).
* An `adb.exe`: either Google's *SDK Platform-Tools* or the copy bundled with your emulator. See
  [docs/ADB_SETUP.md](docs/ADB_SETUP.md).

## Run on Windows

Open **PowerShell** in the project folder (the folder that contains `README.md`):

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m app
```

If PowerShell refuses to run `Activate.ps1`, run this once:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`. Alternatively, double-click **`run.bat`**,
which creates the virtual environment on first use and starts the app.

On first start PokePilot tries to auto-detect ADB. If it cannot find it, open **Settings**, then
**Browse...** to your `adb.exe`, **Test**, and **Save Settings**.

### First connection checklist (BlueStacks users: see [docs/BLUESTACKS_SETUP.md](docs/BLUESTACKS_SETUP.md))

1. Start your emulator and wait for the Android home screen.
2. Make sure ADB is enabled in the emulator's settings. Some emulators require this to be switched on.
3. In PokePilot, open **Emulator Manager** and press **Refresh**.
4. If no device appears, enter the emulator's ADB address under *Connect over TCP/IP*
   (for example `127.0.0.1:5555`) and press **Connect**.
5. Select the device in the table and press **Read Device Info** to confirm communication.

## Running the tests

```powershell
pip install -r requirements-dev.txt
python -m pytest
```

The tests do not need a real device. They use an in-memory fake ADB runner and, for integration
tests, a fake `adb` executable (`tests/fakes/fake_adb.py`) run through real subprocesses.

## Project layout

```
app/
  core/         config, logging, background task runner, device controller
  emulator/     ADB client, output parsers, ADB locator, device selection, emulator launcher
  screen/       (Phase 3) scrcpy integration
  pgsharp/      (Phase 4) PGSharp UI integration
  automation/   (Phase 5) automation engine
  locations/    (Phase 6) locations and GPX
  monitoring/   (Phase 7) session monitoring
  database/     (Phase 7) SQLite
  ui/           PySide6 windows, pages and widgets (no business logic)
tests/          pytest suite and fakes
data/           config.json (created at runtime; dev mode)
logs/           rotating log files (dev mode)
assets/         icons
docs/           guides
```

When packaged with PyInstaller (Phase 8), runtime data goes to `%LOCALAPPDATA%\PokePilot`.
Set the `POKEPILOT_HOME` environment variable to override the location.

## Documentation

* [Installation guide](docs/INSTALLATION.md)
* [ADB configuration](docs/ADB_SETUP.md)
* [Existing emulator compatibility](docs/EMULATOR_COMPATIBILITY.md)
* [BlueStacks setup](docs/BLUESTACKS_SETUP.md)
* [User manual](docs/USER_MANUAL.md)
* [Troubleshooting](docs/TROUBLESHOOTING.md)
* [scrcpy setup](docs/SCRCPY_SETUP.md)
* [PGSharp setup and calibration](docs/PGSHARP_SETUP.md)
* Automation profiles, automation profiles and build instructions are added in their phases.

## Scope and responsible use

PokePilot automates only **user-facing UI** through standard Android tooling. It contains no
stealth, anti-detection, APK modification, traffic manipulation or private-API features, and it
never stores game account credentials. Third-party apps such as PGSharp may violate the game's
terms of service. That risk to your account is yours to assess.
