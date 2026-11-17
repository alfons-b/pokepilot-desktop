"""Aspect-preserving image view with normalized click/drag coordinates and overlays.

Used for screenshot previews and for UI calibration: clicks are reported as
normalized (0..1) coordinates relative to the image, independent of zoom.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget


@dataclass(frozen=True)
class Marker:
    x: float  # normalized
    y: float
    label: str
    color: str = "#ef4444"


@dataclass(frozen=True)
class RectOverlay:
    x: float
    y: float
    w: float
    h: float
    label: str
    color: str = "#3b82f6"


class ImageView(QWidget):
    clicked = Signal(float, float)  # normalized x, y
    rect_selected = Signal(float, float, float, float)  # normalized x, y, w, h

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._image: QImage | None = None
        self._markers: list[Marker] = []
        self._rects: list[RectOverlay] = []
        self._drag_start: QPointF | None = None
        self._drag_now: QPointF | None = None
        self.rect_mode = False  # when True, drag selects a rectangle instead of clicking
        self.placeholder = "No screenshot yet"
        self.setMinimumSize(200, 200)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.CrossCursor)

    # ----------------------------------------------------------------- data
    def set_image(self, image: QImage | None) -> None:
        self._image = image if image is not None and not image.isNull() else None
        self.update()

    def image(self) -> QImage | None:
        return self._image

    def set_markers(self, markers: list[Marker]) -> None:
        self._markers = list(markers)
        self.update()

    def set_rects(self, rects: list[RectOverlay]) -> None:
        self._rects = list(rects)
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(360, 640)

    # ------------------------------------------------------------- geometry
    def image_rect(self) -> QRectF:
        if self._image is None:
            return QRectF()
        iw, ih = self._image.width(), self._image.height()
        scale = min(self.width() / iw, self.height() / ih)
        w, h = iw * scale, ih * scale
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def to_normalized(self, pos: QPointF) -> tuple[float, float] | None:
        r = self.image_rect()
        if r.isEmpty() or not r.contains(pos):
            return None
        return (pos.x() - r.x()) / r.width(), (pos.y() - r.y()) / r.height()

    def _to_widget(self, x: float, y: float) -> QPointF:
        r = self.image_rect()
        return QPointF(r.x() + x * r.width(), r.y() + y * r.height())

    # --------------------------------------------------------------- events
    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton or self._image is None:
            return
        if self.rect_mode:
            self._drag_start = self._drag_now = event.position()
        else:
            norm = self.to_normalized(event.position())
            if norm:
                self.clicked.emit(*norm)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_start is not None:
            self._drag_now = event.position()
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_start is None:
            return
        a = self.to_normalized(self._drag_start)
        b = self.to_normalized(event.position())
        self._drag_start = self._drag_now = None
        self.update()
        if a and b:
            x, y = min(a[0], b[0]), min(a[1], b[1])
            w, h = abs(a[0] - b[0]), abs(a[1] - b[1])
            if w > 0.005 and h > 0.005:
                self.rect_selected.emit(x, y, w, h)

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#111827"))
        if self._image is None:
            p.setPen(QColor("#9ca3af"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.placeholder)
            return
        r = self.image_rect()
        p.drawImage(r, self._image)
        for rect in self._rects:
            tl = self._to_widget(rect.x, rect.y)
            br = self._to_widget(rect.x + rect.w, rect.y + rect.h)
            p.setPen(QPen(QColor(rect.color), 2))
            p.drawRect(QRectF(tl, br))
            p.drawText(tl + QPointF(3, -4), rect.label)
        for m in self._markers:
            c = self._to_widget(m.x, m.y)
            p.setPen(QPen(QColor("white"), 2))
            p.setBrush(QColor(m.color))
            p.drawEllipse(c, 7, 7)
            p.setPen(QColor("white"))
            p.drawText(c + QPointF(10, 4), m.label)
        if self._drag_start is not None and self._drag_now is not None:
            p.setPen(QPen(QColor("#facc15"), 2, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(QRectF(self._drag_start, self._drag_now).normalized())
