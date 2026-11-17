# Installation Guide (Windows 10/11)

## 1. Install Python
1. Download Python 3.12 or newer (64-bit) from <https://www.python.org/downloads/windows/>.
2. In the installer, tick **Add python.exe to PATH**, then click *Install Now*.
3. Check the install in a new PowerShell window: `py -3.12 --version`.

## 2. Get the source
Copy or clone the project to a folder, for example `C:\PokePilot`.

## 3. Create a virtual environment and install dependencies
```powershell
cd C:\PokePilot
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

| Dependency | Why | Installed by |
|---|---|---|
| PySide6 | GUI toolkit (Qt 6) | `pip` (requirements.txt) |
| pytest, pytest-qt, ruff | Tests and linting (developers only) | `pip install -r requirements-dev.txt` |
| adb.exe | Talks to the emulator | You. See [ADB_SETUP.md](ADB_SETUP.md) |
| scrcpy | Screen mirroring (Phase 3) | You. Guide added in Phase 3 |

## 4. Start the application
```powershell
python -m app
```
Or double-click `run.bat`.

## Where files are stored
* Development (running from source): `data\config.json` and `logs\pokepilot.log` inside the project.
* Packaged `.exe` (Phase 8): `%LOCALAPPDATA%\PokePilot\`.
* Override either location with the environment variable `POKEPILOT_HOME`.
