# Testing

```powershell
pip install -r requirements-dev.txt
python -m pytest
```
GUI tests run headless (`QT_QPA_PLATFORM=offscreen` is set automatically). No real device, emulator, scrcpy
or game account is used. Devices are simulated by:
* `tests/fakes/fake_runner.py`: in-memory ADB responses,
* `tests/fakes/fake_adb.py` and `fake_scrcpy.py`: real executables, run through real subprocesses / QProcess,
  with scenarios selected by environment variables,
* `tests/fakes/fake_device.py`: scripted screenshots for UI verification,
* `tests/fakes/fake_executor.py`: a scriptable automation executor.

Every test gets its own temporary `POKEPILOT_HOME`, so your real settings and data are never touched.

## Required scenarios and where they are covered
| Requirement | Tests |
|---|---|
| ADB device parsing | `test_adb_parser.py` |
| Device selection | `test_selection.py`, `test_device_controller.py` |
| Configuration persistence | `test_config.py`, `test_ui.py::test_settings_*` |
| Database operations | `test_database.py`, `test_monitoring.py`, `test_locations.py` |
| Profile CRUD | `test_database.py::test_profile_crud`, `test_ui.py::test_automation_page_profile_flow` |
| Action validation | `test_automation_models.py` |
| Automation state transitions | `test_automation_models.py::test_state_machine_transitions`, `test_engine.py` |
| Session cancellation | `test_engine.py` (stop, emergency stop, stop while paused), `test_session_manager.py` |
| Error handling | `test_engine.py` (policies, retries, exceptions), `test_executor.py`, `test_adb_client.py` |
| No / one / multiple devices | `test_integration_adb.py::test_list_devices_via_subprocess`, `test_device_controller.py` |
| ADB failure | `test_integration_adb.py::test_adb_failure_via_subprocess`, `test_adb_hang_times_out`, `test_controller_missing_adb_executable` |
| scrcpy failure | `test_mirror.py::test_crash_*`, `test_silent_process_reported_unconfirmed` |
| Emulator restart / reconnection | `test_integration_adb.py::test_controller_end_to_end_emulator_restart`, `test_phase2_controllers.py`, `test_engine.py::test_disconnect_*` |
| GUI responsiveness during background work | `test_ui.py::test_gui_responsive_during_slow_adb`, `test_task_runner.py` |
| Application restart | `test_ui.py::test_application_restart_restores_settings`, `test_interrupted_session_marked_on_restart` |
| Corrupted configuration | `test_config.py::test_corrupted_*`, `test_ui.py::test_corrupted_config_*`, `test_corrupted_database_*`, `test_pgsharp_layout.py::test_store_corrupt_*` |

## Continuous integration
`.github/workflows/windows.yml` runs the linter and all tests on `windows-latest`, builds the exe, and
smoke-tests it.

## Manual acceptance checklist (real BlueStacks)
1. Settings: ADB auto-detect, then Test. scrcpy auto-detect, then Test.
2. Emulator Instances: Scan, Connect, Use as Default. The device appears and is selected.
3. Restart ADB Server: the device disappears and is reconnected automatically within about 10 s.
4. Screen Monitor: Start Mirroring; clicks and typing work; Stop.
5. Applications: Load Apps, set PGSharp as the target, Launch: state is *Running*.
6. PGSharp Controller: Capture, add elements and states, Verify Screen, Test Feature.
7. Automation: build a 3-action profile and run it; try Pause, Resume and Emergency Stop.
8. Activity Monitor: the session appears in the history with its log.
