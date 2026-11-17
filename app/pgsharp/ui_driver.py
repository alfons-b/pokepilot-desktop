"""Device UI driver: screenshots, taps on calibrated elements, state verification.

Synchronous; run it on a worker thread. Shared by the PGSharp controller and the
automation engine. Every operation reports explicit outcomes - a successful ADB
command is never treated as proof that the UI changed.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from PySide6.QtGui import QImage

from app.emulator.adb_client import KEYCODE_BACK, AdbClient, AdbError
from app.pgsharp.layout import PgsharpLayout
from app.pgsharp.vision import StateMatch, detect_states, verify_state

logger = logging.getLogger(__name__)


class Outcome(StrEnum):
    SUCCESS = "Success"
    FAILED = "Failed"
    UNKNOWN = "Unknown"  # command sent, but no verification was possible


class DriverError(Exception):
    pass


class Cancelled(Exception):
    """Raised when a cancellation token is set during a wait."""


@dataclass(frozen=True)
class FeatureResult:
    feature_id: str
    outcome: Outcome
    message: str
    match: StateMatch | None = None


class UiDriver:
    def __init__(
        self,
        client: AdbClient,
        serial: str,
        layout: PgsharpLayout,
        sleep: Callable[[float], None] = time.sleep,
        step_delay_s: float = 0.8,
    ) -> None:
        if not serial:
            raise DriverError("No device selected.")
        self.client = client
        self.serial = serial
        self.layout = layout
        self._sleep = sleep
        self.step_delay_s = step_delay_s
        self._size: tuple[int, int] | None = None
        self.last_image: QImage | None = None

    # -------------------------------------------------------------- screen
    def screenshot(self) -> QImage:
        png = self.client.screencap(self.serial)
        img = QImage.fromData(png, "PNG")
        if img.isNull():
            raise DriverError("Screenshot could not be decoded.")
        self._size = (img.width(), img.height())
        self.last_image = img
        return img

    def screen_size(self) -> tuple[int, int]:
        if self._size is None:
            self.screenshot()
        assert self._size is not None
        return self._size

    def resolution_warning(self) -> str | None:
        w, h = self.screen_size()
        return self.layout.check_resolution(w, h)

    # --------------------------------------------------------------- input
    def tap_norm(self, x: float, y: float) -> None:
        if not (0 <= x <= 1 and 0 <= y <= 1):
            raise DriverError(f"Tap position out of range: {x:.3f}, {y:.3f}")
        w, h = self.screen_size()
        self.client.tap(self.serial, round(x * (w - 1)), round(y * (h - 1)))

    def tap_element(self, element_id: str) -> None:
        el = self.layout.elements.get(element_id)
        if el is None:
            raise DriverError(f"UI element '{element_id}' is not calibrated.")
        logger.debug("Tap %s (%.3f, %.3f)", element_id, el.x, el.y)
        self.tap_norm(el.x, el.y)

    def swipe_norm(self, x1: float, y1: float, x2: float, y2: float, duration_ms: int = 300) -> None:
        for v in (x1, y1, x2, y2):
            if not 0 <= v <= 1:
                raise DriverError("Swipe coordinates must be between 0 and 1.")
        if not 50 <= duration_ms <= 10000:
            raise DriverError("Swipe duration must be 50-10000 ms.")
        w, h = self.screen_size()
        self.client.swipe(
            self.serial, round(x1 * (w - 1)), round(y1 * (h - 1)), round(x2 * (w - 1)), round(y2 * (h - 1)), duration_ms
        )

    def back(self) -> None:
        self.client.keyevent(self.serial, KEYCODE_BACK)

    # ---------------------------------------------------------- verification
    def verify(self, state_id: str, image: QImage | None = None) -> StateMatch:
        state = self.layout.states.get(state_id)
        if state is None:
            raise DriverError(f"Screen state '{state_id}' is not calibrated.")
        return verify_state(image or self.screenshot(), state)

    def detect(self) -> list[StateMatch]:
        return detect_states(self.screenshot(), list(self.layout.states.values()))

    def wait_for_state(
        self,
        state_id: str,
        timeout_s: float,
        poll_s: float = 1.0,
        cancel: threading.Event | None = None,
    ) -> StateMatch:
        """Poll until the state matches or the timeout passes. Returns the last match."""
        deadline = time.monotonic() + timeout_s
        while True:
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            match = self.verify(state_id)
            if match.matched is not False or time.monotonic() >= deadline:
                return match
            self._sleep(poll_s)

    # --------------------------------------------------------------- features
    def open_feature(self, feature_id: str, cancel: threading.Event | None = None) -> FeatureResult:
        fm = self.layout.features.get(feature_id)
        if fm is None:
            raise DriverError(f"Unknown feature '{feature_id}'.")
        if fm.availability.value == "Unavailable":
            return FeatureResult(feature_id, Outcome.FAILED, "Feature is marked unavailable in this PGSharp edition.")
        if not fm.open_steps and not fm.verify_state:
            return FeatureResult(feature_id, Outcome.FAILED, "Feature is not mapped yet (no steps, no verify state).")
        for step in fm.open_steps:
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            self.tap_element(step)
            self._sleep(self.step_delay_s)
        return self._verify_feature(feature_id, fm.verify_state, "opened")

    def toggle_feature(self, feature_id: str) -> FeatureResult:
        fm = self.layout.features.get(feature_id)
        if fm is None or not fm.toggle_element:
            return FeatureResult(feature_id, Outcome.FAILED, "No toggle element is mapped for this feature.")
        self.tap_element(fm.toggle_element)
        self._sleep(self.step_delay_s)
        # A toggle's on/off state is only known if the user calibrated a state for it.
        return self._verify_feature(feature_id, fm.verify_state, "toggled")

    def _verify_feature(self, feature_id: str, state_id: str | None, verb: str) -> FeatureResult:
        if not state_id:
            return FeatureResult(feature_id, Outcome.UNKNOWN, "Taps sent; result not verified (no verify state set).")
        try:
            match = self.verify(state_id)
        except (AdbError, DriverError) as exc:
            return FeatureResult(feature_id, Outcome.UNKNOWN, f"Taps sent; verification failed: {exc}")
        if match.matched:
            return FeatureResult(feature_id, Outcome.SUCCESS, f"Feature {verb}; '{match.name}' verified.", match)
        return FeatureResult(
            feature_id, Outcome.FAILED, f"Expected screen '{match.name}' not detected (diff {match.score:.3f}).", match
        )
