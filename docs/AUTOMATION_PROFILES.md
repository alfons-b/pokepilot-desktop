# Automation Profiles

A **profile** is an ordered list of **actions** that PokePilot runs one at a time on the selected device. Profiles
are stored in the local SQLite database (`data\pokepilot.db`) and can be exported and imported as JSON.

Automation only uses on-screen, user-facing interactions: taps, swipes, the BACK key and app launches. It has no
randomization, stealth or detection-evasion behaviour, by design.

## Before you start
1. Select an online device (Emulator Manager).
2. Set the target app (Emulator Manager > Applications) if you use `LAUNCH_APP` without a package.
3. Calibrate the elements, states and features your actions refer to (PGSharp Controller,
   see [PGSHARP_SETUP.md](PGSHARP_SETUP.md)).

The action list shows **"Profile is valid"** or a list of problems. A session cannot start while problems remain.

## Action types
| Type | Parameters | Result when nothing is verified |
|---|---|---|
| `LAUNCH_APP` | `package` (empty = target app) | SUCCEEDED only if the app process is running |
| `WAIT` | `seconds` | SUCCEEDED |
| `SCREENSHOT` | `label` (optional) | SUCCEEDED when the PNG is saved |
| `TAP` | `element` **or** `x` + `y` (0-1) | UNKNOWN |
| `SWIPE` | `x1, y1, x2, y2` (0-1), `duration_ms` | UNKNOWN |
| `PRESS_BACK` | - | UNKNOWN |
| `OPEN_SCREEN` | `steps`: element ids, comma separated | UNKNOWN |
| `SELECT_FEATURE` | `feature` | From the feature's verify state: SUCCEEDED, FAILED or UNKNOWN |
| `TOGGLE_FEATURE` | `feature` (needs a toggle element) | As above |
| `WAIT_FOR_STATE` | `state`, `poll_s` | SUCCEEDED when detected, FAILED on timeout |
| `USER_CONFIRMATION` | `message` | SUCCEEDED on Yes; FAILED on No or timeout |
| `END_SESSION` | - | Ends the session successfully; later actions are SKIPPED |

## Common fields
* **Timeout**: the maximum time for the action, including its verification.
* **Expected state**: after the action, PokePilot waits up to the timeout for this calibrated screen. If it
  appears, the action becomes **SUCCEEDED**; if not, **FAILED**. This is how a tap becomes *verified*.
* **On error**:
  * `STOP` ends the session as FAILED.
  * `SKIP` records the failure and continues.
  * `RETRY` repeats the action up to **Retries** times, then stops.

## Status meanings
| Status | Meaning |
|---|---|
| PENDING | Not started |
| RUNNING | Executing now |
| SUCCEEDED | Verified (or inherently certain, like WAIT) |
| UNKNOWN | The command was sent but its effect was **not verified**. It is not counted as a success |
| FAILED | Verification failed, an error occurred, or the user declined |
| SKIPPED | After END_SESSION |
| CANCELLED | Never ran because the session stopped or failed first |

Session results report succeeded, unverified, failed and cancelled counts. They are **controller action counts,
not game statistics**.

## Running
| Control | Behaviour |
|---|---|
| Start | Pre-checks: device online, profile valid, screen matches calibration. Then runs actions in order |
| Pause | Takes effect after the current action |
| Resume | Continues with the next action |
| Stop | Finishes the current action, then stops (result STOPPED) |
| Emergency Stop | Interrupts waits and verifications immediately (result EMERGENCY_STOPPED) |

The same controls are on the Dashboard; they run the profile selected in Automation Manager.

Safety rules:
* **Only one session at a time.** A second start is refused, and actions never run in parallel.
* While a profile is running, it cannot be edited.
* If you select another device during a session, the session stops.
* If the device disconnects, PokePilot tries to reconnect for 30 s. On success the interrupted action is
  repeated once; otherwise the session fails and the remaining actions are CANCELLED.
* Closing PokePilot during a session asks first, then emergency-stops it.
* A session that was cut off by a crash is shown as INTERRUPTED in the history.

## Example: open the teleport dialog after confirmation
1. `LAUNCH_APP` (target app), timeout 30 s
2. `WAIT_FOR_STATE` state `map_screen`, timeout 60 s
3. `USER_CONFIRMATION` "Open teleport?"
4. `SELECT_FEATURE` feature `teleport`, on error `RETRY` x2
5. `SCREENSHOT` label `teleport_open`

## JSON format
```json
{
  "format": "pokepilot-profile",
  "version": 1,
  "name": "Example",
  "description": "",
  "actions": [
    {"type": "WAIT", "params": {"seconds": 2}, "timeout_s": 10, "expected_state": null,
     "error_policy": "STOP", "max_retries": 0}
  ]
}
```
Imported profiles get fresh action ids and a unique name. Element, state and feature references are checked
against *your* calibration, and problems are listed after import.
