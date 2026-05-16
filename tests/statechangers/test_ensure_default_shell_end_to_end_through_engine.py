from __future__ import annotations

from pathlib import Path
from typing import Mapping, Sequence, override

from statectl import StateCtl
from statectl._engine_result import NodeOutcome
from statectl._interfaces.process import ProcessResult
from statectl._modules import DefaultLogger, InMemoryVariableRegistry
from statectl._statechangers import (
    EnsureDefaultShellParameters,
    EnsureDefaultShellStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_http_client import ScriptedHttpClient
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


class _StatefulShellRunner(ScriptedProcessRunner):
    """Tracks the user's current login shell and updates it on `chsh`, so
    post-assess after a successful transition sees ALREADY_APPLIED."""

    def __init__(self, initial_shell: Path) -> None:
        super().__init__()
        self._shell = initial_shell
        self.register_executable("getent")
        self.register_executable("chsh")

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
        if argv_tuple[:2] == ("getent", "passwd"):
            super().run(argv, cwd=cwd, env=env, stdin=stdin, timeout=timeout)
            return ProcessResult(
                exit_code=0,
                stdout=f"alice:x:1000:1000::/home/alice:{self._shell}\n",
                stderr="",
                duration_ms=0,
            )
        if argv_tuple[:2] == ("chsh", "-s"):
            self._shell = Path(argv_tuple[2])
            super().run(argv, cwd=cwd, env=env, stdin=stdin, timeout=timeout)
            return ProcessResult(
                exit_code=0, stdout="ok", stderr="", duration_ms=0
            )
        return super().run(argv, cwd=cwd, env=env, stdin=stdin, timeout=timeout)


def _engine(pr: ScriptedProcessRunner, fs: InMemoryFileSystem) -> StateCtl:
    return StateCtl(
        logger=DefaultLogger("test"),
        file_system=fs,
        process_runner=pr,
        http_client=ScriptedHttpClient(),
        env=ScriptedEnv.linux(),
        variable_registry=InMemoryVariableRegistry(),
    )


def _fs_ready() -> InMemoryFileSystem:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/bin"))
    fs.add_dir(Path("/etc"))
    fs.add_file(Path("/bin/bash"), mode=0o755)
    fs.add_file(Path("/bin/zsh"), mode=0o755)
    fs.add_file(Path("/etc/shells"), content="/bin/bash\n/bin/zsh\n")
    return fs


def test_engine_changes_shell_and_post_assess_succeeds() -> None:
    pr = _StatefulShellRunner(Path("/bin/bash"))
    fs = _fs_ready()
    changer = EnsureDefaultShellStateChanger(
        EnsureDefaultShellParameters(user="alice", shell=Path("/bin/zsh")),
        process_runner=pr,
        file_system=fs,
        env=ScriptedEnv.linux(),
    )

    engine = _engine(pr, fs)
    engine.add(changer)
    result = engine.start(max_workers=1)

    assert result.ok, result.reports[0].result
    assert result.reports[0].outcome is NodeOutcome.SUCCESS


def test_engine_skips_when_shell_already_set() -> None:
    pr = _StatefulShellRunner(Path("/bin/zsh"))
    fs = _fs_ready()
    changer = EnsureDefaultShellStateChanger(
        EnsureDefaultShellParameters(user="alice", shell=Path("/bin/zsh")),
        process_runner=pr,
        file_system=fs,
        env=ScriptedEnv.linux(),
    )

    engine = _engine(pr, fs)
    engine.add(changer)
    result = engine.start(max_workers=1)

    assert result.ok
    assert result.reports[0].outcome is NodeOutcome.SKIPPED_ALREADY_APPLIED


def test_engine_halts_on_invalid_user() -> None:
    pr = ScriptedProcessRunner()
    pr.register_executable("getent")
    pr.register_executable("chsh")
    pr.register(
        ("getent", "passwd", "ghost"),
        ProcessResult(exit_code=2, stdout="", stderr="", duration_ms=0),
    )
    fs = _fs_ready()
    changer = EnsureDefaultShellStateChanger(
        EnsureDefaultShellParameters(user="ghost", shell=Path("/bin/zsh")),
        process_runner=pr,
        file_system=fs,
        env=ScriptedEnv.linux(),
    )

    engine = _engine(pr, fs)
    engine.add(changer)
    result = engine.start(max_workers=1)

    assert not result.ok
    assert result.reports[0].outcome is NodeOutcome.FAILED_INVALID
