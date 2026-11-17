"""Screen-region comparison used to verify UI states.

Regions are reduced to 32x32 grayscale "signatures" and compared by mean absolute
difference. This is deliberately simple and deterministic: it confirms that a
screen region looks like the calibrated reference, nothing more. QImage is safe
to use on worker threads.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QImage

from app.pgsharp.layout import RegionTemplate, ScreenState

SIG_SIZE = 32


def crop_normalized(image: QImage, x: float, y: float, w: float, h: float) -> QImage:
    iw, ih = image.width(), image.height()
    rect = QRect(round(x * iw), round(y * ih), max(1, round(w * iw)), max(1, round(h * ih)))
    return image.copy(rect.intersected(image.rect()))


def signature(image: QImage) -> bytes:
    small = image.scaled(
        SIG_SIZE, SIG_SIZE, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation
    ).convertToFormat(QImage.Format.Format_Grayscale8)
    bpl = small.bytesPerLine()
    raw = bytes(small.constBits())
    return b"".join(raw[r * bpl : r * bpl + SIG_SIZE] for r in range(SIG_SIZE))


def encode(sig: bytes) -> str:
    return base64.b64encode(sig).decode("ascii")


def decode(text: str) -> bytes:
    data = base64.b64decode(text.encode("ascii"), validate=True)
    if len(data) != SIG_SIZE * SIG_SIZE:
        raise ValueError("signature has wrong size")
    return data


def difference(a: bytes, b: bytes) -> float:
    """Mean absolute difference in 0..1."""
    if len(a) != len(b) or not a:
        raise ValueError("signatures differ in size")
    return sum(abs(x - y) for x, y in zip(a, b, strict=True)) / (255 * len(a))


def make_region(image: QImage, x: float, y: float, w: float, h: float) -> RegionTemplate:
    return RegionTemplate(x, y, w, h, encode(signature(crop_normalized(image, x, y, w, h))))


@dataclass(frozen=True)
class StateMatch:
    state_id: str
    name: str
    matched: bool | None  # None = state has no regions, cannot be verified
    score: float  # worst region difference (lower is better)
    region_scores: tuple[float, ...]


def verify_state(image: QImage, state: ScreenState) -> StateMatch:
    if not state.regions:
        return StateMatch(state.id, state.name, None, 1.0, ())
    scores = tuple(
        difference(signature(crop_normalized(image, r.x, r.y, r.w, r.h)), decode(r.signature)) for r in state.regions
    )
    worst = max(scores)
    return StateMatch(state.id, state.name, worst <= state.threshold, worst, scores)


def detect_states(image: QImage, states: list[ScreenState]) -> list[StateMatch]:
    """Verify all states; matched ones first, best score first."""
    results = [verify_state(image, s) for s in states]
    return sorted(results, key=lambda m: (m.matched is not True, m.score))
