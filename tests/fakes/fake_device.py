"""In-memory device for UiDriver/automation tests: serves scripted screenshots, records input."""

from __future__ import annotations

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRect
from PySide6.QtGui import QColor, QImage, QPainter


def screen_png(width: int = 540, height: int = 1200, box: tuple[int, int, int, int] | None = None,
               color: str = "#000000", bg: str = "#ffffff") -> bytes:
    """A plain screen, optionally with a filled box (x, y, w, h) - used as a recognisable UI feature."""
    img = QImage(width, height, QImage.Format.Format_RGB32)
    img.fill(QColor(bg))
    if box:
        p = QPainter(img)
        p.fillRect(QRect(*box), QColor(color))
        p.end()
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(data)


HOME = screen_png()  # blank screen
MENU = screen_png(box=(0, 0, 270, 120))  # black bar top-left = "menu open"


class FakeDevice:
    """Duck-typed AdbClient subset used by UiDriver."""

    def __init__(self, screens: list[bytes] | None = None) -> None:
        self.screens = list(screens or [HOME])
        self.taps: list[tuple[int, int]] = []
        self.swipes: list[tuple[int, ...]] = []
        self.keys: list[int] = []
        self.fail_next: Exception | None = None
        self.after_tap: bytes | None = None  # screen shown after any tap

    def _maybe_fail(self) -> None:
        if self.fail_next is not None:
            exc, self.fail_next = self.fail_next, None
            raise exc

    def screencap(self, serial: str) -> bytes:
        self._maybe_fail()
        return self.screens[0] if len(self.screens) == 1 else self.screens.pop(0)

    def tap(self, serial: str, x: int, y: int) -> None:
        self._maybe_fail()
        self.taps.append((x, y))
        if self.after_tap is not None:
            self.screens = [self.after_tap]

    def swipe(self, serial: str, *args: int) -> None:
        self._maybe_fail()
        self.swipes.append(tuple(args))

    def keyevent(self, serial: str, code: int) -> None:
        self._maybe_fail()
        self.keys.append(code)

    def get_state(self, serial: str) -> str:
        self._maybe_fail()
        return "device"
