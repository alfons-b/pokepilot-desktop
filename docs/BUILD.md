# Build Instructions

## Option 1: download the build from GitHub (no setup)
Every push to `main` triggers the **Windows test & build** workflow (`.github/workflows/windows.yml`). On a
Windows machine it:
1. installs the dependencies,
2. lints the code and runs the full pytest suite,
3. builds `PokePilot.exe` with PyInstaller,
4. smoke-tests the packaged exe (starts it and checks that it exits cleanly),
5. uploads the build as an artifact.

To download it: open the repository on GitHub, go to **Actions**, choose the latest successful
**Windows test & build** run, and under **Artifacts** download **PokePilot-windows-x64** (a zip).
Extract it anywhere and run `PokePilot.exe`.

## Option 2: build locally
Requirements: Windows 10/11 x64 and Python 3.12+ (with the `py` launcher).

```powershell
powershell -ExecutionPolicy Bypass -File .\build_windows.ps1
```

The script:
1. creates `.venv`,
2. installs `requirements-dev.txt` and `requirements-build.txt`,
3. runs the tests (add `-SkipTests` to skip them),
4. builds with `pokepilot.spec`,
5. zips the result.

Output:
* `dist\PokePilot\PokePilot.exe` (a one-folder build: keep the whole `PokePilot` folder together)
* `dist\PokePilot-win64.zip`

Manual equivalent:
```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-build.txt
pyinstaller --noconfirm --clean pokepilot.spec
```

## Verify a build
```powershell
$env:POKEPILOT_HOME = "$env:TEMP\pokepilot-smoke"
Start-Process dist\PokePilot\PokePilot.exe -ArgumentList "--smoke-test" -Wait -PassThru
```
An exit code of 0 means the app started, built every page, opened its database and closed cleanly.

## Where the packaged app stores data
`%LOCALAPPDATA%\PokePilot\`:
* `data\config.json`: settings
* `data\pokepilot.db`: profiles, locations, history
* `data\pgsharp_layout.json`: calibration
* `data\screenshots\`, `data\gpx\`
* `logs\pokepilot.log`

Set `POKEPILOT_HOME` to use another folder (for example a portable USB copy).

## External tools are not bundled
`adb.exe` and `scrcpy.exe` are configured in Settings and are not shipped inside PokePilot, so you can update
them independently. See [ADB_SETUP.md](ADB_SETUP.md) and [SCRCPY_SETUP.md](SCRCPY_SETUP.md).

## Notes
* Antivirus tools sometimes flag new, unsigned PyInstaller executables. The one-folder build reduces this.
  Building from source yourself is the most trustworthy option.
* The `.spec` excludes unused Qt modules (WebEngine, QML, Multimedia, ...) to keep the size down.
