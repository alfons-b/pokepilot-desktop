"""Calibrated PGSharp UI layout: elements, screen states and feature mappings (JSON)."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from app.core.fileutil import atomic_write_text, backup_corrupt
from app.pgsharp.features import FEATURE_CATALOG, FEATURES_BY_ID

logger = logging.getLogger(__name__)
LAYOUT_SCHEMA_VERSION = 1
DEFAULT_THRESHOLD = 0.12  # max mean pixel difference (0..1) for a region to match


class Availability(StrEnum):
    UNVERIFIED = "Unverified"
    AVAILABLE = "Available"
    UNAVAILABLE = "Unavailable"


class LayoutError(ValueError):
    pass


def _norm(v: Any, name: str) -> float:
    if not isinstance(v, (int, float)) or isinstance(v, bool) or not 0.0 <= float(v) <= 1.0:
        raise LayoutError(f"{name} must be a number between 0 and 1, got {v!r}")
    return float(v)


def slugify(label: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", label.strip().lower()).strip("_")
    if not slug:
        raise LayoutError("Name must contain letters or digits.")
    return slug[:48]


@dataclass(frozen=True)
class UiElement:
    id: str
    label: str
    x: float
    y: float

    def __post_init__(self) -> None:
        _norm(self.x, "x")
        _norm(self.y, "y")


@dataclass(frozen=True)
class RegionTemplate:
    x: float
    y: float
    w: float
    h: float
    signature: str  # base64 of the 32x32 grayscale reference

    def __post_init__(self) -> None:
        for n in ("x", "y", "w", "h"):
            _norm(getattr(self, n), n)
        if self.w <= 0 or self.h <= 0 or self.x + self.w > 1.0001 or self.y + self.h > 1.0001:
            raise LayoutError("Region must have positive size and lie inside the screen.")


@dataclass
class ScreenState:
    id: str
    name: str
    regions: list[RegionTemplate] = field(default_factory=list)
    threshold: float = DEFAULT_THRESHOLD


@dataclass
class FeatureMapping:
    feature_id: str
    availability: Availability = Availability.UNVERIFIED
    open_steps: list[str] = field(default_factory=list)  # element ids tapped in order
    toggle_element: str | None = None
    verify_state: str | None = None
    notes: str = ""


@dataclass
class PgsharpLayout:
    reference_width: int = 0
    reference_height: int = 0
    elements: dict[str, UiElement] = field(default_factory=dict)
    states: dict[str, ScreenState] = field(default_factory=dict)
    features: dict[str, FeatureMapping] = field(default_factory=dict)
    updated_at: str = ""

    def __post_init__(self) -> None:
        for info in FEATURE_CATALOG:
            self.features.setdefault(info.id, FeatureMapping(info.id))

    # ------------------------------------------------------------- mutation
    def set_reference(self, width: int, height: int) -> None:
        if width <= 0 or height <= 0:
            raise LayoutError("Reference resolution must be positive.")
        self.reference_width, self.reference_height = width, height

    def add_element(self, label: str, x: float, y: float) -> UiElement:
        base = slugify(label)
        eid, n = base, 2
        while eid in self.elements:
            eid, n = f"{base}_{n}", n + 1
        el = UiElement(eid, label.strip(), x, y)
        self.elements[eid] = el
        return el

    def move_element(self, eid: str, x: float, y: float) -> None:
        el = self._element(eid)
        self.elements[eid] = UiElement(eid, el.label, x, y)

    def remove_element(self, eid: str) -> list[str]:
        """Remove an element; returns the feature ids whose mapping referenced it (cleared)."""
        self._element(eid)
        del self.elements[eid]
        touched = []
        for fm in self.features.values():
            if eid in fm.open_steps or fm.toggle_element == eid:
                fm.open_steps = [s for s in fm.open_steps if s != eid]
                if fm.toggle_element == eid:
                    fm.toggle_element = None
                touched.append(fm.feature_id)
        return touched

    def add_state(self, name: str) -> ScreenState:
        base = slugify(name)
        sid, n = base, 2
        while sid in self.states:
            sid, n = f"{base}_{n}", n + 1
        st = ScreenState(sid, name.strip())
        self.states[sid] = st
        return st

    def remove_state(self, sid: str) -> None:
        if sid not in self.states:
            raise LayoutError(f"Unknown screen state '{sid}'.")
        del self.states[sid]
        for fm in self.features.values():
            if fm.verify_state == sid:
                fm.verify_state = None

    def update_feature(self, mapping: FeatureMapping) -> None:
        if mapping.feature_id not in FEATURES_BY_ID:
            raise LayoutError(f"Unknown feature '{mapping.feature_id}'.")
        for s in mapping.open_steps:
            self._element(s)
        if mapping.toggle_element:
            self._element(mapping.toggle_element)
        if mapping.verify_state and mapping.verify_state not in self.states:
            raise LayoutError(f"Unknown screen state '{mapping.verify_state}'.")
        self.features[mapping.feature_id] = mapping

    def _element(self, eid: str) -> UiElement:
        if eid not in self.elements:
            raise LayoutError(f"Unknown UI element '{eid}'.")
        return self.elements[eid]

    # --------------------------------------------------------- compatibility
    def check_resolution(self, width: int, height: int) -> str | None:
        """Return a warning when the current screen no longer matches the calibration."""
        if not self.reference_width or not self.elements and not self.states:
            return None
        ref = self.reference_width / self.reference_height
        cur = width / height
        if abs(ref - cur) / ref > 0.02:
            return (
                f"Screen is {width}x{height} but calibration was done at "
                f"{self.reference_width}x{self.reference_height} (different aspect ratio or orientation). "
                "Recalibrate, or restore the emulator's display settings."
            )
        return None

    # -------------------------------------------------------- serialization
    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": LAYOUT_SCHEMA_VERSION,
            "reference_width": self.reference_width,
            "reference_height": self.reference_height,
            "elements": [asdict(e) for e in self.elements.values()],
            "states": [
                {"id": s.id, "name": s.name, "threshold": s.threshold, "regions": [asdict(r) for r in s.regions]}
                for s in self.states.values()
            ],
            "features": [
                {**asdict(f), "availability": f.availability.value} for f in self.features.values()
            ],
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PgsharpLayout:
        try:
            layout = cls(
                reference_width=int(data.get("reference_width", 0)),
                reference_height=int(data.get("reference_height", 0)),
                updated_at=str(data.get("updated_at", "")),
            )
            for e in data.get("elements", []):
                layout.elements[e["id"]] = UiElement(e["id"], e["label"], e["x"], e["y"])
            for s in data.get("states", []):
                layout.states[s["id"]] = ScreenState(
                    s["id"], s["name"], [RegionTemplate(**r) for r in s.get("regions", [])],
                    float(s.get("threshold", DEFAULT_THRESHOLD)),
                )
            for f in data.get("features", []):
                if f.get("feature_id") not in FEATURES_BY_ID:
                    continue
                layout.update_feature(
                    FeatureMapping(
                        f["feature_id"],
                        Availability(f.get("availability", Availability.UNVERIFIED)),
                        list(f.get("open_steps", [])),
                        f.get("toggle_element"),
                        f.get("verify_state"),
                        str(f.get("notes", "")),
                    )
                )
        except (KeyError, TypeError, ValueError) as exc:
            raise LayoutError(f"Invalid layout data: {exc}") from exc
        return layout


class LayoutStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> tuple[PgsharpLayout, str | None]:
        """Return (layout, warning). Corrupt files are backed up and an empty layout is returned."""
        if not self.path.exists():
            return PgsharpLayout(), None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise LayoutError("root must be an object")
            return PgsharpLayout.from_dict(data), None
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            backup = backup_corrupt(self.path)
            msg = f"PGSharp calibration file was invalid ({exc}); starting empty."
            if backup:
                msg += f" Old file saved as {backup.name}."
            logger.error(msg)
            return PgsharpLayout(), msg

    def save(self, layout: PgsharpLayout) -> None:
        layout.updated_at = datetime.now().isoformat(timespec="seconds")
        atomic_write_text(self.path, json.dumps(layout.to_dict(), indent=2))
