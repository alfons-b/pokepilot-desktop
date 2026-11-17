"""scrcpy command construction, version parsing and executable discovery (pure logic)."""

from __future__ import annotations

import logging
import re
import shutil
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from app.emulator.adb_client import AdbError, CommandRunner, subprocess_runner

logger = logging.getLogger(__name__)

_VERSION_RE = re.compile(r"scrcpy\s+v?(?P<major>\d+)\.(?P<minor>\d+)(?:\.(?P<patch>\d+))?")
MAX_SIZE_CHOICES = (0, 720, 1024, 1280, 1600, 1920)  # 0 = native resolution


class ScrcpyError(Exception):
    pass


@dataclass(frozen=True)
class ScrcpyVersion:
    major: int
    minor: int
    patch: int = 0

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    def at_least(self, major: int, minor: int = 0) -> bool:
        return (self.major, self.minor) >= (major, minor)


@dataclass(frozen=True)
class ScrcpyOptions:
    max_size: int = 1280  # longest side in pixels; 0 = native
    max_fps: int = 30
    bitrate_mbps: int = 8
    fullscreen: bool = False
    always_on_top: bool = False
    stay_awake: bool = True
    view_only: bool = False  # --no-control: mirror without forwarding mouse/keyboard
    uhid_keyboard: bool = False  # physical keyboard simulation (scrcpy >= 2.4)
    show_touches: bool = False
    window_title: str = "PokePilot - Android"

    def validate(self) -> None:
        if self.max_size < 0 or (0 < self.max_size < 240) or self.max_size > 4096:
            raise ScrcpyError("Max size must be 0 (native) or between 240 and 4096.")
        if not 1 <= self.max_fps <= 120:
            raise ScrcpyError("FPS must be between 1 and 120.")
        if not 1 <= self.bitrate_mbps <= 100:
            raise ScrcpyError("Bitrate must be between 1 and 100 Mbps.")


def parse_version(text: str) -> ScrcpyVersion | None:
    m = _VERSION_RE.search(text)
    if not m:
        return None
    return ScrcpyVersion(int(m.group("major")), int(m.group("minor")), int(m.group("patch") or 0))


def build_args(serial: str, options: ScrcpyOptions, version: ScrcpyVersion | None = None) -> list[str]:
    """Build scrcpy arguments (without the executable). Version-aware for renamed flags."""
    if not serial:
        raise ScrcpyError("A device serial is required.")
    options.validate()
    modern = version is None or version.at_least(2, 0)
    args = [f"--serial={serial}", f"--max-fps={options.max_fps}", f"--window-title={options.window_title}"]
    if options.max_size:
        args.append(f"--max-size={options.max_size}")
    args.append(f"--video-bit-rate={options.bitrate_mbps}M" if modern else f"--bit-rate={options.bitrate_mbps}M")
    if modern:
        args.append("--no-audio")  # game audio is not needed and audio capture can fail on emulators
    if options.fullscreen:
        args.append("--fullscreen")
    if options.always_on_top:
        args.append("--always-on-top")
    if options.stay_awake and not options.view_only:
        args.append("--stay-awake")
    if options.view_only:
        args.append("--no-control")
    elif options.uhid_keyboard and (version is None or version.at_least(2, 4)):
        args.append("--keyboard=uhid")
    if options.show_touches and not options.view_only:
        args.append("--show-touches")
    return args


def candidate_paths(
    configured: str = "",
    env: Mapping[str, str] | None = None,
    platform: str | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> list[str]:
    import os

    env = os.environ if env is None else env
    platform = platform or sys.platform
    out: list[str] = []
    if configured:
        out.append(configured)
    if found := which("scrcpy"):
        out.append(found)
    if platform == "win32":
        local = env.get("LOCALAPPDATA", "")
        home = env.get("USERPROFILE", "")
        if local:
            out.append(rf"{local}\Microsoft\WinGet\Links\scrcpy.exe")
        if home:
            out.append(rf"{home}\scoop\shims\scrcpy.exe")
        out += [r"C:\scrcpy\scrcpy.exe", r"C:\Program Files\scrcpy\scrcpy.exe", r"C:\tools\scrcpy\scrcpy.exe"]
    return list(dict.fromkeys(out))


def verify_scrcpy(path: str, runner: CommandRunner = subprocess_runner) -> ScrcpyVersion:
    if not path or not Path(path).is_file():
        raise ScrcpyError(f"scrcpy executable not found: {path or '<empty>'}")
    try:
        result = runner([path, "--version"], 15.0)
    except AdbError as exc:  # runner errors share the ADB exception hierarchy
        raise ScrcpyError(str(exc)) from exc
    version = parse_version(result.output)
    if version is None:
        raise ScrcpyError(f"'{path}' did not identify itself as scrcpy.")
    return version


def locate_scrcpy(configured: str = "", runner: CommandRunner = subprocess_runner) -> tuple[str, ScrcpyVersion] | None:
    for path in candidate_paths(configured):
        try:
            return path, verify_scrcpy(path, runner)
        except ScrcpyError as exc:
            logger.debug("scrcpy candidate rejected: %s", exc)
    return None
