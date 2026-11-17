# BlueStacks 5 Setup

These steps apply to the current BlueStacks 5 releases and MSI App Player.

## 1. Enable ADB in BlueStacks
1. Open BlueStacks and click the **gear icon** (Settings).
2. Go to **Advanced**.
3. Turn on **Android Debug Bridge (ADB)**.
4. Note the address shown underneath, for example `127.0.0.1:5555`. Each instance has its own port
   (5555, 5565, 5575, ...).
5. Click **Save changes**. Restart the instance if BlueStacks asks you to.

## 2. Point PokePilot at an adb
Either works:
* Google's Platform-Tools `adb.exe` (recommended), or
* BlueStacks' own `C:\Program Files\BlueStacks_nxt\HD-Adb.exe`. **Auto-detect** finds it.

Use only one of them. Two different adb versions running at the same time make devices flicker
between online and offline (see [ADB_SETUP.md](ADB_SETUP.md)).

## 3. Connect
* **Easiest:** Emulator Manager > **Emulator Instances** > **Scan**, select your instance, then
  **Connect**. Press **Use as Default** to also make it the emulator PokePilot launches and reconnects.
* **Manually:** Devices tab > *Connect over TCP/IP* > enter `127.0.0.1:5555` > **Connect**.

BlueStacks appears as serial `127.0.0.1:5555` in the device table. Select it.

## Why reconnection matters for BlueStacks
BlueStacks exposes ADB only over TCP. The connection ends when:
* the ADB server restarts (*Restart ADB Server*, another tool running `adb kill-server`, or a PC sleep), or
* the BlueStacks instance restarts.

PokePilot remembers your preferred device and reconnects it automatically (Settings > Device
Detection > *Automatically reconnect*).

## Display settings for later phases
Screen calibration (PGSharp Controller) records coordinates relative to the resolution. To avoid re-calibrating,
keep BlueStacks' **Display resolution** and **orientation** unchanged after you calibrate.

## Notes
* The BlueStacks data folder is normally `C:\ProgramData\BlueStacks_nxt`. PokePilot only **reads**
  `bluestacks.conf` and never modifies it.
* If you installed BlueStacks' data in a custom folder, set *Settings > Emulator > BlueStacks config*.
