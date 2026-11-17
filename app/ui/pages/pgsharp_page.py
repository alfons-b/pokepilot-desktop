"""PGSharp Controller: launch, calibrate UI elements and screen states, map and test features."""

from __future__ import annotations

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.app_controller import AppController
from app.emulator.app_launcher import ProcessState
from app.pgsharp.controller import PgsharpController
from app.pgsharp.features import FEATURE_CATALOG, FEATURES_BY_ID
from app.pgsharp.layout import Availability, FeatureMapping
from app.pgsharp.ui_driver import FeatureResult, Outcome
from app.pgsharp.vision import StateMatch
from app.ui.widgets.common import Banner, Page, StatusBadge, hbox, make_button
from app.ui.widgets.image_view import ImageView, Marker, RectOverlay

_PROC_LEVEL = {ProcessState.RUNNING: "ok", ProcessState.NOT_RUNNING: "idle", ProcessState.UNKNOWN: "warn"}
_OUTCOME_LEVEL = {Outcome.SUCCESS: "ok", Outcome.FAILED: "error", Outcome.UNKNOWN: "warn"}

GUIDE = (
    "1) Open PGSharp in the emulator and press Capture.  2) Elements: press Add, then click the button on the "
    "screenshot.  3) Screen States: create a state, switch to 'Draw region' and drag over a part of the screen that "
    "is unique to that screen (e.g. a menu title).  4) Features: set availability, the elements to tap to open it, "
    "and the state that proves it opened, then Test."
)


