# ADB Configuration Guide

PokePilot needs an `adb.exe` (Android Debug Bridge) to communicate with your emulator.

## Option A: Google SDK Platform-Tools (recommended)
1. Download *SDK Platform-Tools for Windows*: <https://developer.android.com/tools/releases/platform-tools>.
2. Extract it, for example to `C:\platform-tools\`.
3. In PokePilot, go to **Settings**, then **Browse...**, select `C:\platform-tools\adb.exe`, **Test**, and **Save Settings**.

## Option B: the adb bundled with your emulator
Most emulators ship their own adb. **Auto-detect** checks these common locations:

| Emulator | Typical path |
|---|---|
| BlueStacks 5 | `C:\Program Files\BlueStacks_nxt\HD-Adb.exe` |
| LDPlayer 9 | `C:\LDPlayer\LDPlayer9\adb.exe` |
| MuMu Player 12 | `C:\Program Files\Netease\MuMuPlayer-12.0\shell\adb.exe` |
| Nox | `C:\Program Files (x86)\Nox\bin\nox_adb.exe` |
| MEmu | `C:\Program Files\Microvirt\MEmu\adb.exe` |
| Android Studio | `%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe` |

These are only candidates. PokePilot accepts a path only after `adb version` succeeds.

## Avoid running two different adb versions
Each adb version starts its own background server on port 5037. If two different versions run at
once (for example Platform-Tools and an emulator's bundled adb), they keep restarting each other's
server and devices flicker between *online* and *offline*. Use one adb for everything. If you see
flickering, choose the emulator's bundled adb in PokePilot, or configure the emulator to use
Platform-Tools.

## How auto-detection searches
1. The path already configured.
2. `adb` on the system `PATH`.
3. `%ANDROID_SDK_ROOT%\platform-tools`, `%ANDROID_HOME%\platform-tools`.
4. `%LOCALAPPDATA%\Android\Sdk\platform-tools`.
5. Emulator-bundled locations (table above), then `C:\platform-tools`.
