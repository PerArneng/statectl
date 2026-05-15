from __future__ import annotations

from pathlib import Path
from typing import Mapping, Sequence, override

from statectl import StateCtl
from statectl._engine_result import NodeOutcome
from statectl._interfaces.process import (
    ProcessNotFound,
    ProcessResult,
    ProcessRunner,
)
from statectl._modules import DefaultLogger, InMemoryVariableRegistry
from statectl._statechangers import (
    EnsureLaunchdAgentParameters,
    EnsureLaunchdAgentStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_http_client import ScriptedHttpClient
from tests.fakes.scripted_process_runner import ScriptedProcessRunner
from tests.statechangers._launchd_helpers import (
    LABEL,
    PLIST_CONTENT,
    USER_PLIST_PATH,
    make_rig,
    script_exit,
    script_loaded,
)


def _engine(
    fs: InMemoryFileSystem, pr: ScriptedProcessRunner, env: ScriptedEnv
) -> StateCtl:
    return StateCtl(
        logger=DefaultLogger("test"),
        file_system=fs,
        process_runner=pr,
        http_client=ScriptedHttpClient(),
        env=env,
        variable_registry=InMemoryVariableRegistry(),
    )


def test_engine_skips_when_already_applied() -> None:
    rig = make_rig()
    rig.fs.add_file(USER_PLIST_PATH, content=PLIST_CONTENT)
    script_loaded(rig.pr, loaded=True)

    engine = _engine(rig.fs, rig.pr, rig.env)
    engine.add(rig.changer())
    result = engine.start(max_workers=1)

    assert result.ok
    assert result.reports[0].outcome is NodeOutcome.SKIPPED_ALREADY_APPLIED


def test_engine_halts_on_invalid_when_not_darwin() -> None:
    rig = make_rig(platform="linux")
    engine = _engine(rig.fs, rig.pr, rig.env)
    engine.add(rig.changer())
    result = engine.start(max_workers=1)

    assert not result.ok
    assert result.reports[0].outcome is NodeOutcome.FAILED_INVALID


def test_engine_runs_transition_when_ready() -> None:
    """Use a stateful runner so the post-transition assess observes the agent
    as loaded."""

    class _StatefulLaunchctl(ProcessRunner):
        def __init__(self, fs: InMemoryFileSystem) -> None:
            self.loaded: bool = False
            self.calls: list[tuple[str, ...]] = []
            self._fs = fs

        @override
        def which(self, name: str) -> Path | None:
            return Path("/bin/launchctl") if name == "launchctl" else None

        @override
        def run(
            self,
            argv: Sequence[str],
            *,
            cwd: Path | None = None,
            env: Mapping[str, str] | None = None,
            stdin: str | None = None,
            timeout: float | None = None,
        ) -> ProcessResult:
            t = tuple(argv)
            self.calls.append(t)
            if not t or t[0] != "launchctl":
                raise ProcessNotFound("missing", argv=t)
            if t[1] == "load":
                self.loaded = True
                return ProcessResult(0, "", "", 0)
            if t[1] == "list":
                return ProcessResult(0 if self.loaded else 1, "", "", 0)
            if t[1] == "print":
                return ProcessResult(0 if self.loaded else 1, "", "", 0)
            return ProcessResult(0, "", "", 0)

    fs = InMemoryFileSystem()
    fs.add_dir(Path("/Users/test"))
    fs.add_dir(Path("/Users/test/Library"))
    fs.add_dir(Path("/Users/test/Library/LaunchAgents"))
    pr = _StatefulLaunchctl(fs)
    env = ScriptedEnv.darwin(home=Path("/Users/test"))

    engine = StateCtl(
        logger=DefaultLogger("test"),
        file_system=fs,
        process_runner=pr,
        http_client=ScriptedHttpClient(),
        env=env,
        variable_registry=InMemoryVariableRegistry(),
    )
    engine.add(
        EnsureLaunchdAgentStateChanger(
            EnsureLaunchdAgentParameters(
                label=LABEL,
                plist_content=PLIST_CONTENT,
                scope="user",
            ),
            file_system=fs,
            process_runner=pr,
            env=env,
        )
    )
    result = engine.start(max_workers=1)

    assert result.ok, result.reports[0].result
    assert result.reports[0].outcome is NodeOutcome.SUCCESS
    assert fs.exists(USER_PLIST_PATH)
    assert any(c[:2] == ("launchctl", "load") for c in pr.calls)


def test_engine_halts_on_load_failure() -> None:
    rig = make_rig()
    rig.pr.register(
        ("launchctl", "load"),
        ProcessResult(exit_code=2, stdout="", stderr="bad", duration_ms=1),
    )
    script_exit(rig.pr, ("launchctl", "list"), 1)  # not loaded
    engine = _engine(rig.fs, rig.pr, rig.env)
    engine.add(rig.changer())
    result = engine.start(max_workers=1)

    assert not result.ok
    assert result.reports[0].outcome is NodeOutcome.FAILED_TRANSITION
    rr = result.reports[0].result
    assert rr is not None
    assert rr.code == "LAUNCHCTL_LOAD_FAILED"
