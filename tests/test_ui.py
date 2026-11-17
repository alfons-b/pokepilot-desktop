"""GUI tests (run headless with QT_QPA_PLATFORM=offscreen)."""

from __future__ import annotations

import time

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox

from app.emulator.adb_client import AdbClient
from app.main import build_app
from app.paths import config_path
from app.ui.main_window import NAV_ITEMS
from tests.fakes.fake_runner import DEVICES_MULTI, DEVICES_ONE, standard_runner


@pytest.fixture
def make_app(qtbot, monkeypatch):
    # Modal dialogs would block a headless test run; answer them automatically.
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.Ok)
    contexts = []

    def factory(fake=None, adb_path="/fake/adb"):
        if adb_path is not None:
            from app.core.config import AppConfig, ConfigManager

            ConfigManager(config_path()).save(AppConfig(adb_path=adb_path, auto_refresh_enabled=False))
        fake = fake or standard_runner()
        ctx = build_app(
            {"client_factory": lambda path, timeout: AdbClient(path, runner=fake, timeout=timeout)}
        )
        qtbot.addWidget(ctx.window)
        contexts.append(ctx)
        return ctx

    yield factory
    for ctx in contexts:
        ctx.controller.shutdown()
        ctx.window.mirror.shutdown()
        ctx.runner.wait_for_done(3000)


def test_window_builds_with_all_pages(make_app):
    ctx = make_app()
    w = ctx.window
    assert w.nav.count() == len(NAV_ITEMS) == w.stack.count()
    for i, name in enumerate(NAV_ITEMS):
        w.nav.setCurrentRow(i)
        assert w.stack.currentWidget() is w.pages[name]


def test_dashboard_session_buttons_disabled_not_fake(make_app):
    ctx = make_app()
    assert all(not b.isEnabled() for b in ctx.window.dashboard_page.session_buttons)
    assert ctx.window.dashboard_page.pgsharp_card.badge.text_value == "Not checked"


def test_dashboard_opens_emulator_manager(make_app):
    ctx = make_app()
    ctx.window.dashboard_page.manage_btn.click()
    assert ctx.window.stack.currentWidget() is ctx.window.emulator_page


def test_emulator_page_shows_detected_devices(qtbot, make_app):
    ctx = make_app(standard_runner(DEVICES_MULTI))
    page = ctx.window.emulator_page
    page.refresh_btn.click()
    qtbot.waitUntil(lambda: page.table.rowCount() == 3, timeout=3000)
    assert page.table.item(0, 0).text() == "emulator-5554"
    assert page.table.item(2, 1).text() == "offline"
    assert "none" in page.selected_label.text()  # multiple devices -> no auto-select
    page.table.selectRow(1)
    assert ctx.controller.selected_serial == "127.0.0.1:5555"
    assert "127.0.0.1:5555" in ctx.window.device_status_label.text()


def test_dashboard_reflects_single_device(qtbot, make_app):
    ctx = make_app(standard_runner(DEVICES_ONE))
    ctx.controller.refresh_devices()
    card = ctx.window.dashboard_page.device_card
    qtbot.waitUntil(lambda: card.badge.text_value == "Online", timeout=3000)
    assert ctx.window.dashboard_page.adb_card.badge.text_value == "Connected"


def test_device_info_panel(qtbot, make_app):
    ctx = make_app(standard_runner(DEVICES_ONE))
    page = ctx.window.emulator_page
    ctx.controller.refresh_devices()
    qtbot.waitUntil(lambda: page.info_btn.isEnabled(), timeout=3000)
    page.info_btn.click()
    qtbot.waitUntil(lambda: page.info_fields["android"].text() == "13", timeout=3000)
    assert page.info_fields["resolution"].text() == "1080 x 2400"