class PgsharpPage(Page):
    def __init__(self, pg: PgsharpController, apps: AppController, parent: QWidget | None = None) -> None:
        super().__init__("PGSharp Controller", "Map PGSharp's on-screen controls and verify screens.", parent)
        self._pg = pg
        self._apps = apps
        self._pending: str | None = None  # "add" | "move"
        self.banner = Banner()
        self.body.addWidget(self.banner)
        self.warn_banner = Banner()
        self.body.addWidget(self.warn_banner)
        if pg.load_warning:
            self.warn_banner.show_message("warn", pg.load_warning)

        # Status row
        status = QGroupBox("PGSharp App")
        self.pkg_label = QLabel()
        self.proc_badge = StatusBadge("Not checked", "idle")
        self.verified_label = QLabel("Last verified screen: none")
        self.verified_label.setObjectName("Muted")
        self.launch_btn = make_button("Launch PGSharp", "primary")
        self.check_btn = make_button("Check Running")
        self.launch_btn.clicked.connect(apps.launch_target)
        self.check_btn.clicked.connect(apps.check_target_running)
        sl = QVBoxLayout(status)
        sl.addLayout(hbox(self.pkg_label, self.proc_badge, self.launch_btn, self.check_btn))
        sl.addWidget(self.verified_label)
        self.body.addWidget(status)

        row = QHBoxLayout()
        row.setSpacing(14)

        # Canvas
        canvas_box = QGroupBox("Screen")
        self.canvas = ImageView()
        self.canvas.placeholder = "Press Capture to take a screenshot"
        self.capture_btn = make_button("Capture", "primary")
        self.verify_btn = make_button("Verify Screen")
        self.capture_btn.clicked.connect(pg.capture)
        self.verify_btn.clicked.connect(pg.verify_now)
        self.mode_click = QRadioButton("Place element")
        self.mode_rect = QRadioButton("Draw region")
        self.mode_click.setChecked(True)
        group = QButtonGroup(self)
        group.addButton(self.mode_click)
        group.addButton(self.mode_rect)
        self.mode_rect.toggled.connect(lambda on: setattr(self.canvas, "rect_mode", on))
        self.coord_label = QLabel("")
        self.coord_label.setObjectName("Muted")
        cl = QVBoxLayout(canvas_box)
        cl.addLayout(hbox(self.capture_btn, self.verify_btn, self.mode_click, self.mode_rect))
        cl.addWidget(self.canvas, 1)
        cl.addWidget(self.coord_label)
        row.addWidget(canvas_box, 2)

        # Editor tabs
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_elements_tab(), "UI Elements")
        self.tabs.addTab(self._build_states_tab(), "Screen States")
        self.tabs.addTab(self._build_features_tab(), "Features")
        right = QVBoxLayout()
        guide = QLabel(GUIDE)
        guide.setObjectName("Muted")
        guide.setWordWrap(True)
        right.addWidget(guide)
        right.addWidget(self.tabs, 1)
        row.addLayout(right, 3)
        self.body.addLayout(row, 1)

        self.canvas.clicked.connect(self._on_canvas_click)
        self.canvas.rect_selected.connect(self._on_rect)
        pg.screenshot_ready.connect(self._on_image)
        pg.layout_changed.connect(self._refresh_all)
        pg.verification_done.connect(self._on_verification)
        pg.feature_tested.connect(self._on_feature_tested)
        pg.layout_warning.connect(lambda m: self.warn_banner.show_message("warn", m))
        pg.operation_failed.connect(lambda op, m: self.banner.show_message("error", f"{op} failed: {m}"))
        pg.operation_succeeded.connect(lambda op, m: self.banner.show_message("ok", f"{op}: {m}"))
        pg.busy_changed.connect(self._on_busy)
        apps.target_app_changed.connect(lambda _p: self._refresh_pkg())
        apps.process_state_changed.connect(self._on_proc)
        self._refresh_pkg()
        self._refresh_all()

    # ================================================================ tabs
    def _build_elements_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.el_list = QListWidget()
        self.el_list.currentItemChanged.connect(lambda *_: self._refresh_overlays())
        self.el_add_btn = make_button("Add", tooltip="Then click the control on the screenshot.")
        self.el_move_btn = make_button("Move")
        self.el_remove_btn = make_button("Remove")
        self.el_tap_btn = make_button("Test Tap", tooltip="Send a tap to this element on the device.")
        self.el_add_btn.clicked.connect(lambda: self._set_pending("add"))
        self.el_move_btn.clicked.connect(lambda: self._set_pending("move"))
        self.el_remove_btn.clicked.connect(self._remove_element)
        self.el_tap_btn.clicked.connect(lambda: self._with_element(self._pg.tap_element))
        lay.addWidget(self.el_list, 1)
        lay.addLayout(hbox(self.el_add_btn, self.el_move_btn, self.el_remove_btn, self.el_tap_btn))
        return w

    def _build_states_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.st_list = QListWidget()
        self.st_list.currentItemChanged.connect(lambda *_: self._on_state_selected())
        self.st_new_btn = make_button("New State")
        self.st_remove_btn = make_button("Delete")
        self.st_clear_btn = make_button("Clear Regions")
        self.st_new_btn.clicked.connect(self._new_state)
        self.st_remove_btn.clicked.connect(self._remove_state)
        self.st_clear_btn.clicked.connect(lambda: self._with_state(self._pg.clear_regions))
        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(0.01, 0.5)
        self.threshold_spin.setSingleStep(0.01)
        self.threshold_spin.setDecimals(2)
        self.threshold_spin.setFixedWidth(100)
        self.threshold_spin.setToolTip("Maximum difference for a match. Raise slightly if a correct screen fails.")
        self.threshold_spin.editingFinished.connect(
            lambda: self._with_state(lambda sid: self._pg.set_threshold(sid, self.threshold_spin.value()))
        )
        hint = QLabel("Select a state, choose 'Draw region' and drag over the screenshot to add a reference region.")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        self.results_list = QListWidget()
        self.results_list.setMaximumHeight(140)
        lay.addWidget(self.st_list, 1)
        lay.addLayout(hbox(self.st_new_btn, self.st_remove_btn, self.st_clear_btn))
        lay.addLayout(hbox(QLabel("Match threshold:"), self.threshold_spin))
        lay.addWidget(hint)
        lay.addWidget(QLabel("Last verification:"))
        lay.addWidget(self.results_list)
        return w

    def _build_features_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.ft_table = QTableWidget(len(FEATURE_CATALOG), 4)
        self.ft_table.setHorizontalHeaderLabels(["Feature", "Availability", "Open steps", "Verify state"])
        self.ft_table.verticalHeader().setVisible(False)
        self.ft_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.ft_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.ft_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.ft_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.ft_table.horizontalHeader().setStretchLastSection(True)
        self.ft_table.itemSelectionChanged.connect(self._load_feature_editor)
        lay.addWidget(self.ft_table, 1)

        editor = QGroupBox("Selected feature")
        self.ft_avail = QComboBox()
        self.ft_avail.addItems([a.value for a in Availability])
        self.ft_steps = QLineEdit()
        self.ft_steps.setPlaceholderText("element ids in tap order, comma separated, e.g. menu_button, teleport_icon")
        self.ft_toggle = QComboBox()
        self.ft_verify = QComboBox()
        self.ft_notes = QLineEdit()
        self.ft_save_btn = make_button("Save Feature", "primary")
        self.ft_test_btn = make_button("Test Feature", tooltip="Tap the open steps, then verify the state.")
        self.ft_result = StatusBadge("Not tested", "idle")
        self.ft_save_btn.clicked.connect(self._save_feature)
        self.ft_test_btn.clicked.connect(self._test_feature)
        f = QFormLayout(editor)
        f.addRow("Availability:", self.ft_avail)
        f.addRow("Open steps:", self.ft_steps)
        f.addRow("Toggle element:", self.ft_toggle)
        f.addRow("Verify state:", self.ft_verify)
        f.addRow("Notes:", self.ft_notes)
        f.addRow(hbox(self.ft_save_btn, self.ft_test_btn, self.ft_result))
        lay.addWidget(editor)
        return w

    # ============================================================ refresh
    def _refresh_pkg(self) -> None:
        pkg = self._apps.target_package
        self.pkg_label.setText(
            f"Package: <b>{pkg}</b>" if pkg else "No PGSharp package set: choose it in Emulator Manager > Applications."
        )
        self.launch_btn.setEnabled(bool(pkg))
        self.check_btn.setEnabled(bool(pkg))

    def _refresh_all(self) -> None:
        lay = self._pg.layout
        cur_el = self._current_id(self.el_list)
        self.el_list.clear()
        for el in lay.elements.values():
            item = QListWidgetItem(f"{el.label}  [{el.id}]  ({el.x:.3f}, {el.y:.3f})")
            item.setData(Qt.ItemDataRole.UserRole, el.id)
            self.el_list.addItem(item)
            if el.id == cur_el:
                self.el_list.setCurrentItem(item)
        cur_st = self._current_id(self.st_list)
        self.st_list.blockSignals(True)
        self.st_list.clear()
        for st in lay.states.values():
            item = QListWidgetItem(f"{st.name}  [{st.id}]  - {len(st.regions)} region(s)")
            item.setData(Qt.ItemDataRole.UserRole, st.id)
            self.st_list.addItem(item)
            if st.id == cur_st:
                self.st_list.setCurrentItem(item)
        self.st_list.blockSignals(False)
        for row, info in enumerate(FEATURE_CATALOG):
            fm = lay.features[info.id]
            vals = [info.name, fm.availability.value, " > ".join(fm.open_steps) or "-", fm.verify_state or "-"]
            for col, v in enumerate(vals):
                item = QTableWidgetItem(v)
                item.setData(Qt.ItemDataRole.UserRole, info.id)
                self.ft_table.setItem(row, col, item)
        for combo, items in ((self.ft_toggle, lay.elements), (self.ft_verify, lay.states)):
            current = combo.currentData()
            combo.clear()
            combo.addItem("(none)", None)
            for key in items:
                combo.addItem(key, key)
            idx = combo.findData(current)
            combo.setCurrentIndex(max(idx, 0))
        if lay.reference_width:
            self.coord_label.setText(f"Calibration reference: {lay.reference_width} x {lay.reference_height}")
        self._on_state_selected()
        self._refresh_overlays()

    def _refresh_overlays(self) -> None:
        sel = self._current_id(self.el_list)
        self.canvas.set_markers(
            [
                Marker(e.x, e.y, e.label, "#f59e0b" if e.id == sel else "#ef4444")
                for e in self._pg.layout.elements.values()
            ]
        )
        sid = self._current_id(self.st_list)
        st = self._pg.layout.states.get(sid or "")
        self.canvas.set_rects([RectOverlay(r.x, r.y, r.w, r.h, st.name) for r in st.regions] if st else [])

    # ============================================================ handlers
    @staticmethod
    def _current_id(lst: QListWidget) -> str | None:
        item = lst.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _set_pending(self, mode: str) -> None:
        if self._pg.image is None:
            self.banner.show_message("warn", "Capture a screenshot first.")
            return
        if mode == "move" and not self._current_id(self.el_list):
            self.banner.show_message("warn", "Select an element to move.")
            return
        self.mode_click.setChecked(True)
        self._pending = mode
        self.banner.show_message("info", "Click the control's position on the screenshot.", 0)

    @Slot(float, float)
    def _on_canvas_click(self, x: float, y: float) -> None:
        self.coord_label.setText(f"Clicked at ({x:.3f}, {y:.3f})")
        mode, self._pending = self._pending, None
        if mode == "add":
            name, ok = QInputDialog.getText(self, "New UI element", "Name (e.g. Teleport button):")
            if ok and name.strip():
                if self._pg.add_element(name, x, y):
                    self.banner.show_message("ok", f"Element '{name.strip()}' added.")
            else:
                self.banner.hide()
        elif mode == "move":
            eid = self._current_id(self.el_list)
            if eid:
                self._pg.move_element(eid, x, y)
                self.banner.show_message("ok", f"Element '{eid}' moved.")

    @Slot(float, float, float, float)
    def _on_rect(self, x: float, y: float, w: float, h: float) -> None:
        sid = self._current_id(self.st_list)
        if not sid:
            self.banner.show_message("warn", "Select or create a screen state first, then drag a region.")
            return
        if self._pg.add_region(sid, x, y, w, h):
            self.banner.show_message("ok", f"Region added to '{sid}'.")

    def _with_element(self, fn) -> None:  # noqa: ANN001
        eid = self._current_id(self.el_list)
        if eid:
            fn(eid)
        else:
            self.banner.show_message("warn", "Select an element first.")

    def _with_state(self, fn) -> None:  # noqa: ANN001
        sid = self._current_id(self.st_list)
        if sid:
            fn(sid)
        else:
            self.banner.show_message("warn", "Select a screen state first.")

    def _remove_element(self) -> None:
        eid = self._current_id(self.el_list)
        if not eid:
            return
        if QMessageBox.question(self, "Remove element", f"Remove '{eid}'? Feature mappings using it are cleared.") \
                == QMessageBox.StandardButton.Yes:
            touched = self._pg.remove_element(eid)
            if touched:
                self.banner.show_message("warn", f"Updated feature mappings: {', '.join(touched)}")

    def _new_state(self) -> None:
        name, ok = QInputDialog.getText(self, "New screen state", "Name (e.g. PGSharp menu open):")
        if ok and name.strip():
            st = self._pg.add_state(name)
            if st:
                self._refresh_all()
                for i in range(self.st_list.count()):
                    if self.st_list.item(i).data(Qt.ItemDataRole.UserRole) == st.id:
                        self.st_list.setCurrentRow(i)
                self.mode_rect.setChecked(True)

    def _remove_state(self) -> None:
        sid = self._current_id(self.st_list)
        if sid and QMessageBox.question(self, "Delete state", f"Delete screen state '{sid}'?") \
                == QMessageBox.StandardButton.Yes:
            self._pg.remove_state(sid)

    def _on_state_selected(self) -> None:
        st = self._pg.layout.states.get(self._current_id(self.st_list) or "")
        self.threshold_spin.setEnabled(st is not None)
        if st:
            self.threshold_spin.setValue(st.threshold)
        self._refresh_overlays()

    def _selected_feature(self) -> str | None:
        rows = self.ft_table.selectionModel().selectedRows()
        if not rows:
            return None
        return self.ft_table.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole)

    def _load_feature_editor(self) -> None:
        fid = self._selected_feature()
        if not fid:
            return
        fm = self._pg.layout.features[fid]
        self.ft_avail.setCurrentText(fm.availability.value)
        self.ft_steps.setText(", ".join(fm.open_steps))
        self.ft_toggle.setCurrentIndex(max(self.ft_toggle.findData(fm.toggle_element), 0))
        self.ft_toggle.setEnabled(FEATURES_BY_ID[fid].toggleable)
        self.ft_verify.setCurrentIndex(max(self.ft_verify.findData(fm.verify_state), 0))
        self.ft_notes.setText(fm.notes)
        self.ft_result.set_status("idle", "Not tested")

    def _save_feature(self) -> bool:
        fid = self._selected_feature()
        if not fid:
            self.banner.show_message("warn", "Select a feature first.")
            return False
        steps = [s.strip() for s in self.ft_steps.text().split(",") if s.strip()]
        mapping = FeatureMapping(
            fid,
            Availability(self.ft_avail.currentText()),
            steps,
            self.ft_toggle.currentData() if self.ft_toggle.isEnabled() else None,
            self.ft_verify.currentData(),
            self.ft_notes.text().strip(),
        )
        if self._pg.update_feature(mapping):
            self.banner.show_message("ok", f"Feature '{FEATURES_BY_ID[fid].name}' saved.")
            self._reselect_feature(fid)
            return True
        return False

    def _reselect_feature(self, fid: str) -> None:
        for row in range(self.ft_table.rowCount()):
            if self.ft_table.item(row, 0).data(Qt.ItemDataRole.UserRole) == fid:
                self.ft_table.selectRow(row)

    def _test_feature(self) -> None:
        fid = self._selected_feature()
        if fid and self._save_feature():
            self.ft_result.set_status("info", "Testing...")
            self._pg.test_feature(fid)

    @Slot(object)
    def _on_image(self, img: QImage) -> None:
        self.canvas.set_image(img)
        self.coord_label.setText(f"Screenshot {img.width()} x {img.height()}")

    @Slot(list)
    def _on_verification(self, matches: list[StateMatch]) -> None:
        self.results_list.clear()
        for m in matches:
            mark = {True: "MATCH", False: "no", None: "no regions"}[m.matched]
            self.results_list.addItem(f"{mark:<10} {m.name}  (diff {m.score:.3f})")
        self._update_verified_label()

    @Slot(object)
    def _on_feature_tested(self, result: FeatureResult) -> None:
        self.ft_result.set_status(_OUTCOME_LEVEL[result.outcome], result.outcome.value)
        level = {"Success": "ok", "Failed": "error", "Unknown": "warn"}[result.outcome.value]
        self.banner.show_message(level, result.message)
        self._update_verified_label()

    def _update_verified_label(self) -> None:
        lv = self._pg.last_verified
        self.verified_label.setText(
            f"Last verified screen: {lv[1]} at {lv[0]:%H:%M:%S}" if lv else "Last verified screen: none"
        )

    @Slot(str, str, object)
    def _on_proc(self, _serial: str, package: str, state: ProcessState) -> None:
        if package == self._apps.target_package:
            self.proc_badge.set_status(_PROC_LEVEL[state], state.value)

    @Slot(bool)
    def _on_busy(self, busy: bool) -> None:
        for b in (self.capture_btn, self.verify_btn, self.el_tap_btn, self.ft_test_btn):
            b.setEnabled(not busy)
