"""Shared helpers for the ensure-launchd-agent test suite."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from statectl._interfaces.process import ProcessResult
from statectl._statechangers import (
    EnsureLaunchdAgentParameters,
    EnsureLaunchdAgentRollbackStateChanger,
    EnsureLaunchdAgentStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


LABEL = "com.example.foo"
USER_PLIST_PATH = Path(f"/Users/test/Library/LaunchAgents/{LABEL}.plist")
SYSTEM_PLIST_PATH = Path(f"/Library/LaunchDaemons/{LABEL}.plist")

PLIST_CONTENT = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<plist version="1.0">\n'
    "  <dict>\n"
    "    <key>Label</key>\n"
    f"    <string>{LABEL}</string>\n"
    "  </dict>\n"
    "</plist>\n"
)

OTHER_PLIST_CONTENT = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<plist version="1.0">\n'
    "  <dict>\n"
    "    <key>Label</key>\n"
    "    <string>com.other.tool</string>\n"
    "  </dict>\n"
    "</plist>\n"
)


@dataclass
class Rig:
    fs: InMemoryFileSystem
    pr: ScriptedProcessRunner
    env: ScriptedEnv

    def changer(
        self,
        *,
        label: str = LABEL,
        plist_content: str = PLIST_CONTENT,
        scope: str = "user",
        loaded: bool = True,
        domain_target: str | None = None,
    ) -> EnsureLaunchdAgentStateChanger:
        return EnsureLaunchdAgentStateChanger(
            EnsureLaunchdAgentParameters(
                label=label,
                plist_content=plist_content,
                scope=scope,  # type: ignore[arg-type]
                loaded=loaded,
                domain_target=domain_target,
            ),
            file_system=self.fs,
            process_runner=self.pr,
            env=self.env,
        )

    def rollback(
        self,
        *,
        label: str = LABEL,
        plist_content: str = PLIST_CONTENT,
        scope: str = "user",
        loaded: bool = True,
        domain_target: str | None = None,
    ) -> EnsureLaunchdAgentRollbackStateChanger:
        return EnsureLaunchdAgentRollbackStateChanger(
            EnsureLaunchdAgentParameters(
                label=label,
                plist_content=plist_content,
                scope=scope,  # type: ignore[arg-type]
                loaded=loaded,
                domain_target=domain_target,
            ),
            file_system=self.fs,
            process_runner=self.pr,
            env=self.env,
        )


def make_rig(
    *,
    platform: str = "darwin",
    launchctl_on_path: bool = True,
    create_user_dir: bool = True,
    create_system_dir: bool = False,
) -> Rig:
    fs = InMemoryFileSystem()
    if create_user_dir:
        fs.add_dir(Path("/Users/test"))
        fs.add_dir(Path("/Users/test/Library"))
        fs.add_dir(Path("/Users/test/Library/LaunchAgents"))
    if create_system_dir:
        fs.add_dir(Path("/Library"))
        fs.add_dir(Path("/Library/LaunchDaemons"))
    pr = ScriptedProcessRunner()
    if launchctl_on_path:
        pr.register_executable("launchctl")
    env = (
        ScriptedEnv.darwin(home=Path("/Users/test"))
        if platform == "darwin"
        else ScriptedEnv.linux(home=Path("/home/test"))
    )
    return Rig(fs=fs, pr=pr, env=env)


def script_loaded(pr: ScriptedProcessRunner, loaded: bool) -> None:
    """Register `launchctl list <label>` and `launchctl print ...` to return
    exit 0 (loaded) or exit 1 (not loaded)."""
    exit_code = 0 if loaded else 1
    pr.register(
        ("launchctl", "list"),
        ProcessResult(exit_code=exit_code, stdout="", stderr="", duration_ms=0),
    )
    pr.register(
        ("launchctl", "print"),
        ProcessResult(exit_code=exit_code, stdout="", stderr="", duration_ms=0),
    )


def script_exit(
    pr: ScriptedProcessRunner, prefix: tuple[str, ...], exit_code: int
) -> None:
    pr.register(
        prefix,
        ProcessResult(exit_code=exit_code, stdout="", stderr="", duration_ms=0),
    )
