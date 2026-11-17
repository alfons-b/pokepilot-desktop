"""A stand-in ``adb`` executable for integration tests.

Behaviour is selected with the FAKE_ADB_SCENARIO environment variable:
``none`` | ``one`` | ``multi`` | ``fail`` | ``hang``.
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tests.fakes.fake_runner import (  # noqa: E402
    AM_START_OUTPUT,
    DEVICES_MULTI,
    DEVICES_NONE,
    DEVICES_ONE,
    GETPROP_OUTPUT,
    PACKAGES_3RD,
    RESOLVE_OUTPUT,
    TARGET_PKG,
    VERSION_OUTPUT,
    WM_SIZE_OUTPUT,
)


def main(argv: list[str]) -> int:
    scenario = os.environ.get("FAKE_ADB_SCENARIO", "one")
    args = argv[1:]
    if len(args) >= 2 and args[0] == "-s":
        args = args[2:]
    if scenario == "hang":
        time.sleep(6)  # longer than the test timeout; short so Windows pipe cleanup is quick
        return 0
    if args == ["version"]:
        sys.stdout.write(VERSION_OUTPUT)
        return 0
    if scenario == "fail":
        sys.stderr.write("error: protocol fault (couldn't read status): connection reset\n")
        return 1
    if args == ["devices", "-l"]:
        sys.stdout.write({"none": DEVICES_NONE, "one": DEVICES_ONE, "multi": DEVICES_MULTI}[scenario])
        return 0
    if args == ["shell", "getprop"]:
        sys.stdout.write(GETPROP_OUTPUT)
        return 0
    if args == ["shell", "wm", "size"]:
        sys.stdout.write(WM_SIZE_OUTPUT)
        return 0
    if args == ["shell", "pm", "list", "packages", "-3"]:
        sys.stdout.write(PACKAGES_3RD)
        return 0
    if args[:4] == ["shell", "cmd", "package", "resolve-activity"]:
        if args[-1] == TARGET_PKG:
            sys.stdout.write(RESOLVE_OUTPUT)
        else:
            sys.stdout.write("No activity found\n")
        return 0
    if args[:3] == ["shell", "am", "start"]:
        sys.stdout.write(AM_START_OUTPUT)
        return 0
    if args[:2] == ["shell", "pidof"]:
        if args[2] == TARGET_PKG:
            sys.stdout.write("4242\n")
            return 0
        return 1
    if args and args[0] in ("kill-server", "start-server"):
        return 0
    if args and args[0] == "connect":
        sys.stdout.write(f"failed to connect to '{args[1]}': Connection refused\n")
        return 0  # real adb also exits 0 here
    sys.stderr.write(f"fake adb: unsupported {args}\n")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
