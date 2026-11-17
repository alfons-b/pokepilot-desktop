"""Location Manager: location presets and GPX files (files and configuration only)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.locations.gpx import GpxError
from app.locations.models import LocationError, LocationPreset, format_coordinates, parse_coordinates
from app.locations.repository import GpxRepository, LocationRepository
from app.ui.widgets.common import Banner, Page, hbox, make_button

NOTE = (
    "PokePilot stores and validates locations and GPX files. To use one, apply it through PGSharp's own "
    "teleport / GPX screens: 'Copy Coordinates' puts 'latitude, longitude' on the clipboard for pasting."
)


class LocationDialog(QDialog):
    def __init__(self, loc: LocationPreset | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Location" if loc else "Add Location")
        self.setMinimumWidth(420)
        self.name_edit = QLineEdit(loc.name if loc else "")
        self.coord_edit = QLineEdit(loc.coordinates if loc else "")
        self.coord_edit.setPlaceholderText("-6.208800, 106.845600")
        self.notes_edit = QLineEdit(loc.notes if loc else "")
        self.fav_check = QCheckBox("Favorite")
        self.fav_check.setChecked(bool(loc and loc.favorite))
        self.error = QLabel()
        self.error.setObjectName("Banner")
        self.error.setProperty("level", "error")
        self.error.hide()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        f = QFormLayout()
        f.addRow("Name:", self.name_edit)
        f.addRow("Coordinates:", self.coord_edit)
        f.addRow("Notes:", self.notes_edit)
        f.addRow(self.fav_check)
        lay = QVBoxLayout(self)
        lay.addLayout(f)
        lay.addWidget(self.error)
        lay.addWidget(buttons)
        self._id = loc.id if loc else None
        self.result_location: LocationPreset | None = None

    def build(self) -> LocationPreset:
        lat, lon = parse_coordinates(self.coord_edit.text())
        loc = LocationPreset(self.name_edit.text(), lat, lon, self.notes_edit.text().strip(),
                             self.fav_check.isChecked(), self._id)
        loc.validate()
        return loc

    def _accept(self) -> None:
        try:
            self.result_location = self.build()
        except LocationError as exc:
            self.error.setText(str(exc))
            self.error.show()
            return
        self.accept()


class LocationPage(Page):
    def __init__(self, locations: LocationRepository, gpx: GpxRepository, parent: QWidget | None = None) -> None:
        super().__init__("Location Manager", "Location presets and GPX routes.", parent)
        self._locs = locations
        self._gpx = gpx
        self.banner = Banner()
        self.body.addWidget(self.banner)
        note = QLabel(NOTE)
        note.setObjectName("Muted")
        note.setWordWrap(True)
        self.body.addWidget(note)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_presets(), "Presets")
        self.tabs.addTab(self._build_gpx(), "GPX Files")
        self.body.addWidget(self.tabs, 1)
        self.refresh_presets()
        self.refresh_gpx()

    # ============================================================ presets
    def _build_presets(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 8, 0, 0)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search name or notes")
        self.search_edit.textChanged.connect(lambda _t: self.refresh_presets())
        self.fav_only = QCheckBox("Favorites only")
        self.fav_only.toggled.connect(lambda _b: self.refresh_presets())
        self.loc_table = QTableWidget(0, 5)
        self.loc_table.setHorizontalHeaderLabels(["", "Name", "Latitude", "Longitude", "Notes"])
        self.loc_table.verticalHeader().setVisible(False)
        self.loc_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.loc_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.loc_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.loc_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.loc_table.horizontalHeader().setStretchLastSection(True)
        self.loc_table.doubleClicked.connect(lambda _i: self._edit_location())
        self.add_btn = make_button("Add", "primary")
        self.edit_btn = make_button("Edit")
        self.delete_btn = make_button("Delete")
        self.fav_btn = make_button("Toggle Favorite")
        self.copy_btn = make_button("Copy Coordinates")
        self.import_btn = make_button("Import JSON...")
        self.export_btn = make_button("Export JSON...")
        self.add_btn.clicked.connect(self._add_location)
        self.edit_btn.clicked.connect(self._edit_location)
        self.delete_btn.clicked.connect(self._delete_location)
        self.fav_btn.clicked.connect(self._toggle_favorite)
        self.copy_btn.clicked.connect(self._copy)
        self.import_btn.clicked.connect(self._import)
        self.export_btn.clicked.connect(self._export)
        self.count_label = QLabel()
        self.count_label.setObjectName("Muted")
        lay.addLayout(hbox(self.search_edit, self.fav_only, stretch_end=False))
        lay.addWidget(self.loc_table, 1)
        lay.addLayout(hbox(self.add_btn, self.edit_btn, self.delete_btn, self.fav_btn, self.copy_btn))
        lay.addLayout(hbox(self.import_btn, self.export_btn, self.count_label))
        return w

    def refresh_presets(self) -> None:
        self._shown = self._locs.search(self.search_edit.text(), self.fav_only.isChecked())
        self.loc_table.setRowCount(len(self._shown))
        for row, loc in enumerate(self._shown):
            for col, text in enumerate(["★" if loc.favorite else "", loc.name, f"{loc.latitude:.6f}",
                                        f"{loc.longitude:.6f}", loc.notes]):
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, loc.id)
                if col == 0:
                    item.setForeground(Qt.GlobalColor.darkYellow)
                self.loc_table.setItem(row, col, item)
        self.count_label.setText(f"{len(self._shown)} location(s)")

    def _selected_location(self) -> LocationPreset | None:
        rows = self.loc_table.selectionModel().selectedRows()
        return self._shown[rows[0].row()] if rows else None

    def _add_location(self) -> None:
        dlg = LocationDialog(None, self)
        if dlg.exec() and dlg.result_location:
            self._locs.add(dlg.result_location)
            self.refresh_presets()
            self.banner.show_message("ok", f"Added '{dlg.result_location.name}'.")

    def _edit_location(self) -> None:
        loc = self._selected_location()
        if loc is None:
            return
        dlg = LocationDialog(loc, self)
        if dlg.exec() and dlg.result_location:
            try:
                self._locs.update(dlg.result_location)
            except LocationError as exc:
                self.banner.show_message("error", str(exc))
            self.refresh_presets()

    def _delete_location(self) -> None:
        loc = self._selected_location()
        if loc and QMessageBox.question(self, "Delete location", f"Delete '{loc.name}'?") \
                == QMessageBox.StandardButton.Yes:
            self._locs.delete(loc.id)
            self.refresh_presets()

    def _toggle_favorite(self) -> None:
        loc = self._selected_location()
        if loc:
            self._locs.set_favorite(loc.id, not loc.favorite)
            self.refresh_presets()

    def _copy(self) -> None:
        loc = self._selected_location()
        if loc:
            QGuiApplication.clipboard().setText(format_coordinates(loc.latitude, loc.longitude))
            self.banner.show_message("ok", f"Copied {loc.coordinates} - paste it into PGSharp's teleport field.")

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import locations", "", "JSON (*.json)")
        if path:
            self.import_locations(path)

    def import_locations(self, path: str) -> bool:
        try:
            report = self._locs.import_json(Path(path).read_text(encoding="utf-8"))
        except (OSError, LocationError, UnicodeDecodeError) as exc:
            self.banner.show_message("error", f"Import failed: {exc}")
            return False
        self.refresh_presets()
        msg = f"Imported {report.added} location(s)."
        if report.skipped:
            msg += f" Skipped {len(report.skipped)}: " + "; ".join(report.skipped[:3])
        self.banner.show_message("warn" if report.skipped else "ok", msg)
        return True

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export locations", "locations.json", "JSON (*.json)")
        if path:
            self.export_locations(path)

    def export_locations(self, path: str) -> bool:
        try:
            Path(path).write_text(self._locs.export_json(self._shown), encoding="utf-8")
        except OSError as exc:
            self.banner.show_message("error", f"Export failed: {exc}")
            return False
        self.banner.show_message("ok", f"Exported {len(self._shown)} location(s).")
        return True

    # ================================================================ GPX
    def _build_gpx(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 8, 0, 0)
        self.gpx_table = QTableWidget(0, 5)
        self.gpx_table.setHorizontalHeaderLabels(["Name", "Points", "Tracks/Routes", "Distance", "File"])
        self.gpx_table.verticalHeader().setVisible(False)
        self.gpx_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.gpx_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.gpx_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.gpx_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.gpx_table.horizontalHeader().setStretchLastSection(True)
        self.gpx_import_btn = make_button("Import GPX...", "primary")
        self.gpx_rename_btn = make_button("Rename")
        self.gpx_validate_btn = make_button("Validate")
        self.gpx_export_btn = make_button("Export Copy...")
        self.gpx_delete_btn = make_button("Delete")
        self.gpx_folder_btn = make_button("Open Folder")
        self.gpx_import_btn.clicked.connect(self._gpx_import)
        self.gpx_rename_btn.clicked.connect(self._gpx_rename)
        self.gpx_validate_btn.clicked.connect(self._gpx_validate)
        self.gpx_export_btn.clicked.connect(self._gpx_export)
        self.gpx_delete_btn.clicked.connect(self._gpx_delete)
        self.gpx_folder_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._gpx.store_dir)))
        )
        hint = QLabel("Imported files are validated and copied to PokePilot's GPX folder. Load them in PGSharp's "
                      "Custom GPX screen (copy them to the emulator's shared folder if needed).")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        box = QGroupBox()
        bl = QVBoxLayout(box)
        bl.addWidget(self.gpx_table, 1)
        bl.addLayout(hbox(self.gpx_import_btn, self.gpx_rename_btn, self.gpx_validate_btn, self.gpx_export_btn,
                          self.gpx_delete_btn, self.gpx_folder_btn))
        bl.addWidget(hint)
        lay.addWidget(box, 1)
        return w

    def refresh_gpx(self) -> None:
        self._gpx_rows = self._gpx.list()
        self.gpx_table.setRowCount(len(self._gpx_rows))
        for row, g in enumerate(self._gpx_rows):
            dist = f"{g.distance_m / 1000:.2f} km" if g.distance_m >= 1000 else f"{g.distance_m:.0f} m"
            vals = [g.name, str(g.point_count), str(g.track_count), dist,
                    Path(g.file_path).name + ("" if g.exists else "  (MISSING)")]
            for col, v in enumerate(vals):
                self.gpx_table.setItem(row, col, QTableWidgetItem(v))

    def _selected_gpx(self):  # noqa: ANN202
        rows = self.gpx_table.selectionModel().selectedRows()
        return self._gpx_rows[rows[0].row()] if rows else None

    def _gpx_import(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Import GPX", "", "GPX (*.gpx);;All files (*)")
        for p in paths:
            self.import_gpx(p)

    def import_gpx(self, path: str) -> bool:
        try:
            _, info = self._gpx.import_file(Path(path))
        except (GpxError, OSError) as exc:
            self.banner.show_message("error", f"{Path(path).name}: {exc}")
            return False
        self.refresh_gpx()
        self.banner.show_message("ok", f"Imported '{info.name}': {info.points + info.waypoints} points, "
                                       f"{info.distance_m / 1000:.2f} km.")
        return True

    def _gpx_rename(self) -> None:
        g = self._selected_gpx()
        if g:
            name, ok = QInputDialog.getText(self, "Rename GPX", "Name:", text=g.name)
            if ok:
                try:
                    self._gpx.rename(g.id, name)
                except GpxError as exc:
                    self.banner.show_message("error", str(exc))
                self.refresh_gpx()

    def _gpx_validate(self) -> None:
        g = self._selected_gpx()
        if g:
            try:
                info = self._gpx.revalidate(g.id)
                self.banner.show_message("ok", f"'{g.name}' is valid: {info.points + info.waypoints} points.")
            except (GpxError, OSError) as exc:
                self.banner.show_message("error", f"'{g.name}' is invalid: {exc}")

    def _gpx_export(self) -> None:
        g = self._selected_gpx()
        if g:
            path, _ = QFileDialog.getSaveFileName(self, "Export GPX", Path(g.file_path).name, "GPX (*.gpx)")
            if path:
                try:
                    self._gpx.export_copy(g.id, Path(path))
                    self.banner.show_message("ok", f"Saved {path}")
                except (GpxError, OSError) as exc:
                    self.banner.show_message("error", str(exc))

    def _gpx_delete(self) -> None:
        g = self._selected_gpx()
        if g and QMessageBox.question(self, "Delete GPX", f"Delete '{g.name}' and its stored copy?") \
                == QMessageBox.StandardButton.Yes:
            self._gpx.delete(g.id)
            self.refresh_gpx()