def test_settings_save_persists_and_validates(qtbot, make_app):
    ctx = make_app()
    page = ctx.window.settings_page
    page.adb_path_edit.setText("/new/adb")
    page.refresh_spin.setValue(12)
    page.log_level_combo.setCurrentText("DEBUG")
    assert page.is_dirty()
    assert page.save()
    assert not page.is_dirty()
    saved = ctx.config_manager.load().config
    assert saved.adb_path == "/new/adb"
    assert saved.auto_refresh_interval_s == 12
    assert saved.log_level == "DEBUG"

    page.emu_args_edit.setText('--broken "quote')
    assert page.save() is False
    assert page.banner.property("level") == "error"


def test_application_restart_restores_settings(qtbot, make_app):
    ctx = make_app(standard_runner(DEVICES_MULTI))
    ctx.controller.refresh_devices()
    qtbot.waitUntil(lambda: len(ctx.controller.devices) == 3, timeout=3000)
    ctx.controller.select_device("127.0.0.1:5555")
    ctx.window.settings_page.scrcpy_path_edit.setText("/opt/scrcpy")
    ctx.window.settings_page.save()
    ctx.window.close()

    ctx2 = make_app(standard_runner(DEVICES_MULTI), adb_path=None)  # reuse saved config
    assert ctx2.controller.config.scrcpy_path == "/opt/scrcpy"
    ctx2.controller.refresh_devices()
    qtbot.waitUntil(lambda: ctx2.controller.selected_serial == "127.0.0.1:5555", timeout=3000)


def test_corrupted_config_starts_with_defaults(qtbot, make_app):
    path = config_path()
    path.write_text("{{{ broken", encoding="utf-8")
    ctx = make_app(adb_path=None)
    assert ctx.controller.config.adb_path == ""
    assert ctx.startup_warnings
    assert any(p.name.startswith("config.json.corrupt-") for p in path.parent.iterdir())


def test_gui_responsive_during_slow_adb(qtbot, make_app):
    """The event loop must keep running while a slow ADB call is in progress."""
    ctx = make_app(standard_runner(DEVICES_ONE, delay=1.0))
    ticks = []
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(time.monotonic()))
    timer.start(50)
    start = time.monotonic()
    ctx.window.emulator_page.refresh_btn.click()
    assert time.monotonic() - start < 0.2  # click returns immediately
    assert not ctx.window.emulator_page.refresh_btn.isEnabled()  # busy state shown
    qtbot.waitUntil(lambda: ctx.window.emulator_page.table.rowCount() == 1, timeout=4000)
    timer.stop()
    assert len(ticks) >= 10  # ~20 expected over 1s; GUI thread was never blocked
    assert ctx.window.emulator_page.refresh_btn.isEnabled()


def test_close_with_unsaved_settings_can_cancel(qtbot, make_app, monkeypatch):
    ctx = make_app()
    ctx.window.show()
    ctx.window.settings_page.scrcpy_path_edit.setText("/unsaved")
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    ctx.window.close()
    assert ctx.window.isVisible()
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    ctx.window.close()
    assert not ctx.window.isVisible()


# ------------------------------------------------------------------ Phase 2
def test_emulator_manager_has_tabs(make_app):
    page = make_app().window.emulator_page
    assert [page.tabs.tabText(i) for i in range(page.tabs.count())] == [
        "Devices",
        "Applications",
        "Emulator Instances",
    ]


def test_apps_tab_load_filter_and_set_target(qtbot, make_app):
    from tests.fakes.fake_runner import TARGET_PKG

    ctx = make_app(standard_runner(DEVICES_ONE))
    tab = ctx.window.emulator_page.apps_tab
    ctx.controller.refresh_devices()
    qtbot.waitUntil(lambda: ctx.controller.selected_device is not None, timeout=3000)
    tab.load_btn.click()
    qtbot.waitUntil(lambda: tab.list.count() == 3, timeout=3000)
    tab.search_edit.setText("target")
    assert tab.list.count() == 1
    tab.list.setCurrentRow(0)
    tab.set_target_btn.click()
    assert TARGET_PKG in tab.target_label.text()
    assert tab.launch_btn.isEnabled()
    tab.launch_btn.click()
    qtbot.waitUntil(lambda: tab.state_badge.text_value == "Running", timeout=5000)


