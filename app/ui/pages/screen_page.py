"""Screen Monitor: scrcpy mirroring control, options and screenshots."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl, Slot
from PySide6.QtGui import QDesktopServices, QImage
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.core.device_controller import DeviceController
from app.screen.mirror_controller import MirrorController, MirrorState, screenshots_dir
from app.screen.scrcpy import MAX_SIZE_CHOICES
from app.ui.widgets.common import Banner, Page, StatusBadge, hbox, make_button
from app.ui.widgets.image_view import ImageView

_LEVEL = {
    MirrorState.RUNNING: "ok",
    MirrorState.STARTING: "info",
    MirrorState.STOPPING: "info",
    MirrorState.STOPPED: "idle",
    MirrorState.FAILED: "error",
}

HELP = (
    "Mouse and keyboard work directly in the scrcpy window: left-click = tap, drag = swipe, "
    "right-click = BACK, middle-click = HOME, type to send text. Alt+F = fullscreen, Alt+Up/Down = volume. "
    "View-only mode disables input forwarding."
)


class ScreenPage(Page):
    def __init__(self, devices: DeviceController, mirror: MirrorController, parent: QWidget | None = None) -> None:
        super().__init__("Screen Monitor", "Mirror and control the emulator with scrcpy; capture screenshots.", parent)
        self._devices = devices
        self._mirror = mirror
        self.banner = Banner()
        self.body.addWidget(self.banner)

        row = QHBoxLayout()
        row.setSpacing(14)
        left = QVBoxLayout()
        left.setSpacing(12)

        ctl = QGroupBox("Mirroring")
        self.state_badge = StatusBadge("Not running", "idle")
        self.detail_label = QLabel("")
        self.detail_label.setObjectName("Muted")
        self.detail_label.setWordWrap(True)
        self.start_btn = make_button("Start Mirroring", "primary")
        self.stop_btn = make_button("Stop")
        self.restart_btn = make_button("Restart")
        self.start_btn.clicked.connect(self._start)
        self.stop_btn.clicked.connect(mirror.stop)
        self.restart_btn.clicked.connect(self._restart)
        help_label = QLabel(HELP)
        help_label.setObjectName("Muted")
        help_label.setWordWrap(True)
        cl = QVBoxLayout(ctl)
        cl.addWidget(self.state_badge)
        cl.addWidget(self.detail_label)
        cl.addLayout(hbox(self.start_btn, self.stop_btn, self.restart_btn))
        cl.addWidget(help_label)
        left.addWidget(ctl)

        opts = QGroupBox("Options (applied on next start)")
        self.size_combo = QComboBox()
        for v in MAX_SIZE_CHOICES:
            self.size_combo.addItem("Native" if v == 0 else f"{v} px", v)
        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(1, 120)
        self.fps_spin.setSuffix(" fps")
        self.bitrate_spin = QSpinBox()
        self.bitrate_spin.setRange(1, 100)
        self.bitrate_spin.setSuffix(" Mbps")
        for w in (self.size_combo, self.fps_spin, self.bitrate_spin):
            w.setFixedWidth(130)
        self.fullscreen_check = QCheckBox("Fullscreen")
        self.on_top_check = QCheckBox("Always on top")
        self.awake_check = QCheckBox("Keep device awake")
        self.view_only_check = QCheckBox("View only (no mouse/keyboard control)")
        self.uhid_check = QCheckBox("Physical keyboard simulation (UHID, scrcpy 2.4+)")
        self.auto_restart_check = QCheckBox("Restart automatically if scrcpy crashes")
        f = QFormLayout(opts)
        f.addRow("Max size:", self.size_combo)
        f.addRow("Frame rate:", self.fps_spin)
        f.addRow("Bitrate:", self.bitrate_spin)
        for cb in (self.fullscreen_check, self.on_top_check, self.awake_check, self.view_only_check,
                   self.uhid_check, self.auto_restart_check):
            f.addRow(cb)
        left.addWidget(opts)

        log_box = QGroupBox("scrcpy Output")
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(500)
        QVBoxLayout(log_box).addWidget(self.log_view)
        left.addWidget(log_box, 1)
        row.addLayout(left, 3)

        shot = QGroupBox("Screenshot")
        self.preview = ImageView()
        self.shot_btn = make_button("Capture Screenshot", "primary")
        self.folder_btn = make_button("Open Folder")
        self.shot_btn.clicked.connect(mirror.capture_screenshot)
        self.folder_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(screenshots_dir()))))
        self.shot_label = QLabel("")
        self.shot_label.setObjectName("Muted")
        sl = QVBoxLayout(shot)
        sl.addLayout(hbox(self.shot_btn, self.folder_btn))
        sl.addWidget(self.preview, 1)
        sl.addWidget(self.shot_label)
        row.addWidget(shot, 2)
        self.body.addLayout(row, 1)

        self._load_options()
        for w in (self.fullscreen_check, self.on_top_check, self.awake_check, self.view_only_check,
                  self.uhid_check, self.auto_restart_check):
            w.toggled.connect(self._save_options)
        self.size_combo.currentIndexChanged.connect(self._save_options)
        self.fps_spin.valueChanged.connect(self._save_options)
        self.bitrate_spin.valueChanged.connect(self._save_options)

        mirror.state_changed.connect(self._on_state)
        mirror.output_line.connect(self.log_view.appendPlainText)
        mirror.screenshot_saved.connect(self._on_screenshot)
        mirror.operation_failed.connect(lambda op, m: self.banner.show_message("error", f"{op} failed: {m}"))
        mirror.operation_succeeded.connect(lambda op, m: self.banner.show_message("ok", f"{op}: {m}"))
        self._on_state(mirror.state, mirror.detail)

    def _load_options(self) -> None:
        c = self._devices.config
        idx = self.size_combo.findData(c.scrcpy_max_size)
        if idx < 0:
            self.size_combo.addItem(f"{c.scrcpy_max_size} px", c.scrcpy_max_size)
            idx = self.size_combo.count() - 1
        self.size_combo.setCurrentIndex(idx)
        self.fps_spin.setValue(c.scrcpy_max_fps)
        self.bitrate_spin.setValue(c.scrcpy_bitrate_mbps)
        self.fullscreen_check.setChecked(c.scrcpy_fullscreen)
        self.on_top_check.setChecked(c.scrcpy_always_on_top)
        self.awake_check.setChecked(c.scrcpy_stay_awake)
        self.view_only_check.setChecked(c.scrcpy_view_only)
        self.uhid_check.setChecked(c.scrcpy_uhid_keyboard)
        self.auto_restart_check.setChecked(c.scrcpy_auto_restart)

    def _save_options(self, *_: object) -> None:
        c = self._devices.config
        c.scrcpy_max_size = int(self.size_combo.currentData())
        c.scrcpy_max_fps = self.fps_spin.value()
        c.scrcpy_bitrate_mbps = self.bitrate_spin.value()
        c.scrcpy_fullscreen = self.fullscreen_check.isChecked()
        c.scrcpy_always_on_top = self.on_top_check.isChecked()
        c.scrcpy_stay_awake = self.awake_check.isChecked()
        c.scrcpy_view_only = self.view_only_check.isChecked()
        c.scrcpy_uhid_keyboard = self.uhid_check.isChecked()
        c.scrcpy_auto_restart = self.auto_restart_check.isChecked()
        self._devices.save_config()

    def _start(self) -> None:
        self.log_view.clear()
        self._mirror.start()

    def _restart(self) -> None:
        self.log_view.clear()
        self._mirror.restart()

    @Slot(object, str)
    def _on_state(self, state: MirrorState, detail: str) -> None:
        self.state_badge.set_status(_LEVEL[state], state.value)
        self.detail_label.setText(detail)
        active = state in (MirrorState.STARTING, MirrorState.RUNNING, MirrorState.STOPPING)
        self.start_btn.setEnabled(not active)
        self.stop_btn.setEnabled(active and state is not MirrorState.STOPPING)
        self.restart_btn.setEnabled(state is not MirrorState.STOPPING)

    @Slot(str)
    def _on_screenshot(self, path: str) -> None:
        img = QImage(path)
        self.preview.set_image(img)
        self.shot_label.setText(f"{Path(path).name} - {img.width()} x {img.height()}")
