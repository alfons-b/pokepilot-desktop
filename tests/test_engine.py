import threading

from app.automation.engine import ActionOutcome, AutomationSession, SessionListener
from app.automation.models import Action, ActionStatus, ActionType, ErrorPolicy, Profile
from app.automation.state_machine import SessionState
from app.emulator.adb_client import AdbNotFoundError
from tests.fakes.fake_executor import FakeExecutor, disconnect_error, wait_until


def make(*actions, executor=None, **kw):
    states, logs, confirms = [], [], []
    listener = SessionListener(
        on_state=lambda o, n: states.append(n),
        on_log=lambda lvl, m: logs.append((lvl, m)),
        on_confirmation=confirms.append,
    )
    ex = executor or FakeExecutor()
    session = AutomationSession(Profile("p", actions=list(actions)), ex, listener, recover_timeout_s=1,
                                retry_delay_s=0.01, **kw)
    return session, ex, states, logs, confirms


def back(**kw):
    return Action(ActionType.PRESS_BACK, **kw)


def test_happy_path_states_and_counts():
    s, ex, states, _, _ = make(back(), back(), Action.create(ActionType.WAIT, seconds=0.01))
    summary = s.run()
    assert summary.result == "COMPLETED" and summary.succeeded == 3
    assert states == [SessionState.PREPARING, SessionState.RUNNING, SessionState.COMPLETED]
    assert ex.max_concurrent == 1


def test_run_only_once():
    s, *_ = make(back())
    s.run()
    try:
        s.run()
        raise AssertionError("second run should fail")
    except RuntimeError:
        pass


def test_preflight_failure():
    ex = FakeExecutor()
    ex.preflight_errors = ["Device offline"]
    s, _, states, _, _ = make(back(), executor=ex)
    summary = s.run()
    assert summary.result == "FAILED" and "Device offline" in summary.last_error
    assert ex.executed == []
    assert states[-1] is SessionState.FAILED
    assert all(a.status is ActionStatus.CANCELLED for a in s.profile.actions)


def test_failure_policies():
    a1, a2, a3 = back(), back(error_policy=ErrorPolicy.SKIP), back()
    ex = FakeExecutor()
    ex.results[a2.uid] = [ActionOutcome(ActionStatus.FAILED, "missed")]
    s, *_ = make(a1, a2, a3, executor=ex)
    summary = s.run()
    assert summary.result == "COMPLETED" and summary.failed == 1 and a3.status is ActionStatus.SUCCEEDED

    b1, b2 = back(), back()
    ex = FakeExecutor()
    ex.results[b1.uid] = [ActionOutcome(ActionStatus.FAILED, "missed")]
    s, *_ = make(b1, b2, executor=ex)
    summary = s.run()
    assert summary.result == "FAILED" and "missed" in summary.last_error
    assert b2.status is ActionStatus.CANCELLED and b2.uid not in ex.executed


def test_retry_policy():
    a = back(error_policy=ErrorPolicy.RETRY, max_retries=2)
    ex = FakeExecutor()
    ex.results[a.uid] = [ActionOutcome(ActionStatus.FAILED, "x"), ActionOutcome(ActionStatus.FAILED, "y")]
    s, *_ = make(a, executor=ex)
    assert s.run().result == "COMPLETED"
    assert ex.executed.count(a.uid) == 3
    b = back(error_policy=ErrorPolicy.RETRY, max_retries=1)
    ex = FakeExecutor()
    ex.results[b.uid] = [ActionOutcome(ActionStatus.FAILED, "x")] * 2
    s, *_ = make(b, executor=ex)
    assert s.run().result == "FAILED"


def test_unknown_is_not_success_but_not_failure():
    a = back()
    ex = FakeExecutor()
    ex.default = ActionOutcome(ActionStatus.UNKNOWN, "tap sent")
    s, *_ = make(a, executor=ex)
    summary = s.run()
    assert summary.result == "COMPLETED" and summary.unknown == 1 and summary.succeeded == 0


def test_expected_state_upgrades_or_fails():
    a = back(expected_state="menu")
    ex = FakeExecutor()
    ex.default = ActionOutcome(ActionStatus.UNKNOWN, "tap sent")
    s, *_ = make(a, executor=ex)
    s.run()
    assert a.status is ActionStatus.SUCCEEDED
    b = back(expected_state="menu")
    ex = FakeExecutor()
    ex.verify_result = ActionOutcome(ActionStatus.FAILED, "not detected")
    s, *_ = make(b, executor=ex)
    assert s.run().result == "FAILED" and b.status is ActionStatus.FAILED


def test_end_session_skips_rest():
    a, end, c = back(), Action(ActionType.END_SESSION), back()
    s, ex, *_ = make(a, end, c)
    summary = s.run()
    assert summary.result == "COMPLETED" and c.status is ActionStatus.SKIPPED and c.uid not in ex.executed


def _run_async(session):
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("summary", session.run()))
    t.start()
    return t, out


