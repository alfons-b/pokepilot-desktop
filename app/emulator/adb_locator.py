"""Find an ADB executable on this machine.

Candidates are only *suggestions*; each is verified by running ``adb version``.
Bundled ADB binaries of popular emulators are included as candidates because
users often have no Android SDK installed, but no emulator brand is assumed.
"""

from __future__ import annotations

import logging
import ntpath
import os
import posixpath
import shutil
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

from app.emulator.adb_client import AdbClient, AdbError, CommandRunner, subprocess_runner

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AdbCandidate:
    path: str
    source: str


@dataclass(frozen=True)
class AdbLocation:
    path: str
    source: str
    version: str


# Relative to Program Files / drive roots. Emulator-bundled adb executables.
_WINDOWS_BUNDLED = [
    ("BlueStacks 5", r"{pf}\BlueStacks_nxt\HD-Adb.exe"),
    ("BlueStacks", r"{pf}\BlueStacks\HD-Adb.exe"),
    ("LDPlayer 9", r"C:\LDPlayer\LDPlayer9\adb.exe"),
    ("LDPlayer 4", r"C:\LDPlayer\LDPlayer4.0\adb.exe"),
    ("MuMu Player 12", r"{pf}\Netease\MuMuPlayer-12.0\shell\adb.exe"),
    ("MuMu Player 12", r"{pf}\Netease\MuMu Player 12\shell\adb.exe"),
    ("Nox", r"{pf86}\Nox\bin\nox_adb.exe"),
    ("MEmu", r"{pf}\Microvirt\MEmu\adb.exe"),
]


def _adb_name(platform: str) -> str:
    return "adb.exe" if platform == "win32" else "adb"


def candidate_adb_paths(
    configured: str | None = None,
    env: Mapping[str, str] | None = None,
    platform: str | None = None,
    which: Callable[[str], str | None] = shutil.which,
    home: Path | None = None,
) -> list[AdbCandidate]:
    """Return de-duplicated candidate paths in priority order (not yet verified)."""
    env = os.environ if env is None else env
    platform = platform or sys.platform
    home = home or Path.home()
    exe = _adb_name(platform)
    pure = PureWindowsPath if platform == "win32" else PurePosixPath
    out: list[AdbCandidate] = []

    def add(path: str | None, source: str) -> None:
        if path:
            out.append(AdbCandidate(str(path), source))

    add(configured, "Configured path")
    add(which("adb"), "System PATH")
    for var in ("ANDROID_SDK_ROOT", "ANDROID_HOME"):
        if env.get(var):
            add(str(pure(env[var]) / "platform-tools" / exe), f"{var} environment variable")

    if platform == "win32":
        local = env.get("LOCALAPPDATA")
        if local:
            add(str(pure(local) / "Android" / "Sdk" / "platform-tools" / exe), "Android Studio SDK")
        pf = env.get("ProgramFiles", r"C:\Program Files")
        pf86 = env.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        for name, template in _WINDOWS_BUNDLED:
            add(template.format(pf=pf, pf86=pf86), f"{name} (bundled)")
        add(r"C:\platform-tools\adb.exe", "C:\\platform-tools")
    elif platform == "darwin":
        add(str(home / "Library" / "Android" / "sdk" / "platform-tools" / exe), "Android Studio SDK")
    else:
        add(str(home / "Android" / "Sdk" / "platform-tools" / exe), "Android Studio SDK")

    pathmod = ntpath if platform == "win32" else posixpath
    seen: set[str] = set()
    unique: list[AdbCandidate] = []
    for c in out:
        key = pathmod.normcase(pathmod.normpath(c.path))
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique


def verify_adb(path: str, runner: CommandRunner = subprocess_runner, timeout: float = 10.0) -> str:
    """Return the ADB version string or raise :class:`AdbError`."""
    if not path:
        raise AdbError("No path given.")
    if not Path(path).is_file():
        raise AdbError(f"File does not exist: {path}")
    return AdbClient(path, runner=runner, timeout=timeout).version()


def locate_adb(
    configured: str | None = None,
    runner: CommandRunner = subprocess_runner,
    candidates: list[AdbCandidate] | None = None,
) -> AdbLocation | None:
    """Return the first candidate that runs and identifies as ADB, or None."""
    for cand in candidates if candidates is not None else candidate_adb_paths(configured):
        try:
            version = verify_adb(cand.path, runner=runner)
        except AdbError as exc:
            logger.debug("ADB candidate rejected (%s): %s", cand.source, exc)
            continue
        logger.info("Found ADB %s at %s (%s)", version, cand.path, cand.source)
        return AdbLocation(cand.path, cand.source, version)
    logger.warning("No working ADB executable found.")
    return None
