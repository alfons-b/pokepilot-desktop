"""Dialog for creating/editing one automation action; the form is generated from PARAM_SCHEMA."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.automation.models import (
    MAX_RETRIES,
    MAX_TIMEOUT_S,
    PARAM_SCHEMA,
    Action,
    ActionType,
    ErrorPolicy,
    ParamSpec,
    validate_action,
)
from app.pgsharp.features import FEATURE_CATALOG
from app.pgsharp.layout import PgsharpLayout

TYPE_HELP = {
    ActionType.LAUNCH_APP: "Start an app (default: the target app) and confirm its process is running.",
    ActionType.WAIT: "Pause for a fixed time.",
    ActionType.SCREENSHOT: "Save a screenshot to data/screenshots.",
    ActionType.TAP: "Tap a calibrated element or a normalized position (0-1). Unverified unless an expected state is set.",
    ActionType.SWIPE: "Swipe between two normalized positions.",
    ActionType.PRESS_BACK: "Send the Android BACK key.",
    ActionType.OPEN_SCREEN: "Tap a sequence of calibrated elements.",
    ActionType.SELECT_FEATURE: "Open a mapped PGSharp feature and verify its screen.",
    ActionType.TOGGLE_FEATURE: "Tap a mapped feature's toggle element.",
    ActionType.WAIT_FOR_STATE: "Wait until a calibrated screen state is detected.",
    ActionType.USER_CONFIRMATION: "Ask you to confirm before continuing.",
    ActionType.END_SESSION: "End the session successfully; later actions are skipped.",
}


class ActionDialog(QDialog):
    def __init__(self, layout: PgsharpLayout, action: Action | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Action" if action else "Add Action")
        self.setMinimumWidth(460)
        self._layout = layout
        self._uid = action.uid if action else None
        self._widgets: dict[str, QWidget] = {}

        self.type_combo = QComboBox()
        self.type_combo.addItems([t.value for t in ActionType])
        self.help_label = QLabel()
        self.help_label.setObjectName("Muted")
        self.help_label.setWordWrap(True)
        self.params_form = QFormLayout()
        self.timeout_spin = QDoubleSpinBox()
        self.timeout_spin.setRange(0.5, MAX_TIMEOUT_S)
        self.timeout_spin.setSuffix(" s")
        self.expected_combo = QComboBox()
        self.expected_combo.addItem("(none)", None)
        for sid, st in layout.states.items():
            self.expected_combo.addItem(f"{st.name} [{sid}]", sid)
        self.policy_combo = QComboBox()
        self.policy_combo.addItems([p.value for p in ErrorPolicy])
        self.retries_spin = QSpinBox()
        self.retries_spin.setRange(0, MAX_RETRIES)
        self.error_label = QLabel()
        self.error_label.setObjectName("Banner")
        self.error_label.setProperty("level", "error")
        self.error_label.setWordWrap(True)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)

        common = QFormLayout()
        common.addRow("Timeout:", self.timeout_spin)
        common.addRow("Expected state:", self.expected_combo)
        common.addRow("On error:", self.policy_combo)
        common.addRow("Retries:", self.retries_spin)
        lay = QVBoxLayout(self)
        top = QFormLayout()
        top.addRow("Action type:", self.type_combo)
        lay.addLayout(top)
        lay.addWidget(self.help_label)
        lay.addLayout(self.params_form)
        lay.addLayout(common)
        lay.addWidget(self.error_label)
        lay.addWidget(self.buttons)

        initial = action or Action.create(ActionType.TAP)
        self.type_combo.setCurrentText(initial.type.value)
        self._build_params(initial.type, initial.params)
        self.timeout_spin.setValue(initial.timeout_s)
        self.expected_combo.setCurrentIndex(max(self.expected_combo.findData(initial.expected_state), 0))
        self.policy_combo.setCurrentText(initial.error_policy.value)
        self.retries_spin.setValue(initial.max_retries)
        self.type_combo.currentTextChanged.connect(self._on_type_changed)
        self.error_label.hide()
        self.result_action: Action | None = None

    # ----------------------------------------------------------------- form
    def _on_type_changed(self, text: str) -> None:
        t = ActionType(text)
        fresh = Action.create(t)
        self._build_params(t, fresh.params)
        self.timeout_spin.setValue(fresh.timeout_s)

    def _build_params(self, t: ActionType, values: dict[str, Any]) -> None:
        while self.params_form.rowCount():
            self.params_form.removeRow(0)
        self._widgets.clear()
        self.help_label.setText(TYPE_HELP[t])
        for spec in PARAM_SCHEMA[t]:
            w = self._widget_for(spec, values.get(spec.name))
            self._widgets[spec.name] = w
            label = spec.name + ("" if spec.required else " (optional)")
            if spec.help:
                w.setToolTip(spec.help)
            self.params_form.addRow(f"{label}:", w)
        is_confirm = t in (ActionType.USER_CONFIRMATION, ActionType.WAIT_FOR_STATE, ActionType.END_SESSION)
        self.expected_combo.setEnabled(not is_confirm)
        if is_confirm:
            self.expected_combo.setCurrentIndex(0)

    def _widget_for(self, spec: ParamSpec, value: Any) -> QWidget:
        if spec.kind in ("float", "int") and spec.required:
            w = QSpinBox() if spec.kind == "int" else QDoubleSpinBox()
            if isinstance(w, QDoubleSpinBox):
                w.setDecimals(3)
                w.setSingleStep(0.05 if (spec.maximum or 0) <= 1 else 0.5)
            w.setRange(spec.minimum if spec.minimum is not None else -1e9, spec.maximum if spec.maximum is not None else 1e9)
            w.setValue(value if isinstance(value, (int, float)) else (spec.default or 0))
            return w
        if spec.kind in ("element", "state", "feature"):
            combo = QComboBox()
            if not spec.required:
                combo.addItem("(none)", "")
            if spec.kind == "element":
                for eid, el in self._layout.elements.items():
                    combo.addItem(f"{el.label} [{eid}]", eid)
            elif spec.kind == "state":
                for sid, st in self._layout.states.items():
                    combo.addItem(f"{st.name} [{sid}]", sid)
            else:
                for f in FEATURE_CATALOG:
                    fm = self._layout.features.get(f.id)
                    combo.addItem(f"{f.name} ({fm.availability.value if fm else '?'})", f.id)
            if value and combo.findData(value) < 0:
                combo.addItem(f"{value} (missing)", value)
            combo.setCurrentIndex(max(combo.findData(value or ""), 0))
            return combo
        edit = QLineEdit("" if value is None else str(value))
        if spec.kind == "package":
            edit.setPlaceholderText("empty = target app")
        elif spec.kind == "steps":
            edit.setPlaceholderText("element ids, comma separated: " + ", ".join(list(self._layout.elements)[:4]))
        elif spec.kind in ("float", "int"):
            edit.setPlaceholderText(f"{spec.minimum}-{spec.maximum}, empty = not used")
        return edit

    def _read_params(self) -> tuple[dict[str, Any], list[str]]:
        params: dict[str, Any] = {}
        errors: list[str] = []
        for spec in PARAM_SCHEMA[ActionType(self.type_combo.currentText())]:
            w = self._widgets[spec.name]
            if isinstance(w, (QSpinBox, QDoubleSpinBox)):
                params[spec.name] = w.value()
            elif isinstance(w, QComboBox):
                if w.currentData():
                    params[spec.name] = w.currentData()
            else:
                text = w.text().strip()  # type: ignore[attr-defined]
                if not text:
                    continue
                if spec.kind in ("float", "int"):
                    try:
                        params[spec.name] = int(text) if spec.kind == "int" else float(text)
                    except ValueError:
                        errors.append(f"'{spec.name}' must be a number.")
                else:
                    params[spec.name] = text
        return params, errors

    def build_action(self) -> tuple[Action, list[str]]:
        params, errors = self._read_params()
        action = Action(
            ActionType(self.type_combo.currentText()),
            params,
            float(self.timeout_spin.value()),
            self.expected_combo.currentData(),
            ErrorPolicy(self.policy_combo.currentText()),
            int(self.retries_spin.value()),
        )
        if self._uid:
            action.uid = self._uid
        return action, errors + validate_action(action, self._layout)

    def _accept(self) -> None:
        action, errors = self.build_action()
        if errors:
            self.error_label.setText("\n".join(errors))
            self.error_label.show()
            return
        self.result_action = action
        self.accept()
