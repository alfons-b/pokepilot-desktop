from app.emulator import bluestacks
from app.emulator.bluestacks import instances_from_conf, parse_conf

CONF = """\
bst.enable_adb_access="1"
bst.installed_images="Pie64,Rvc64"
bst.instance.Pie64.display_name="BlueStacks App Player"
bst.instance.Pie64.status.adb_port="5555"
bst.instance.Rvc64.display_name="Android 11"
bst.instance.Rvc64.status.adb_port="5565"
bst.instance.Rvc64.adb_port="5565"
bst.instance.Broken.status.adb_port="notaport"
garbage line without quotes
"""


def test_parse_conf():
    values = parse_conf(CONF)
    assert values["bst.enable_adb_access"] == "1"
    assert values["bst.instance.Pie64.status.adb_port"] == "5555"
    assert "garbage" not in " ".join(values)


def test_instances_from_conf():
    insts = instances_from_conf(parse_conf(CONF), player_exe=r"C:\Program Files\BlueStacks_nxt\HD-Player.exe")
    by_name = {i.name: i for i in insts}
    assert by_name["Pie64"].adb_address == "127.0.0.1:5555"
    assert by_name["Pie64"].display_name == "BlueStacks App Player"
    assert by_name["Pie64"].launch_args == ("--instance", "Pie64")
    assert by_name["Rvc64"].adb_address == "127.0.0.1:5565"
    assert by_name["Pie64"].adb_enabled is True
    assert "Broken" not in by_name  # invalid port and no display name


def test_adb_disabled_and_unknown():
    disabled = instances_from_conf(parse_conf('bst.enable_adb_access="0"\nbst.instance.Pie64.status.adb_port="5555"\n'))
    assert disabled[0].adb_enabled is False
    assert not disabled[0].can_launch  # no player exe known
    unknown = instances_from_conf(parse_conf('bst.instance.Pie64.status.adb_port="5555"\n'))
    assert unknown[0].adb_enabled is None


def _install(tmp_path, conf_text, with_player=True):
    pd = tmp_path / "ProgramData" / "BlueStacks_nxt"
    pf = tmp_path / "Program Files" / "BlueStacks_nxt"
    pd.mkdir(parents=True)
    pf.mkdir(parents=True)
    (pd / "bluestacks.conf").write_text(conf_text, encoding="utf-8")
    if with_player:
        (pf / "HD-Player.exe").write_text("")
    return {"ProgramData": str(tmp_path / "ProgramData"), "ProgramFiles": str(tmp_path / "Program Files")}


def test_discover_from_default_locations(tmp_path):
    env = _install(tmp_path, CONF)
    result = bluestacks.discover(env=env)
    assert len(result.instances) == 2
    assert result.sources and result.sources[0].endswith("bluestacks.conf")
    assert all(i.can_launch for i in result.instances)
    assert result.warnings == []


def test_discover_warns_when_adb_disabled(tmp_path):
    env = _install(tmp_path, CONF.replace('enable_adb_access="1"', 'enable_adb_access="0"'), with_player=False)
    result = bluestacks.discover(env=env)
    assert any("Android Debug Bridge" in w for w in result.warnings)
    assert not any(i.can_launch for i in result.instances)


def test_discover_nothing_installed(tmp_path):
    result = bluestacks.discover(env={"ProgramData": str(tmp_path), "ProgramFiles": str(tmp_path)})
    assert result.instances == [] and result.sources == []


def test_discover_custom_conf_path(tmp_path):
    conf = tmp_path / "custom.conf"
    conf.write_text(CONF, encoding="utf-8")
    result = bluestacks.discover(str(conf), env={"ProgramFiles": str(tmp_path)})
    assert len(result.instances) == 2
    missing = bluestacks.discover(str(tmp_path / "nope.conf"))
    assert missing.warnings and not missing.instances
