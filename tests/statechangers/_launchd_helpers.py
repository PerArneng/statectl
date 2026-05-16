from __future__ import annotations

from pathlib import Path

from statectl._statechangers import (
    EnsureLaunchdAgentParameters,
    EnsureLaunchdAgentStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


HOME: Path = Path("/Users/test")
USER_AGENTS_DIR: Path = HOME / "Library" / "LaunchAgents"
SYSTEM_DAEMONS_DIR: Path = Path("/Library/LaunchDaemons")

DEFAULT_LABEL: str = "com.example.foo"
DEFAULT_DOMAIN: str = "gui/501"


def make_plist(label: str = DEFAULT_LABEL) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<plist version="1.0">\n'
        "<dict>\n"
        f"  <key>Label</key><string>{label}</string>\n"
        "  <key>ProgramArguments</key>\n"
        "  <array><string>/usr/bin/true</string></array>\n"
        "</dict>\n"
        "</plist>\n"
    )


def make_fs_with_user_agents_dir() -> InMemoryFileSystem:
    fs = InMemoryFileSystem()
    fs.add_dir(HOME)
    fs.add_dir(HOME / "Library")
    fs.add_dir(USER_AGENTS_DIR)
    return fs


def make_fs_with_system_daemons_dir() -> InMemoryFileSystem:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/Library"))
    fs.add_dir(SYSTEM_DAEMONS_DIR)
    return fs


def make_env_darwin() -> ScriptedEnv:
    return ScriptedEnv.darwin(home=HOME)


def make_pr_with_launchctl() -> ScriptedProcessRunner:
    pr = ScriptedProcessRunner()
    pr.register_executable("launchctl")
    return pr


def make_changer(
    *,
    fs: InMemoryFileSystem | None = None,
    pr: ScriptedProcessRunner | None = None,
    env: ScriptedEnv | None = None,
    label: str = DEFAULT_LABEL,
    plist_content: str | None = None,
    scope: str = "user",
    loaded: bool = True,
    domain_target: str | None = DEFAULT_DOMAIN,
) -> EnsureLaunchdAgentStateChanger:
    fs = fs if fs is not None else make_fs_with_user_agents_dir()
    pr = pr if pr is not None else make_pr_with_launchctl()
    env = env if env is not None else make_env_darwin()
    plist_content = plist_content if plist_content is not None else make_plist(label)
    return EnsureLaunchdAgentStateChanger(
        EnsureLaunchdAgentParameters(
            label=label,
            plist_content=plist_content,
            scope=scope,  # type: ignore[arg-type]
            loaded=loaded,
            domain_target=domain_target,
        ),
        file_system=fs,
        process_runner=pr,
        env=env,
    )
