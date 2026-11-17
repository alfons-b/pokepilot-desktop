"""Page for modules scheduled in later phases. States plainly what is not built yet."""

from __future__ import annotations

from PySide6.QtWidgets import QGroupBox, QLabel, QVBoxLayout, QWidget

from app.ui.widgets.common import Page


class PlannedPage(Page):
    def __init__(self, title: str, phase: int, summary: str, features: list[str], parent: QWidget | None = None) -> None:
        super().__init__(title, summary, parent)
        box = QGroupBox(f"Scheduled for Phase {phase}")
        layout = QVBoxLayout(box)
        note = QLabel("This module is not implemented yet. Planned features:")
        note.setObjectName("Muted")
        layout.addWidget(note)
        for feat in features:
            layout.addWidget(QLabel(f"•  {feat}"))
        self.body.addWidget(box)
        self.body.addStretch(1)


PLANNED_PAGES: dict[str, tuple[int, str, list[str]]] = {
    "Screen Monitor": (
        3,
        "Mirror and control the emulator screen with scrcpy.",
        ["Start / stop mirroring", "Fullscreen", "Mouse and keyboard control", "Screenshots",
         "Resolution and FPS settings", "Process monitoring and restart"],
    ),
    "PGSharp Controller": (
        4,
        "Launch PGSharp and map its user-facing controls.",
        ["App discovery and launch", "Running-state detection", "UI coordinate calibration",
         "Feature registry per installed edition", "Post-action screen verification"],
    ),
    "Automation Manager": (
        5,
        "Profile-based, sequential UI automation with explicit state verification.",
        ["Profile create / edit / duplicate / import / export", "Ordered action builder",
         "Timeouts and expected states", "Pause / resume / stop / emergency stop"],
    ),
    "Location Manager": (
        6,
        "Manage location presets and GPX files.",
        ["Location presets with favourites and search", "Coordinate validation",
         "GPX validation and file management", "JSON import / export"],
    ),
}
