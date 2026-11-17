# Troubleshooting

| Symptom | Cause / fix |
|---|---|
| ADB **Not configured** | No adb path set. Settings > Auto-detect, or Browse to `adb.exe`. |
| ADB **Not found** | The configured file is missing or cannot run. Re-select it and press **Test**. |
| ADB **Timed out** | adb did not answer in time. Restart ADB Server; increase *Command timeout*; check that antivirus is not blocking adb. |
| No devices listed | Emulator not running, or ADB disabled in it, or it needs `adb connect` (see [EMULATOR_COMPATIBILITY.md](EMULATOR_COMPATIBILITY.md)). |
| `Connect failed: ... refused` | Wrong port, or ADB is disabled in the emulator. |
| BlueStacks not listed after restarting the ADB server | Expected: TCP connections end when the server restarts. Auto-reconnect restores the preferred device within about 10 s, or press **Reconnect**. |
| Emulator Instances: "No BlueStacks configuration was found" | BlueStacks installed in a custom data folder. Set *Settings > Emulator > BlueStacks config* to its `bluestacks.conf`. |
| Launch: "Android rejected the launch" | The package has no launchable activity, or it is not installed on the selected device. |
| Launch: "accepted, but ... not running" | The app crashed or closed on start. Open it manually in the emulator to see why. |
| Device **offline** | Restart ADB Server. If it persists, restart the emulator. |
| Device **unauthorized** | Accept the "Allow USB debugging" prompt inside the emulator. |
| Devices flicker online/offline | Two different adb versions are running. See [ADB_SETUP.md](ADB_SETUP.md#avoid-running-two-different-adb-versions). |
| "Configuration recovered" on start | `config.json` was unreadable. It was renamed to `config.json.corrupt-<time>` and defaults were loaded. Re-enter your settings. |
| `Activate.ps1 cannot be loaded` | Run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, or use `run.bat`. |
| `py` is not recognized | Reinstall Python with "Add to PATH", or use the full path to `python.exe`. |

Logs: `logs\pokepilot.log` (source checkout) or `%LOCALAPPDATA%\PokePilot\logs\` (packaged app).
Set *Log level* to DEBUG in Settings to record every adb command.
