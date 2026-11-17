# scrcpy Setup

[scrcpy](https://github.com/Genymobile/scrcpy) mirrors the emulator screen in its own window and forwards your
mouse and keyboard. PokePilot starts, monitors and stops it.

## Install (Windows)
Choose one:
* **Zip:** download `scrcpy-win64-vX.Y.zip` from <https://github.com/Genymobile/scrcpy/releases>, then extract it
  to `C:\scrcpy\`.
* **winget:** `winget install --exact Genymobile.scrcpy`
* **scoop:** `scoop install scrcpy`

Then go to **Settings > Screen Mirroring (scrcpy) > Auto-detect** (or **Browse...** to `scrcpy.exe`), then **Test**.
scrcpy 2.0 or newer is recommended. Older versions work with fewer options.

## Same adb for everything
PokePilot starts scrcpy with the environment variable `ADB=<your configured adb>`, so scrcpy uses the same adb as
PokePilot. This prevents two adb versions from repeatedly restarting each other's server. scrcpy's zip bundles its
own `adb.exe`, but that copy is not used.

## Screen Monitor page
| Control | Effect |
|---|---|
| Start / Stop / Restart | Start or stop the scrcpy window for the selected device |
| Max size | Longest side of the mirrored image (Native = no scaling) |
| Frame rate, Bitrate | Lower values use less CPU and bandwidth |
| Fullscreen, Always on top | Window options |
| Keep device awake | `--stay-awake` |
| View only | `--no-control`: mirror only, no mouse or keyboard input |
| UHID keyboard | Physical keyboard simulation (scrcpy 2.4+) |
| Restart automatically | Restarts after a crash, at most 3 times in 2 minutes |

Option changes apply the next time mirroring starts.

Status values:
* *Starting*: the process has launched.
* *Running*: scrcpy reported that its video window opened. If scrcpy prints nothing for 8 s while its
  process stays alive, the status reads *"window not confirmed"*.
* *Failed*: shows scrcpy's last error line.

## Mouse and keyboard in the scrcpy window
| Input | Action |
|---|---|
| Left click / drag | Tap / swipe |
| Right click | BACK |
| Middle click | HOME |
| Typing | Text input |
| Alt+F | Toggle fullscreen |
| Alt+Up / Alt+Down | Volume |

## Screenshots
**Capture Screenshot** runs `adb exec-out screencap -p` and saves a PNG to `data\screenshots\`. It does not need
scrcpy. Screenshots are also used for PGSharp calibration and screen verification.

## Troubleshooting
| Symptom | Fix |
|---|---|
| "Could not open video stream" / encoder errors | Lower *Max size* to 1024 and *Bitrate* to 4 Mbps; restart BlueStacks. |
| Window opens and closes immediately | Check the *scrcpy Output* box; usually the device is offline or unauthorized. |
| Black window on BlueStacks | In BlueStacks Settings > Graphics, try switching the graphics renderer, then restart. |
