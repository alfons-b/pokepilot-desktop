import pytest

from app.automation.models import (
    Action,
    ActionType,
    ErrorPolicy,
    Profile,
    validate_action,
    validate_profile,
)
from app.automation.state_machine import InvalidTransition, SessionState, StateMachine
from app.pgsharp.layout import Availability, FeatureMapping, PgsharpLayout


def layout() -> PgsharpLayout:
    lay = PgsharpLayout()
    lay.add_element("menu", 0.5, 0.5)
    lay.add_state("menu open")
    lay.update_feature(FeatureMapping("teleport", Availability.AVAILABLE, ["menu"], "menu", "menu_open"))
    return lay


@pytest.mark.parametrize("t", list(ActionType))
def test_every_type_has_valid_default(t):
    a = Action.create(t)
    if t in (ActionType.OPEN_SCREEN,):
        a.params["steps"] = "menu"
    if t in (ActionType.SELECT_FEATURE, ActionType.TOGGLE_FEATURE):
        a.params["feature"] = "teleport"
    if t is ActionType.WAIT_FOR_STATE:
        a.params["state"] = "menu_open"
    if t is ActionType.TAP:
        a.params["element"] = "menu"
    assert validate_action(a, layout()) == [], t


def test_tap_requires_element_xor_xy():
    assert validate_action(Action(ActionType.TAP, {}))
    assert validate_action(Action(ActionType.TAP, {"element": "menu", "x": 0.1, "y": 0.1}), layout())
    assert validate_action(Action(ActionType.TAP, {"x": 0.1, "y": 0.2})) == []
    assert any("<= 1.0" in e for e in validate_action(Action(ActionType.TAP, {"x": 1.5, "y": 0.2})))


def test_reference_checks_against_layout():
    lay = layout()
    assert "not calibrated" in validate_action(Action(ActionType.TAP, {"element": "nope"}), lay)[0]
    assert validate_action(Action(ActionType.WAIT_FOR_STATE, {"state": "nope"}, 10), lay)
    assert validate_action(Action(ActionType.OPEN_SCREEN, {"steps": "menu, nope"}), lay) == [
        "UI element 'nope' is not calibrated."
    ]
    lay.update_feature(FeatureMapping("joystick"))
    assert "not mapped" in validate_action(Action(ActionType.SELECT_FEATURE, {"feature": "joystick"}), lay)[0]
    assert "toggle" in validate_action(Action(ActionType.TOGGLE_FEATURE, {"feature": "joystick"}), lay)[0]
    lay.update_feature(FeatureMapping("teleport", Availability.UNAVAILABLE))
    assert "unavailable" in validate_action(Action(ActionType.SELECT_FEATURE, {"feature": "teleport"}), lay)[0]
    a = Action(ActionType.PRESS_BACK, expected_state="nope")
    assert validate_action(a, lay)


def test_param_type_and_policy_checks():
    assert validate_action(Action(ActionType.WAIT, {"seconds": "5"}))
    assert validate_action(Action(ActionType.WAIT, {"seconds": 100}, timeout_s=10))
    assert validate_action(Action(ActionType.WAIT, {"seconds": 1, "bogus": 2}))
    assert validate_action(Action(ActionType.PRESS_BACK, error_policy=ErrorPolicy.RETRY, max_retries=0))
    assert validate_action(Action(ActionType.PRESS_BACK, timeout_s=0))
    assert validate_action(Action(ActionType.LAUNCH_APP, {"package": "bad pkg"}))
    assert validate_action(Action(ActionType.WAIT_FOR_STATE, {"state": "x"}, expected_state="x"))


def test_profile_validation_and_json_roundtrip():
    p = Profile("Daily", "desc", [Action.create(ActionType.WAIT, seconds=2), Action.create(ActionType.PRESS_BACK)])
    assert validate_profile(p) == []
    assert validate_profile(Profile("", actions=[])) == ["Profile name is required.", "Profile has no actions."]
    copy = Profile.from_json(p.to_json())
    assert copy.name == "Daily" and [a.type for a in copy.actions] == [a.type for a in p.actions]
    assert copy.actions[0].uid != p.actions[0].uid
    for bad in ["{", "[]", '{"format": "other"}', '{"format": "pokepilot-profile", "version": 99, "name": "x"}',
                '{"format": "pokepilot-profile", "version": 1, "name": ""}',
                '{"format": "pokepilot-profile", "version": 1, "name": "x", "actions": [{"type": "NOPE"}]}']:
        with pytest.raises(ValueError):
            Profile.from_json(bad)


def test_state_machine_transitions():
    seen = []
    sm = StateMachine(lambda o, n: seen.append((o, n)))
    for s in (SessionState.PREPARING, SessionState.RUNNING, SessionState.PAUSED, SessionState.RUNNING,
              SessionState.STOPPING, SessionState.IDLE):
        sm.transition(s)
    assert len(seen) == 6
    with pytest.raises(InvalidTransition):
        sm.transition(SessionState.RUNNING)  # IDLE -> RUNNING skips PREPARING
    assert not sm.try_transition(SessionState.COMPLETED)
    sm.transition(SessionState.PREPARING)
    sm.transition(SessionState.FAILED)
    with pytest.raises(InvalidTransition):
        sm.transition(SessionState.RUNNING)
    sm.transition(SessionState.IDLE)
