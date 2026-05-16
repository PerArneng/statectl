from __future__ import annotations

from pathlib import Path

from statectl._statechangers import (
    EnsureSystemdUnitParameters,
    EnsureSystemdUnitStateChanger,
    SystemdScope,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


HOME: Path = Path("/home/test")
USER_UNIT_DIR: Path = HOME / ".config" / "systemd" / "user"
SYSTEM_UNIT_DIR: Path = Path("/etc/systemd/system")

DEFAULT_UNIT: str = "myapp.service"


def make_unit_content(description: str = "MyApp daemon") -> str:
    return (
        "[Unit]\n"
        f"Description={description}\n"
        "\n"
        "[Service]\n"
        "ExecStart=/usr/bin/true\n"
        "\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )


def make_fs_with_user_unit_dir() -> InMemoryFileSystem:
    fs = InMemoryFileSystem()
    fs.add_dir(HOME)
    fs.add_dir(HOME / ".config")
    fs.add_dir(HOME / ".config" / "systemd")
    fs.add_dir(USER_UNIT_DIR)
    return fs


def make_fs_with_system_unit_dir() -> InMemoryFileSystem:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/etc"))
    fs.add_dir(Path("/etc/systemd"))
    fs.add_dir(SYSTEM_UNIT_DIR)
    return fs


def make_env_linux() -> ScriptedEnv:
    return ScriptedEnv.linux(home=HOME)


def make_pr_with_systemctl() -> ScriptedProcessRunner:
    pr = ScriptedProcessRunner()
    pr.register_executable("systemctl")
    return pr


def make_changer(
    *,
    fs: InMemoryFileSystem | None = None,
    pr: ScriptedProcessRunner | None = None,
    env: ScriptedEnv | None = None,
    unit_name: str = DEFAULT_UNIT,
    unit_content: str | None = None,
    scope: SystemdScope = "user",
    enabled: bool = True,
    started: bool = True,
    reload_on_change: bool = True,
) -> EnsureSystemdUnitStateChanger:
    fs = fs if fs is not None else make_fs_with_user_unit_dir()
    pr = pr if pr is not None else make_pr_with_systemctl()
    env = env if env is not None else make_env_linux()
    unit_content = unit_content if unit_content is not None else make_unit_content()
    return EnsureSystemdUnitStateChanger(
        EnsureSystemdUnitParameters(
            unit_name=unit_name,
            unit_content=unit_content,
            scope=scope,
            enabled=enabled,
            started=started,
            reload_on_change=reload_on_change,
        ),
        file_system=fs,
        process_runner=pr,
        env=env,
    )
