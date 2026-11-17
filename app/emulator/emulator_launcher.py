"""Launch the user's existing emulator executable (no emulator brand is assumed)."""

from __future__ import annotations

import logging
import shlex
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


class EmulatorLaunchError(Exception):
    pass


def split_args(text: str) -> list[str]:
    """Split a user-entered argument string. Quoted segments may contain spaces.

    Uses non-POSIX rules so Windows backslashes are preserved, then strips quotes.
    """
    text = text.strip()
    if not text:
        return []
    try:
        parts = shlex.split(text, posix=False)
    except ValueError as exc:
        raise EmulatorLaunchError(f"Invalid emulator arguments: {exc}") from exc
    return [p[1:-1] if len(p) >= 2 and p[0] == p[-1] and p[0] in "\"'" else p for p in parts]


def build_command(executable: str, args: str) -> list[str]:
    path = Path(executable.strip()) if executable else None
    if not path or not str(path):
        raise EmulatorLaunchError("Emulator executable path is not configured. Set it in Settings.")
    if not path.is_file():
        raise EmulatorLaunchError(f"Emulator executable not found: {path}")
    return [str(path), *split_args(args)]


def join_args(args: list[str] | tuple[str, ...]) -> str:
    """Inverse of :func:`split_args` for storing arguments in settings."""
    return " ".join(f'"{a}"' if (" " in a or not a) else a for a in args)


def launch_emulator(executable: str, args: str = "") -> int:
    """Start the emulator detached from PokePilot. Returns the process id."""
    return launch_command(build_command(executable, args))


def launch_command(cmd: list[str]) -> int:
    """Start an already-built command detached from PokePilot. Returns the process id."""
    if not cmd or not Path(cmd[0]).is_file():
        raise EmulatorLaunchError(f"Emulator executable not found: {cmd[0] if cmd else '<empty>'}")
    kwargs: dict = {
        "cwd": str(Path(cmd[0]).parent),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        )
    else:
        kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(cmd, **kwargs)  # noqa: S603 - argument list, no shell
    except OSError as exc:
        raise EmulatorLaunchError(f"Failed to start emulator: {exc}") from exc
    logger.info("Launched emulator (pid %s): %s", proc.pid, cmd)
    return proc.pid
