import pytest

from app.screen.scrcpy import (
    ScrcpyError,
    ScrcpyOptions,
    ScrcpyVersion,
    build_args,
    candidate_paths,
    parse_version,
    verify_scrcpy,
)
from tests.fakes.fake_runner import FakeRunner


def test_parse_version():
    assert parse_version("scrcpy 3.1 <https://github.com/Genymobile/scrcpy>") == ScrcpyVersion(3, 1, 0)
    assert parse_version("scrcpy v2.4.1") == ScrcpyVersion(2, 4, 1)
    assert parse_version("adb 1.0") is None


def test_build_args_modern_defaults():
    args = build_args("127.0.0.1:5555", ScrcpyOptions(), ScrcpyVersion(3, 1))
    assert "--serial=127.0.0.1:5555" in args
    assert "--max-size=1280" in args and "--max-fps=30" in args
    assert "--video-bit-rate=8M" in args and "--no-audio" in args
    assert "--stay-awake" in args and "--no-control" not in args


def test_build_args_legacy_and_options():
    opts = ScrcpyOptions(max_size=0, fullscreen=True, always_on_top=True, uhid_keyboard=True)
    old = build_args("emulator-5554", opts, ScrcpyVersion(1, 25))
    assert "--bit-rate=8M" in old and "--no-audio" not in old
    assert not any(a.startswith("--max-size") for a in old)
    assert "--keyboard=uhid" not in old  # needs 2.4+
    new = build_args("emulator-5554", opts, ScrcpyVersion(2, 4))
    assert "--fullscreen" in new and "--always-on-top" in new and "--keyboard=uhid" in new


def test_view_only_disables_input_options():
    args = build_args("x:1", ScrcpyOptions(view_only=True, uhid_keyboard=True, show_touches=True))
    assert "--no-control" in args
    assert "--keyboard=uhid" not in args and "--show-touches" not in args and "--stay-awake" not in args


@pytest.mark.parametrize("opts", [ScrcpyOptions(max_fps=0), ScrcpyOptions(max_size=100), ScrcpyOptions(bitrate_mbps=500)])
def test_invalid_options(opts):
    with pytest.raises(ScrcpyError):
        build_args("x:1", opts)


def test_serial_required():
    with pytest.raises(ScrcpyError):
        build_args("", ScrcpyOptions())


def test_candidate_paths_windows():
    paths = candidate_paths("D:/s/scrcpy.exe", env={"LOCALAPPDATA": r"C:\L", "USERPROFILE": r"C:\U"},
                            platform="win32", which=lambda _n: None)
    assert paths[0] == "D:/s/scrcpy.exe"
    assert r"C:\L\Microsoft\WinGet\Links\scrcpy.exe" in paths
    assert r"C:\U\scoop\shims\scrcpy.exe" in paths


def test_verify_scrcpy(tmp_path):
    exe = tmp_path / "scrcpy.exe"
    exe.write_text("")
    r = FakeRunner()
    r.set(["--version"], "scrcpy 2.7 <https://github.com/Genymobile/scrcpy>")
    assert verify_scrcpy(str(exe), r) == ScrcpyVersion(2, 7)
    r.set(["--version"], "something else")
    with pytest.raises(ScrcpyError):
        verify_scrcpy(str(exe), r)
    with pytest.raises(ScrcpyError):
        verify_scrcpy(str(tmp_path / "missing.exe"), r)


def test_verify_real_fake_scrcpy(fake_scrcpy_exe):
    assert verify_scrcpy(str(fake_scrcpy_exe)) == ScrcpyVersion(3, 1)
