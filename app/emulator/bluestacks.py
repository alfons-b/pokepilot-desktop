"""BlueStacks 5 instance discovery (read-only).

BlueStacks 5 stores its settings in ``bluestacks.conf`` (``key="value"`` lines)
inside its data directory, normally ``C:\\ProgramData\\BlueStacks_nxt``. Relevant keys:

* ``bst.enable_adb_access="1"`` - Settings > Advanced > Android Debug Bridge.
* ``bst.instance.<id>.status.adb_port="5555"`` - ADB port of each instance.
* ``bst.instance.<id>.display_name="BlueStacks App Player"``

PokePilot only reads this file; it never writes to it.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from app.emulator.instances import DiscoveryResult, EmulatorInstance

logger = logging.getLogger(__name__)

PROVIDER = "BlueStacks"
# Standard edition and the MSI App Player edition (also BlueStacks 5).
_VARIANTS = ("BlueStacks_nxt", "BlueStacks_msi5")
_LINE_RE = re.compile(r'^\s*(?P<key>[\w.\-]+)\s*=\s*"(?P<value>[^"]*)"\s*$')
_PORT_KEY_RE = re.compile(r"^bst\.instance\.(?P<id>[^.]+)\.(?:status\.)?adb_port$")
_NAME_KEY_RE = re.compile(r"^bst\.instance\.(?P<id>[^.]+)\.display_name$")


@dataclass(frozen=True)
class BlueStacksInstall:
    variant: str
    install_dir: Path | None
    conf_path: Path

    @property
    def player_exe(self) -> Path | None:
        return self.install_dir / "HD-Player.exe" if self.install_dir else None


def parse_conf(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        m = _LINE_RE.match(line)
        if m:
            values[m.group("key")] = m.group("value")
    return values


def instances_from_conf(values: dict[str, str], player_exe: str | None = None) -> list[EmulatorInstance]:
    adb_flag = values.get("bst.enable_adb_access")
    adb_enabled = None if adb_flag is None else adb_flag == "1"
    ports: dict[str, int] = {}
    names: dict[str, str] = {}
    for key, value in values.items():
        if m := _PORT_KEY_RE.match(key):
            if value.isdigit() and 0 < int(value) < 65536:
                ports[m.group("id")] = int(value)
        elif m := _NAME_KEY_RE.match(key):
            names[m.group("id")] = value
    ids = sorted(set(ports) | set(names))
    return [
        EmulatorInstance(
            provider=PROVIDER,
            name=iid,
            display_name=names.get(iid) or iid,
            adb_address=f"127.0.0.1:{ports[iid]}" if iid in ports else None,
            launch_executable=player_exe,
            launch_args=("--instance", iid) if player_exe else (),
            adb_enabled=adb_enabled,
        )
        for iid in ids
    ]


def _registry_dirs(variant: str) -> tuple[str | None, str | None]:
    """Return (InstallDir, UserDefinedDir) from the registry on Windows."""
    if sys.platform != "win32":
        return None, None
    try:
        import winreg  # type: ignore[import-not-found]

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\{variant}") as key:
            def get(name: str) -> str | None:
                try:
                    return str(winreg.QueryValueEx(key, name)[0])
                except OSError:
                    return None

            return get("InstallDir"), get("UserDefinedDir")
    except OSError:
        return None, None


def find_installs(env: dict[str, str] | None = None) -> list[BlueStacksInstall]:
    env = dict(os.environ) if env is None else env
    program_data = env.get("ProgramData", r"C:\ProgramData")
    program_files = env.get("ProgramFiles", r"C:\Program Files")
    found: list[BlueStacksInstall] = []
    for variant in _VARIANTS:
        reg_install, reg_data = _registry_dirs(variant)
        data_dir = Path(reg_data) if reg_data else Path(program_data) / variant
        install_dir = Path(reg_install) if reg_install else Path(program_files) / variant
        conf = data_dir / "bluestacks.conf"
        if conf.is_file():
            found.append(BlueStacksInstall(variant, install_dir if install_dir.is_dir() else None, conf))
    return found


def discover(conf_override: str = "", env: dict[str, str] | None = None) -> DiscoveryResult:
    result = DiscoveryResult()
    if conf_override:
        conf = Path(conf_override)
        default_install = Path((env or os.environ).get("ProgramFiles", r"C:\Program Files")) / _VARIANTS[0]
        install_dir = default_install if default_install.is_dir() else None
        installs = [BlueStacksInstall("custom", install_dir, conf)] if conf.is_file() else []
        if not installs:
            result.warnings.append(f"BlueStacks config file not found: {conf}")
    else:
        installs = find_installs(env)
    for inst in installs:
        try:
            text = inst.conf_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            result.warnings.append(f"Cannot read {inst.conf_path}: {exc}")
            continue
        result.sources.append(str(inst.conf_path))
        exe = inst.player_exe
        found = instances_from_conf(parse_conf(text), str(exe) if exe and exe.is_file() else None)
        if not found:
            result.warnings.append(f"No instances listed in {inst.conf_path}.")
        if any(i.adb_enabled is False for i in found):
            result.warnings.append(
                "ADB access is disabled in BlueStacks. Enable it in BlueStacks Settings > Advanced > "
                "Android Debug Bridge (ADB), then restart the instance."
            )
        result.instances.extend(found)
    logger.info("BlueStacks discovery: %d instance(s) from %d file(s)", len(result.instances), len(result.sources))
    return result
