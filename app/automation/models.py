"""Automation profile and action models, parameter schemas and validation."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.emulator.app_launcher import validate_package_name
from app.pgsharp.layout import Availability, PgsharpLayout

PROFILE_FORMAT = "pokepilot-profile"
PROFILE_FORMAT_VERSION = 1
MAX_TIMEOUT_S = 3600.0
MAX_RETRIES = 5


class ActionType(StrEnum):
    LAUNCH_APP = "LAUNCH_APP"
    WAIT = "WAIT"
    SCREENSHOT = "SCREENSHOT"
    TAP = "TAP"
    SWIPE = "SWIPE"
    PRESS_BACK = "PRESS_BACK"
    OPEN_SCREEN = "OPEN_SCREEN"
    SELECT_FEATURE = "SELECT_FEATURE"
    TOGGLE_FEATURE = "TOGGLE_FEATURE"
    WAIT_FOR_STATE = "WAIT_FOR_STATE"
    USER_CONFIRMATION = "USER_CONFIRMATION"
    END_SESSION = "END_SESSION"


class ErrorPolicy(StrEnum):
    STOP = "STOP"  # fail the session
    SKIP = "SKIP"  # record the failure and continue
    RETRY = "RETRY"  # retry up to max_retries, then stop


class ActionStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"  # command sent, effect not verified
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class ParamSpec:
    name: str
    kind: str  # float | int | str | element | state | feature | package | steps
    required: bool = True
    default: Any = None
    minimum: float | None = None
    maximum: float | None = None
    help: str = ""


_NORM = {"minimum": 0.0, "maximum": 1.0}
PARAM_SCHEMA: dict[ActionType, tuple[ParamSpec, ...]] = {
    ActionType.LAUNCH_APP: (ParamSpec("package", "package", False, "", help="Empty = the target app"),),
    ActionType.WAIT: (ParamSpec("seconds", "float", True, 1.0, 0.1, MAX_TIMEOUT_S),),
    ActionType.SCREENSHOT: (ParamSpec("label", "str", False, ""),),
    ActionType.TAP: (
        ParamSpec("element", "element", False, "", help="Calibrated element, or use x/y"),
        ParamSpec("x", "float", False, None, **_NORM),
        ParamSpec("y", "float", False, None, **_NORM),
    ),
    ActionType.SWIPE: (
        ParamSpec("x1", "float", True, 0.5, **_NORM),
        ParamSpec("y1", "float", True, 0.7, **_NORM),
        ParamSpec("x2", "float", True, 0.5, **_NORM),
        ParamSpec("y2", "float", True, 0.3, **_NORM),
        ParamSpec("duration_ms", "int", True, 300, 50, 10000),
    ),
    ActionType.PRESS_BACK: (),
    ActionType.OPEN_SCREEN: (ParamSpec("steps", "steps", True, "", help="Element ids to tap, comma separated"),),
    ActionType.SELECT_FEATURE: (ParamSpec("feature", "feature", True, ""),),
    ActionType.TOGGLE_FEATURE: (ParamSpec("feature", "feature", True, ""),),
    ActionType.WAIT_FOR_STATE: (
        ParamSpec("state", "state", True, ""),
        ParamSpec("poll_s", "float", False, 1.0, 0.2, 60),
    ),
    ActionType.USER_CONFIRMATION: (ParamSpec("message", "str", True, "Continue?"),),
    ActionType.END_SESSION: (),
}

DEFAULT_TIMEOUTS: dict[ActionType, float] = {
    ActionType.LAUNCH_APP: 30.0,
    ActionType.WAIT: 60.0,
    ActionType.WAIT_FOR_STATE: 30.0,
    ActionType.USER_CONFIRMATION: 300.0,
}


def new_uid() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class Action:
    type: ActionType
    params: dict[str, Any] = field(default_factory=dict)
    timeout_s: float = 10.0
    expected_state: str | None = None
    error_policy: ErrorPolicy = ErrorPolicy.STOP
    max_retries: int = 0
    uid: str = field(default_factory=new_uid)
    status: ActionStatus = ActionStatus.PENDING  # runtime only

    @classmethod
    def create(cls, type_: ActionType, **params: Any) -> Action:
        defaults = {p.name: p.default for p in PARAM_SCHEMA[type_] if p.default not in (None, "")}
        defaults.update(params)
        return cls(type_, defaults, DEFAULT_TIMEOUTS.get(type_, 10.0))

    def summary(self) -> str:
        p = self.params
        t = self.type
        if t is ActionType.TAP:
            return p.get("element") or f"({p.get('x')}, {p.get('y')})"
        if t is ActionType.SWIPE:
            return f"({p.get('x1')},{p.get('y1')}) -> ({p.get('x2')},{p.get('y2')}) {p.get('duration_ms')} ms"
        if t is ActionType.WAIT:
            return f"{p.get('seconds')} s"
        key = {"LAUNCH_APP": "package", "SCREENSHOT": "label", "OPEN_SCREEN": "steps", "SELECT_FEATURE": "feature",
               "TOGGLE_FEATURE": "feature", "WAIT_FOR_STATE": "state", "USER_CONFIRMATION": "message"}.get(t.value)
        value = p.get(key, "") if key else ""
        return str(value) if value else ("target app" if t is ActionType.LAUNCH_APP else "")

    def to_dict(self) -> dict[str, Any]:
        return {
            "uid": self.uid,
            "type": self.type.value,
            "params": dict(self.params),
            "timeout_s": self.timeout_s,
            "expected_state": self.expected_state,
            "error_policy": self.error_policy.value,
            "max_retries": self.max_retries,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Action:
        try:
            return cls(
                type=ActionType(d["type"]),
                params=dict(d.get("params") or {}),
                timeout_s=float(d.get("timeout_s", 10.0)),
                expected_state=d.get("expected_state") or None,
                error_policy=ErrorPolicy(d.get("error_policy", ErrorPolicy.STOP)),
                max_retries=int(d.get("max_retries", 0)),
                uid=str(d.get("uid") or new_uid()),
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise ValueError(f"Invalid action: {exc}") from exc


@dataclass
class Profile:
    name: str
    description: str = ""
    actions: list[Action] = field(default_factory=list)
    id: int | None = None

    def to_export(self) -> dict[str, Any]:
        return {
            "format": PROFILE_FORMAT,
            "version": PROFILE_FORMAT_VERSION,
            "name": self.name,
            "description": self.description,
            "actions": [a.to_dict() for a in self.actions],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_export(), indent=2)

    @classmethod
    def from_json(cls, text: str) -> Profile:
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise ValueError(f"Not valid JSON: {exc}") from exc
        if not isinstance(data, dict) or data.get("format") != PROFILE_FORMAT:
            raise ValueError("Not a PokePilot profile file.")
        if int(data.get("version", 0)) > PROFILE_FORMAT_VERSION:
            raise ValueError("Profile was created by a newer PokePilot version.")
        name = str(data.get("name", "")).strip()
        if not name:
            raise ValueError("Profile has no name.")
        actions = [Action.from_dict(a) for a in data.get("actions", [])]
        for a in actions:
            a.uid = new_uid()  # imported copies never share ids with existing actions
        return cls(name, str(data.get("description", "")), actions)


# -------------------------------------------------------------- validation
def _check_number(spec: ParamSpec, value: Any, errors: list[str]) -> None:
    ok_type = (int,) if spec.kind == "int" else (int, float)
    if not isinstance(value, ok_type) or isinstance(value, bool):
        errors.append(f"'{spec.name}' must be a number.")
        return
    if spec.minimum is not None and value < spec.minimum:
        errors.append(f"'{spec.name}' must be >= {spec.minimum}.")
    if spec.maximum is not None and value > spec.maximum:
        errors.append(f"'{spec.name}' must be <= {spec.maximum}.")


def validate_action(action: Action, layout: PgsharpLayout | None = None) -> list[str]:
    """Return human-readable problems. ``layout`` enables reference checks against calibration."""
    errors: list[str] = []
    schema = {s.name: s for s in PARAM_SCHEMA[action.type]}
    for key in action.params:
        if key not in schema:
            errors.append(f"Unknown parameter '{key}'.")
    for spec in schema.values():
        value = action.params.get(spec.name)
        if value in (None, ""):
            if spec.required:
                errors.append(f"'{spec.name}' is required.")
            continue
        if spec.kind in ("float", "int"):
            _check_number(spec, value, errors)
        elif not isinstance(value, str):
            errors.append(f"'{spec.name}' must be text.")
        elif spec.kind == "package":
            try:
                validate_package_name(value)
            except ValueError as exc:
                errors.append(str(exc))
        elif layout is not None and spec.kind == "element" and value not in layout.elements:
            errors.append(f"UI element '{value}' is not calibrated.")
        elif layout is not None and spec.kind == "state" and value not in layout.states:
            errors.append(f"Screen state '{value}' is not calibrated.")
        elif spec.kind == "feature" and layout is not None:
            fm = layout.features.get(value)
            if fm is None:
                errors.append(f"Unknown feature '{value}'.")
            elif fm.availability is Availability.UNAVAILABLE:
                errors.append(f"Feature '{value}' is marked unavailable.")
            elif action.type is ActionType.SELECT_FEATURE and not (fm.open_steps or fm.verify_state):
                errors.append(f"Feature '{value}' is not mapped yet (PGSharp Controller > Features).")
            elif action.type is ActionType.TOGGLE_FEATURE and not fm.toggle_element:
                errors.append(f"Feature '{value}' has no toggle element mapped.")
        elif spec.kind == "steps":
            steps = [s.strip() for s in value.split(",") if s.strip()]
            if not steps:
                errors.append("'steps' needs at least one element id.")
            elif layout is not None:
                errors += [f"UI element '{s}' is not calibrated." for s in steps if s not in layout.elements]
    if action.type is ActionType.TAP:
        has_el = bool(action.params.get("element"))
        has_xy = action.params.get("x") is not None and action.params.get("y") is not None
        if has_el == has_xy:
            errors.append("TAP needs either an element or both x and y.")
    if not 0.5 <= action.timeout_s <= MAX_TIMEOUT_S:
        errors.append(f"Timeout must be between 0.5 and {MAX_TIMEOUT_S:.0f} seconds.")
    if action.type is ActionType.WAIT and isinstance(action.params.get("seconds"), (int, float)):
        if action.params["seconds"] > action.timeout_s:
            errors.append("WAIT seconds cannot exceed the action timeout.")
    if not 0 <= action.max_retries <= MAX_RETRIES:
        errors.append(f"Retries must be 0-{MAX_RETRIES}.")
    if action.error_policy is ErrorPolicy.RETRY and action.max_retries == 0:
        errors.append("RETRY policy needs at least 1 retry.")
    if action.expected_state and layout is not None and action.expected_state not in layout.states:
        errors.append(f"Expected state '{action.expected_state}' is not calibrated.")
    if action.expected_state and action.type in (ActionType.WAIT_FOR_STATE, ActionType.END_SESSION,
                                                 ActionType.USER_CONFIRMATION):
        errors.append(f"{action.type.value} cannot have an expected state.")
    return errors


def validate_profile(profile: Profile, layout: PgsharpLayout | None = None) -> list[str]:
    errors = [] if profile.name.strip() else ["Profile name is required."]
    if not profile.actions:
        errors.append("Profile has no actions.")
    uids = [a.uid for a in profile.actions]
    if len(set(uids)) != len(uids):
        errors.append("Duplicate action ids.")
    for i, action in enumerate(profile.actions, 1):
        errors += [f"Action {i} ({action.type.value}): {e}" for e in validate_action(action, layout)]
    return errors