def test_instances_tab_populates(qtbot, make_app, tmp_path):
    from app.emulator.instances import DiscoveryResult, EmulatorInstance

    exe = tmp_path / "HD-Player.exe"
    exe.write_text("")
    inst = EmulatorInstance("BlueStacks", "Pie64", "BlueStacks App Player", "127.0.0.1:5555", str(exe),
                            ("--instance", "Pie64"), False)
    ctx = make_app()
    ctx.controller._discover = lambda _c: DiscoveryResult([inst], ["ADB access is disabled"], ["x.conf"])
    tab = ctx.window.emulator_page.instances_tab
    tab.scan_btn.click()
    qtbot.waitUntil(lambda: tab.table.rowCount() == 1, timeout=3000)
    assert tab.table.item(0, 3).text() == "127.0.0.1:5555"
    assert tab.table.item(0, 4).text() == "Disabled"
    assert not tab.warn_label.isHidden()
    tab.table.selectRow(0)
    assert tab.connect_btn.isEnabled() and tab.launch_btn.isEnabled()


def test_settings_phase2_fields_persist(make_app):
    ctx = make_app()
    page = ctx.window.settings_page
    page.auto_reconnect_check.setChecked(False)
    page.bs_conf_edit.setText("D:/BlueStacks/bluestacks.conf")
    assert page.save()
    saved = ctx.config_manager.load().config
    assert saved.auto_reconnect_enabled is False
    assert saved.bluestacks_conf_path == "D:/BlueStacks/bluestacks.conf"


# ------------------------------------------------------------------ Phase 3
def test_screen_page_options_persist_and_buttons(make_app):
    ctx = make_app()
    w = ctx.window
    w.navigate_to("Screen Monitor")
    page = w.screen_page
    assert w.stack.currentWidget() is page
    page.fps_spin.setValue(45)
    page.view_only_check.setChecked(True)
    saved = ctx.config_manager.load().config
    assert saved.scrcpy_max_fps == 45 and saved.scrcpy_view_only is True
    assert page.start_btn.isEnabled() and not page.stop_btn.isEnabled()
    assert ctx.window.dashboard_page.mirror_card.badge.text_value == "Not running"


def test_screen_page_start_without_scrcpy_shows_error(qtbot, make_app):
    ctx = make_app(standard_runner(DEVICES_ONE))
    ctx.controller.refresh_devices()
    qtbot.waitUntil(lambda: ctx.controller.selected_device is not None, timeout=3000)
    page = ctx.window.screen_page
    page.start_btn.click()
    assert page.banner.property("level") == "error"
    assert "scrcpy" in page.banner.text()


# ------------------------------------------------------------------ Phase 4
def test_pgsharp_page_calibration_flow(qtbot, make_app, monkeypatch):
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QInputDialog

    from tests.fakes.fake_device import MENU

    ctx = make_app()
    page = ctx.window.pgsharp_page
    pg = ctx.window.pgsharp
    pg.image = QImage.fromData(MENU, "PNG")
    page._on_image(pg.image)
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Menu button", True))
    page.el_add_btn.click()
    page.canvas.clicked.emit(0.25, 0.75)
    assert "menu_button" in pg.layout.elements
    assert page.el_list.count() == 1
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Menu open", True))
    page.st_new_btn.click()
    assert page.mode_rect.isChecked()
    page.canvas.rect_selected.emit(0.0, 0.0, 0.5, 0.1)
    assert len(pg.layout.states["menu_open"].regions) == 1
    page.ft_table.selectRow(1)  # teleport
    page.ft_avail.setCurrentText("Available")
    page.ft_steps.setText("menu_button")
    page.ft_verify.setCurrentIndex(page.ft_verify.findData("menu_open"))
    assert page._save_feature()
    fm = pg.layout.features["teleport"]
    assert fm.open_steps == ["menu_button"] and fm.verify_state == "menu_open"
    page.ft_steps.setText("does_not_exist")
    assert page._save_feature() is False
    assert page.banner.property("level") == "error"
