from __future__ import annotations

from pathlib import Path
from typing import Mapping, Sequence, override

from statectl import StateCtl
from statectl._engine_result import NodeOutcome
from statectl._interfaces.process import ProcessResult
from statectl._modules import DefaultLogger, InMemoryVariableRegistry, RealHashing
from statectl._statechangers import (
    EnsureGroupMembershipParameters,
    EnsureGroupMembershipStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_archive import ScriptedArchive
from tests.fakes.scripted_clock import ScriptedClock
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_http_client import ScriptedHttpClient
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


class _StatefulGroupRunner(ScriptedProcessRunner):
    """Tracks the user's group memberships and updates them on usermod, so a
    post-assess after a successful transition reports ALREADY_APPLIED."""

    def __init__(self, user: str, initial: list[str]) -> None:
        super().__init__()
        self._user = user
        self._groups = list(initial)
        self.register_executable("id")
        self.register_executable("getent")
        self.register_executable("usermod")
        self.register_executable("groupadd")

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
        if argv_tuple[:2] == ("id", "-nG"):
            super().run(argv, cwd=cwd, env=env, stdin=stdin, timeout=timeout)
            return ProcessResult(
                exit_code=0,
                stdout=" ".join(self._groups) + "\n",
                stderr="",
                duration_ms=0,
            )
        if argv_tuple[:2] == ("getent", "group"):
            super().run(argv, cwd=cwd, env=env, stdin=stdin, timeout=timeout)
            return ProcessResult(
                exit_code=0,
                stdout=f"{argv_tuple[2]}:x:999:\n",
                stderr="",
                duration_ms=0,
            )
        if argv_tuple[:2] == ("usermod", "-aG"):
            self._groups.append(argv_tuple[2])
            super().run(argv, cwd=cwd, env=env, stdin=stdin, timeout=timeout)
            return ProcessResult(
                exit_code=0, stdout="ok", stderr="", duration_ms=0
            )
        return super().run(argv, cwd=cwd, env=env, stdin=stdin, timeout=timeout)


def _engine(pr: ScriptedProcessRunner) -> StateCtl:
    return StateCtl(
        logger=DefaultLogger("test"),
        file_system=InMemoryFileSystem(),
        process_runner=pr,
        http_client=ScriptedHttpClient(),
        env=ScriptedEnv.linux(),
        archive=ScriptedArchive(),
        hashing=RealHashing(),
        clock=ScriptedClock(),
        variable_registry=InMemoryVariableRegistry(),
    )


def test_engine_adds_user_to_group_and_succeeds() -> None:
    pr = _StatefulGroupRunner("alice", ["alice", "users"])
    changer = EnsureGroupMembershipStateChanger(
        EnsureGroupMembershipParameters(user="alice", group="docker"),
        process_runner=pr,
        env=ScriptedEnv.linux(),
    )
    engine = _engine(pr)
    engine.add(changer)

    result = engine.start(max_workers=1)

    assert result.ok, result.reports[0].result
    assert result.reports[0].outcome is NodeOutcome.SUCCESS


def test_engine_skips_when_user_already_member() -> None:
    pr = _StatefulGroupRunner("alice", ["alice", "users", "docker"])
    changer = EnsureGroupMembershipStateChanger(
        EnsureGroupMembershipParameters(user="alice", group="docker"),
        process_runner=pr,
        env=ScriptedEnv.linux(),
    )
    engine = _engine(pr)
    engine.add(changer)

    result = engine.start(max_workers=1)

    assert result.ok
    assert result.reports[0].outcome is NodeOutcome.SKIPPED_ALREADY_APPLIED


def test_engine_halts_on_invalid_user() -> None:
    pr = ScriptedProcessRunner()
    pr.register_executable("id")
    pr.register_executable("getent")
    pr.register_executable("usermod")
    pr.register(
        ("id", "-nG", "ghost"),
        ProcessResult(exit_code=1, stdout="", stderr="", duration_ms=0),
    )
    changer = EnsureGroupMembershipStateChanger(
        EnsureGroupMembershipParameters(user="ghost", group="docker"),
        process_runner=pr,
        env=ScriptedEnv.linux(),
    )
    engine = _engine(pr)
    engine.add(changer)

    result = engine.start(max_workers=1)

    assert not result.ok
    assert result.reports[0].outcome is NodeOutcome.FAILED_INVALID
