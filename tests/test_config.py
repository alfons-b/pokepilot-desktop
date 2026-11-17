import json

from app.core.config import MAX_RECENT_ADDRESSES, AppConfig


def test_missing_file_gives_defaults(config_manager):
    result = config_manager.load()
    assert result.config == AppConfig()
    assert not result.recovered_from_corruption


def test_roundtrip(config_manager):
    cfg = AppConfig(adb_path=r"C:\platform-tools\adb.exe", auto_refresh_interval_s=10, log_level="DEBUG")
    cfg.remember_address("127.0.0.1:5555")
    config_manager.save(cfg)
    loaded = config_manager.load()
    assert loaded.config == cfg
    assert loaded.warnings == []


def test_save_is_atomic_no_temp_files_left(config_manager):
    config_manager.save(AppConfig())
    files = list(config_manager.path.parent.iterdir())
    assert files == [config_manager.path]


def test_corrupted_json_is_backed_up(config_manager):
    config_manager.path.parent.mkdir(parents=True)
    config_manager.path.write_text("{ not json", encoding="utf-8")
    result = config_manager.load()
    assert result.recovered_from_corruption
    assert result.config == AppConfig()
    assert result.backup_path is not None and result.backup_path.exists()
    assert result.backup_path.read_text() == "{ not json"
    assert not config_manager.path.exists()
    assert result.warnings


def test_non_object_root_is_corrupt(config_manager):
    config_manager.path.parent.mkdir(parents=True)
    config_manager.path.write_text("[1, 2, 3]", encoding="utf-8")
    assert config_manager.load().recovered_from_corruption


def test_binary_garbage_is_corrupt(config_manager):
    config_manager.path.parent.mkdir(parents=True)
    config_manager.path.write_bytes(b"\xff\xfe\x00\x81garbage")
    assert config_manager.load().recovered_from_corruption


def test_wrong_types_fall_back_per_field(config_manager):
    config_manager.path.parent.mkdir(parents=True)
    config_manager.path.write_text(
        json.dumps(
            {
                "adb_path": 42,
                "auto_refresh_enabled": "yes",
                "auto_refresh_interval_s": True,  # bool is not an int here
                "adb_command_timeout_s": 15,  # int accepted for float
                "recent_connect_addresses": [1, 2],
                "scrcpy_path": "C:/scrcpy/scrcpy.exe",
                "mystery": 1,
            }
        ),
        encoding="utf-8",
    )
    result = config_manager.load()
    cfg = result.config
    assert cfg.adb_path == ""
    assert cfg.auto_refresh_enabled is True
    assert cfg.auto_refresh_interval_s == 5
    assert cfg.adb_command_timeout_s == 15.0
    assert cfg.recent_connect_addresses == []
    assert cfg.scrcpy_path == "C:/scrcpy/scrcpy.exe"
    assert len(result.warnings) == 5
    assert not result.recovered_from_corruption


def test_out_of_range_values_clamped():
    cfg, warnings = AppConfig.from_dict({"auto_refresh_interval_s": 0, "adb_command_timeout_s": 999.0, "log_level": "loud"})
    assert cfg.auto_refresh_interval_s == 2
    assert cfg.adb_command_timeout_s == 120.0
    assert cfg.log_level == "INFO"
    assert len(warnings) == 3


def test_recent_addresses_mru_and_capped():
    cfg = AppConfig()
    for i in range(MAX_RECENT_ADDRESSES + 3):
        cfg.remember_address(f"127.0.0.1:{5555 + i}")
    cfg.remember_address("127.0.0.1:5556")
    assert cfg.recent_connect_addresses[0] == "127.0.0.1:5556"
    assert len(cfg.recent_connect_addresses) == MAX_RECENT_ADDRESSES
    assert len(set(cfg.recent_connect_addresses)) == MAX_RECENT_ADDRESSES


def test_no_credentials_fields():
    names = set(AppConfig().to_dict())
    assert not any(word in n for n in names for word in ("password", "token", "secret"))
