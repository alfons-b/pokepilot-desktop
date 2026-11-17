import pytest

from app.emulator.emulator_launcher import EmulatorLaunchError, build_command, split_args


def test_split_args_preserves_backslashes_and_quotes():
    assert split_args(r'--instance "Pie 64" --path C:\data\x') == ["--instance", "Pie 64", "--path", r"C:\data\x"]
    assert split_args("   ") == []


def test_build_command_requires_path():
    with pytest.raises(EmulatorLaunchError, match="not configured"):
        build_command("", "")


def test_build_command_requires_existing_file(tmp_path):
    with pytest.raises(EmulatorLaunchError, match="not found"):
        build_command(str(tmp_path / "missing.exe"), "")


def test_build_command(tmp_path):
    exe = tmp_path / "emu.exe"
    exe.write_text("")
    assert build_command(str(exe), "-a 1") == [str(exe), "-a", "1"]
