from pathlib import Path

from app.emulator.adb_locator import AdbCandidate, candidate_adb_paths, locate_adb, verify_adb
from tests.fakes.fake_runner import standard_runner


def test_windows_candidates_order_and_dedup():
    env = {
        "ANDROID_SDK_ROOT": r"C:\sdk",
        "ANDROID_HOME": r"C:\sdk",
        "LOCALAPPDATA": r"C:\Users\u\AppData\Local",
        "ProgramFiles": r"C:\Program Files",
    }
    cands = candidate_adb_paths(
        configured=r"D:\tools\adb.exe", env=env, platform="win32", which=lambda _: r"C:\sdk\platform-tools\adb.exe"
    )
    sources = [c.source for c in cands]
    assert sources[0] == "Configured path"
    assert sources[1] == "System PATH"
    # ANDROID_SDK_ROOT/ANDROID_HOME duplicate the PATH entry -> removed
    assert not any("ANDROID_" in s for s in sources)
    assert any("BlueStacks" in s for s in sources)
    assert any(c.path.endswith(r"Android\Sdk\platform-tools\adb.exe") for c in cands)


def test_linux_candidates_without_path():
    cands = candidate_adb_paths(env={}, platform="linux", which=lambda _: None, home=Path("/home/u"))
    assert [c.source for c in cands] == ["Android Studio SDK"]


def test_verify_requires_existing_file(tmp_path):
    import pytest

    from app.emulator.adb_client import AdbError

    with pytest.raises(AdbError):
        verify_adb(str(tmp_path / "missing"), runner=standard_runner())


def test_locate_skips_invalid_candidates(tmp_path):
    good = tmp_path / "good-adb"
    good.write_text("x")
    cands = [AdbCandidate(str(tmp_path / "missing"), "A"), AdbCandidate(str(good), "B")]
    loc = locate_adb(runner=standard_runner(), candidates=cands)
    assert loc is not None
    assert loc.source == "B"
    assert loc.version.startswith("1.0.41")


def test_locate_returns_none_when_nothing_works(tmp_path):
    assert locate_adb(runner=standard_runner(), candidates=[AdbCandidate(str(tmp_path / "x"), "A")]) is None
