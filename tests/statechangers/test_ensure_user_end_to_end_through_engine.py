from __future__ import annotations

from pathlib import Path
from typing import Mapping, Sequence, override

from statectl import StateCtl
from statectl._engine_result import NodeOutcome
from statectl._interfaces.process import ProcessResult
from statectl._modules import DefaultLogger, InMemoryVariableRegistry, RealHashing
from statectl._statechangers import (
    EnsureUserParameters,
    EnsureUserStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_archive import ScriptedArchive
from tests.fakes.scripted_clock import ScriptedClock
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_http_client import ScriptedHttpClient
from tests.fakes.scripted_process_runner import ScriptedProcessRunner
from tests.statechangers._ensure_user_helpers import (
    linux_runner_with_executables,
    register_linux_uid_owner,
    register_linux_user,
    register_linux_user_missing,
)


class _StatefulLinux(ScriptedProcessRunner):
    """Tracks user existence; `useradd <name>` flips later getent probes
    to return the user."""

    def __init__(self) -> None:
        super().__init__()
        for name in ("useradd", "usermod", "userdel", "getent"):
            self.register_executable(name)
        self._exists = False
        register_linux_user_missing(self, "alice")
        register_linux_uid_owner(self, 1500, None)

    def _set_exists(self) -> None:
        self._exists = True
        self._scripts = [s for s in self._scripts if s[0][:2] != ("getent", "passwd")]
        register_linux_user(self, "alice", uid=1500, gid=1500, home="/home/alice")

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
        argv_tuple = tuple(argv)
        if argv_tuple[:1] == ("useradd",):
            self._set_exists()
            super().run(argv, cwd=cwd, env=env, stdin=stdin, timeout=timeout)
            return ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=0)
        return super().run(argv, cwd=cwd, env=env, stdin=stdin, timeout=timeout)


def _engine(pr: ScriptedProcessRunner, fs: InMemoryFileSystem) -> StateCtl:
    return StateCtl(
        logger=DefaultLogger("test"),
        file_system=fs,
        process_runner=pr,
        http_client=ScriptedHttpClient(),
        env=ScriptedEnv.linux(),
        archive=ScriptedArchive(),
        hashing=RealHashing(),
        clock=ScriptedClock(),
        variable_registry=InMemoryVariableRegistry(),
    )


def test_engine_creates_user_and_succeeds() -> None:
    pr = _StatefulLinux()
    fs = InMemoryFileSystem()
    changer = EnsureUserStateChanger(
        EnsureUserParameters(username="alice", uid=1500),
        process_runner=pr,
        file_system=fs,
        env=ScriptedEnv.linux(),
    )
    engine = _engine(pr, fs)
    engine.add(changer)
    result = engine.start(max_workers=1)

    assert result.ok, result.reports[0].result
    assert result.reports[0].outcome is NodeOutcome.SUCCESS


def test_engine_skips_when_user_already_in_desired_state() -> None:
    pr = linux_runner_with_executables()
    register_linux_user(pr, "alice", uid=1500)
    fs = InMemoryFileSystem()
    changer = EnsureUserStateChanger(
        EnsureUserParameters(username="alice"),
        process_runner=pr,
        file_system=fs,
        env=ScriptedEnv.linux(),
    )
    engine = _engine(pr, fs)
    engine.add(changer)
    result = engine.start(max_workers=1)

    assert result.ok
    assert result.reports[0].outcome is NodeOutcome.SKIPPED_ALREADY_APPLIED


def test_engine_halts_on_invalid_uid_conflict() -> None:
    pr = linux_runner_with_executables()
    register_linux_user_missing(pr, "alice")
    register_linux_uid_owner(pr, 1500, "bob")
    fs = InMemoryFileSystem()
    changer = EnsureUserStateChanger(
        EnsureUserParameters(username="alice", uid=1500),
        process_runner=pr,
        file_system=fs,
        env=ScriptedEnv.linux(),
    )
    engine = _engine(pr, fs)
    engine.add(changer)
    result = engine.start(max_workers=1)

    assert not result.ok
    assert result.reports[0].outcome is NodeOutcome.FAILED_INVALID
