"""PGSharp controller: calibration data, screen verification and feature tests."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage

from app.core.device_controller import DeviceController
from app.core.task_runner import TaskRunner
from app.paths import data_dir
from app.pgsharp.layout import FeatureMapping, LayoutError, LayoutStore
from app.pgsharp.ui_driver import FeatureResult, UiDriver
from app.pgsharp.vision import StateMatch, make_region

logger = logging.getLogger(__name__)
LAYOUT_FAILURE_LIMIT = 3


def layout_path() -> Path:
    return data_dir() / "pgsharp_layout.json"


class PgsharpController(QObject):
    layout_changed = Signal()
    screenshot_ready = Signal(object)  # QImage
    verification_done = Signal(list)  # list[StateMatch]
    feature_tested = Signal(object)  # FeatureResult
    layout_warning = Signal(str)
    operation_succeeded = Signal(str, str)
    operation_failed = Signal(str, str)
    busy_changed = Signal(bool)

    def __init__(
        self,
        devices: DeviceController,
        runner: TaskRunner,
        store: LayoutStore | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._devices = devices
        self._runner = runner
        self._store = store or LayoutStore(layout_path())
        self.layout, self.load_warning = self._store.load()
        self.image: QImage | None = None
        self.last_verified: tuple[datetime, str] | None = None  # time, state name
        self._consecutive_misses = 0
        self._busy = 0

    @property
    def is_busy(self) -> bool:
        return self._busy > 0

    # ------------------------------------------------------------- editing
    def save(self) -> bool:
        try:
            self._store.save(self.layout)
        except OSError as exc:
            self.operation_failed.emit("Save calibration", str(exc))
            return False
        self.layout_changed.emit()
        return True

    def _edit(self, op: str, fn: Callable[[], object]) -> object | None:
        try:
            result = fn()
        except LayoutError as exc:
            self.operation_failed.emit(op, str(exc))
            return None
        self.save()
        return result

    def add_element(self, label: str, x: float, y: float):  # noqa: ANN201
        def do():  # noqa: ANN202
            self._ensure_reference()
            return self.layout.add_element(label, x, y)

        return self._edit("Add element", do)

    def move_element(self, eid: str, x: float, y: float) -> None:
        self._edit("Move element", lambda: self.layout.move_element(eid, x, y))

    def remove_element(self, eid: str) -> list[str] | None:
        return self._edit("Remove element", lambda: self.layout.remove_element(eid))  # type: ignore[return-value]

    def add_state(self, name: str):  # noqa: ANN201
        return self._edit("Add screen state", lambda: self.layout.add_state(name))

    def remove_state(self, sid: str) -> None:
        self._edit("Remove screen state", lambda: self.layout.remove_state(sid))

    def add_region(self, sid: str, x: float, y: float, w: float, h: float) -> bool:
        if self.image is None:
            self.operation_failed.emit("Add region", "Capture a screenshot first.")
            return False
        state = self.layout.states.get(sid)
        if state is None:
            self.operation_failed.emit("Add region", "Select a screen state first.")
            return False

        try:
            self._ensure_reference()
            state.regions.append(make_region(self.image, x, y, w, h))
        except LayoutError as exc:
            self.operation_failed.emit("Add region", str(exc))
            return False
        return self.save()

    def clear_regions(self, sid: str) -> None:
        if sid in self.layout.states:
            self.layout.states[sid].regions.clear()
            self.save()

    def set_threshold(self, sid: str, value: float) -> None:
        if sid in self.layout.states and 0.01 <= value <= 0.5:
            self.layout.states[sid].threshold = value
            self.save()

    def update_feature(self, mapping: FeatureMapping) -> bool:
        try:
            self.layout.update_feature(mapping)
        except LayoutError as exc:
            self.operation_failed.emit("Save feature", str(exc))
            return False
        return self.save()

    def _ensure_reference(self) -> None:
        if self.image is not None and not self.layout.reference_width:
            self.layout.set_reference(self.image.width(), self.image.height())
        elif self.image is not None:
            warn = self.layout.check_resolution(self.image.width(), self.image.height())
            if warn:
                raise LayoutError(warn)

    def reset_reference(self) -> None:
        """Adopt the current screenshot's resolution as the calibration reference."""
        if self.image is None:
            self.operation_failed.emit("Reset reference", "Capture a screenshot first.")
            return
        self.layout.set_reference(self.image.width(), self.image.height())
        self.save()

    # ----------------------------------------------------------- operations
    def _driver(self) -> UiDriver | None:
        device = self._devices.selected_device
        if device is None or not device.is_online:
            self.operation_failed.emit("PGSharp", "Select an online device first.")
            return None
        return UiDriver(self._devices.make_client(), device.serial, self.layout)

    def capture(self) -> bool:
        driver = self._driver()
        if driver is None:
            return False

        def on_ok(img: QImage) -> None:
            self.image = img
            self.screenshot_ready.emit(img)
            warn = self.layout.check_resolution(img.width(), img.height())
            if warn:
                self.layout_warning.emit(warn)

        self._run("Capture", driver.screenshot, on_result=on_ok)
        return True

    def verify_now(self) -> bool:
        driver = self._driver()
        if driver is None:
            return False
        if not self.layout.states:
            self.operation_failed.emit("Verify screen", "No screen states are calibrated yet.")
            return False

        def work() -> tuple[QImage, list[StateMatch], str | None]:
            matches = driver.detect()
            return driver.last_image, matches, driver.resolution_warning()

        def on_ok(result: tuple[QImage, list[StateMatch], str | None]) -> None:
            img, matches, warn = result
            self.image = img
            self.screenshot_ready.emit(img)
            self.verification_done.emit(matches)
            hit = next((m for m in matches if m.matched), None)
            if hit:
                self.last_verified = (datetime.now(), hit.name)
                self._consecutive_misses = 0
            else:
                self._consecutive_misses += 1
            if warn:
                self.layout_warning.emit(warn)
            elif self._consecutive_misses >= LAYOUT_FAILURE_LIMIT:
                self.layout_warning.emit(
                    f"No calibrated screen matched {self._consecutive_misses} times in a row. "
                    "PGSharp's UI may have changed (update or different theme). Recalibrate the affected states."
                )

        self._run("Verify screen", work, on_result=on_ok)
        return True

    def tap_element(self, eid: str) -> bool:
        driver = self._driver()
        if driver is None:
            return False
        self._run(
            "Test tap",
            driver.tap_element,
            eid,
            on_result=lambda _r: self.operation_succeeded.emit(
                "Test tap", f"Tap sent to '{eid}' (screen effect not verified)."
            ),
        )
        return True

    def test_feature(self, feature_id: str) -> bool:
        driver = self._driver()
        if driver is None:
            return False

        def on_ok(result: FeatureResult) -> None:
            self.feature_tested.emit(result)
            if result.match and result.match.matched:
                self.last_verified = (datetime.now(), result.match.name)

        self._run("Test feature", driver.open_feature, feature_id, on_result=on_ok)
        return True

    def _run(self, name: str, fn: Callable, *args: object, on_result: Callable) -> None:
        self._busy += 1
        if self._busy == 1:
            self.busy_changed.emit(True)

        def on_error(exc: Exception) -> None:
            logger.error("%s failed: %s", name, exc)
            self.operation_failed.emit(name, str(exc))

        def on_done() -> None:
            self._busy -= 1
            if self._busy == 0:
                self.busy_changed.emit(False)

        self._runner.submit(fn, *args, on_result=on_result, on_error=on_error, on_finished=on_done, name=name)
