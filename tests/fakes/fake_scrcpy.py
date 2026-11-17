"""Stand-in scrcpy executable. FAKE_SCRCPY_MODE: run | crash | silent. FAKE_SCRCPY_LOG: file to record argv/env."""

import os
import sys
import time

if __name__ == "__main__":
    if "--version" in sys.argv:
        print("scrcpy 3.1 <https://github.com/Genymobile/scrcpy>")
        sys.exit(0)
    log = os.environ.get("FAKE_SCRCPY_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(" ".join(sys.argv[1:]) + "\n")
            fh.write("ADB=" + os.environ.get("ADB", "") + "\n")
    mode = os.environ.get("FAKE_SCRCPY_MODE", "run")
    if mode == "crash":
        print("INFO: scrcpy 3.1", flush=True)
        print("ERROR: Could not open video stream", flush=True)
        sys.exit(1)
    if mode == "run":
        print("INFO: Renderer: direct3d", flush=True)
        print("INFO: Texture: 1080x2400", flush=True)
    time.sleep(30)