def test_pause_resume_and_graceful_stop():
    gate = threading.Event()
    ex = FakeExecutor()
    ex.on_execute = lambda action: gate.wait(2) if action.params.get("block") else None
    a1 = Action(ActionType.PRESS_BACK, {"block": True})
    a2, a3 = back(), back()
    s, _, states, _, _ = make(a1, a2, a3, executor=ex)
    t, out = _run_async(s)
    assert wait_until(lambda: s.state is SessionState.RUNNING)
    assert s.pause()
    gate.set()
    assert wait_until(lambda: a1.status is ActionStatus.SUCCEEDED)
    import time

    time.sleep(0.1)
    assert a2.status is ActionStatus.PENDING  # paused before a2
    assert s.resume()
    t.join(3)
    assert out["summary"].result == "COMPLETED"

    gate2 = threading.Event()
    ex2 = FakeExecutor()
    ex2.on_execute = lambda action: gate2.wait(2) if action.params.get("block") else None
    b1 = Action(ActionType.PRESS_BACK, {"block": True})
    b2 = back()
    s2, *_ = make(b1, b2, executor=ex2)
    t2, out2 = _run_async(s2)
    assert wait_until(lambda: b1.status is ActionStatus.RUNNING)
    s2.stop()
    gate2.set()
    t2.join(3)
    assert out2["summary"].result == "STOPPED"
    assert b1.status is ActionStatus.SUCCEEDED  # current action finished
    assert b2.status is ActionStatus.CANCELLED
    assert s2.state is SessionState.IDLE


def test_emergency_stop_interrupts_wait():
    w = Action.create(ActionType.WAIT, seconds=30)
    w.timeout_s = 60
    s, *_ = make(w, back())
    t, out = _run_async(s)
    assert wait_until(lambda: w.status is ActionStatus.RUNNING)
    s.emergency_stop()
    t.join(2)
    assert not t.is_alive()
    assert out["summary"].result == "EMERGENCY_STOPPED"
    assert w.status is ActionStatus.CANCELLED


def test_stop_while_paused():
    s, *_ = make(back(), back())
    s.machine.transition(SessionState.PREPARING)  # simulate a running session paused between actions
    s.machine.transition(SessionState.RUNNING)
    s.pause()
    assert s.stop()
    assert s.state is SessionState.STOPPING


def test_user_confirmation():
    c = Action(ActionType.USER_CONFIRMATION, {"message": "Ready?"}, timeout_s=5)
    s, _, _, _, confirms = make(c, back())
    t, out = _run_async(s)
    assert wait_until(lambda: confirms == ["Ready?"])
    s.respond_confirmation(True)
    t.join(3)
    assert out["summary"].result == "COMPLETED"
    d = Action(ActionType.USER_CONFIRMATION, {"message": "Go?"}, timeout_s=5)
    s, _, _, _, confirms = make(d, back())
    t, out = _run_async(s)
    assert wait_until(lambda: bool(confirms))
    s.respond_confirmation(False)
    t.join(3)
    assert out["summary"].result == "FAILED" and "Declined" in out["summary"].last_error


def test_confirmation_timeout():
    c = Action(ActionType.USER_CONFIRMATION, {"message": "?"}, timeout_s=0.5)
    s, *_ = make(c)
    assert s.run().result == "FAILED"


def test_disconnect_recovered_repeats_action():
    a = back()
    ex = FakeExecutor()
    ex.results[a.uid] = [disconnect_error()]
    ex.connected = False
    ex.recovers = True
    s, *_ = make(a, executor=ex)
    assert s.run().result == "COMPLETED"
    assert ex.recover_calls == 1 and ex.executed.count(a.uid) == 2


def test_disconnect_not_recovered_cancels_pending():
    a, b = back(), back()
    ex = FakeExecutor()
    ex.results[a.uid] = [disconnect_error()]
    ex.connected = False
    s, *_ = make(a, b, executor=ex)
    summary = s.run()
    assert summary.result == "FAILED" and "did not come back" in summary.last_error
    assert b.status is ActionStatus.CANCELLED and b.uid not in ex.executed


def test_adb_error_with_device_connected_is_action_failure():
    a = back(error_policy=ErrorPolicy.SKIP)
    ex = FakeExecutor()
    ex.results[a.uid] = [disconnect_error()]
    s, *_ = make(a, executor=ex)
    assert s.run().result == "COMPLETED" and a.status is ActionStatus.FAILED and ex.recover_calls == 0


def test_adb_missing_aborts():
    a = back(error_policy=ErrorPolicy.SKIP)
    ex = FakeExecutor()
    ex.results[a.uid] = [AdbNotFoundError("adb missing")]
    s, *_ = make(a, executor=ex)
    assert s.run().result == "FAILED"


def test_unexpected_exception_is_action_failure():
    a = back()
    ex = FakeExecutor()
    ex.results[a.uid] = [RuntimeError("boom")]
    s, *_ = make(a, executor=ex)
    summary = s.run()
    assert summary.result == "FAILED" and "boom" in summary.last_error
