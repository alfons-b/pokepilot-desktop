# Existing Emulator Compatibility

PokePilot works with **any** Android environment that ADB can reach. It does not assume a brand.

## Requirements
* ADB access enabled in the emulator. Many emulators have a setting such as
  *Settings > Advanced > Android Debug Bridge*. In AVD and Genymotion it is always on.
* The emulator reaches the `device` state in `adb devices`.
* Android 7.0 or newer is recommended. scrcpy requires Android 5.0 or newer.

## How emulators appear in ADB
| Kind | Serial shown | What to do |
|---|---|---|
| Android Studio AVD and other QEMU-based emulators | `emulator-5554` | Appears automatically |
| Emulators exposing ADB over TCP | `127.0.0.1:<port>` | Use **Connect** in Emulator Manager once per ADB server start |

Common local ports (check your emulator's own settings, because ports change with multiple instances):

| Emulator | Port(s) |
|---|---|
| BlueStacks 5 | 5555, 5565, 5575... (shown in its ADB setting) |
| MuMu Player 12 | 16384, 16416... (older MuMu: 7555) |
| Nox | 62001, 62025... |
| MEmu | 21503, 21513... |
| LDPlayer | usually `emulator-5554` automatically |

## The "Emulator hint" column
PokePilot marks a device as *Likely emulator* when its serial is `emulator-NNNN` or a loopback
address. This is a hint, not proof. **QEMU flag** under Device Information reports whether the
emulator sets `ro.kernel.qemu`. Many commercial emulators do not.

## Launching the emulator from PokePilot
Set **Settings > Emulator > Executable** to your emulator's launcher and optionally add
**Arguments**, for example an instance name. **Emulator Manager > Launch Emulator** starts it
detached. It can take a minute before the emulator shows up in ADB.
