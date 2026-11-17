# PGSharp Setup and Calibration

PokePilot controls PGSharp **only through its on-screen UI**, the same way you would with a mouse. It does not
modify, inspect or patch the PGSharp APK. Because PGSharp's layout differs between versions, editions (free or
premium) and screen sizes, **you calibrate it once**: you show PokePilot where the buttons are and what each screen
looks like.

> Using PGSharp may violate Pokémon GO's Terms of Service, and your account can be banned. PokePilot adds no
> protection against that and contains no anti-detection features.

## 1. Choose the PGSharp app
Go to **Emulator Manager > Applications > Load Apps**, select your PGSharp installation, and press
**Set as Target App**. PokePilot never guesses the package name. **PGSharp Controller > Launch PGSharp** then
starts it and confirms the process is running.

## 2. Keep the display fixed
Calibration is stored relative to the screen size (as fractions of width and height), so it survives scaling. It
does **not** survive a change of aspect ratio or orientation. If the screen no longer matches, PokePilot shows a
"Recalibrate" warning and refuses to add points to a mismatched calibration.

## 3. UI elements (tap targets)
1. Open the PGSharp screen that contains the button, and press **Capture**.
2. **UI Elements > Add**, then click the button's position on the screenshot and give it a name, for example
   *PGSharp menu*, *Teleport*, *Autowalk toggle*.
3. Use **Test Tap** to send a real tap and check that it hits the right place. **Move** re-positions an element.

## 4. Screen states (verification)
A screen state is "what the screen looks like when X is open". Each state has one or more reference
**regions**. Choose parts of the screen that only appear on that screen, such as a dialog title or a panel
header, and avoid areas that change, like the map or Pokémon.

1. Open that screen in PGSharp and press **Capture**.
2. **Screen States > New State**, give it a name (for example *Teleport dialog*). *Draw region* is switched on.
3. Drag a rectangle over the distinctive area. Add 1 to 3 regions per state.
4. **Verify Screen** shows which states match the current screen, with a difference score. If a correct screen
   fails narrowly, raise the **Match threshold** a little (default 0.12). If wrong screens match, lower it or pick
   a more distinctive region.

## 5. Features
For each feature (Joystick, Teleport, Autowalk, Custom GPX, Nearby Radar, Quick Catch, Virtual GO Plus,
Auto Transfer, Auto Discard, Auto Incubator):

| Field | Meaning |
|---|---|
| Availability | *Unverified* by default. Set *Available* or *Unavailable* after checking your PGSharp. The free edition does not include every feature, and automation refuses features marked *Unavailable*. |
| Open steps | Element ids to tap, in order, to open the feature, for example `pgsharp_menu, teleport` |
| Toggle element | For on/off features, the switch to tap |
| Verify state | The screen state that proves the feature opened |

**Test Feature** taps the steps, then checks the verify state. Results:
* **Success**: the expected screen was detected.
* **Failed**: the expected screen was not detected, so the tap probably missed or the UI changed.
* **Unknown**: the taps were sent but no verify state is set, so nothing was confirmed.

## Layout change detection
If no calibrated state matches 3 verifications in a row, PokePilot warns that PGSharp's UI may have changed (for
example after an update). Recalibrate the affected elements and states.

## Files
Calibration is saved in `data\pgsharp_layout.json`. Back it up to keep your calibration. If the file is damaged,
it is renamed to `pgsharp_layout.json.corrupt-<time>` and an empty calibration is started.
