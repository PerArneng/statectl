from __future__ import annotations

from pathlib import Path

from statectl._interfaces.process import ProcessResult
from statectl._state_changer import ExistingState, ResultStatus
from statectl._statechangers import (
    EnsureDefaultShellParameters,
    EnsureDefaultShellRollbackStateChanger,
    EnsureDefaultShellStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


def _forward_executed_linux() -> tuple[
    EnsureDefaultShellStateChanger,
    ScriptedProcessRunner,
    InMemoryFileSystem,
]:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/bin"))
    fs.add_dir(Path("/etc"))
    fs.add_file(Path("/bin/zsh"), mode=0o755)
    fs.add_file(Path("/bin/bash"), mode=0o755)
    fs.add_file(Path("/etc/shells"), content="/bin/bash\n/bin/zsh\n")
    pr = ScriptedProcessRunner()
    pr.register_executable("getent")
    pr.register_executable("chsh")
    pr.register(
        ("getent", "passwd", "alice"),
        ProcessResult(
            exit_code=0,
            stdout="alice:x:1000:1000::/home/alice:/bin/bash\n",
            stderr="",
            duration_ms=0,
        ),
    )
    pr.register(
        ("chsh", "-s", "/bin/zsh", "alice"),
        ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=0),
    )
    forward = EnsureDefaultShellStateChanger(
        EnsureDefaultShellParameters(user="alice", shell=Path("/bin/zsh")),
        process_runner=pr,
        file_system=fs,
        env=ScriptedEnv.linux(),
    )
    forward.transition()
    return forward, pr, fs


def test_rollback_invalid_when_pre_shell_unknown() -> None:
    inverse = EnsureDefaultShellRollbackStateChanger(
        EnsureDefaultShellParameters(user="alice", shell=Path("/bin/zsh")),
        pre_shell=None,
        process_runner=ScriptedProcessRunner(),
        file_system=InMemoryFileSystem(),
        env=ScriptedEnv.linux(),
    )

    assess = inverse.assess_state()

    assert assess.state is ExistingState.INVALID
    assert any("pre_shell is unknown" in i for i in assess.issues)


def test_rollback_already_applied_when_current_shell_matches_pre_shell() -> None:
    fs = InMemoryFileSystem()
    fs.add_file(Path("/bin/bash"), mode=0o755)
    pr = ScriptedProcessRunner()
    pr.register_executable("getent")
    pr.register_executable("chsh")
    pr.register(
        ("getent", "passwd", "alice"),
        ProcessResult(
            exit_code=0,
            stdout="alice:x:1000:1000::/home/alice:/bin/bash\n",
            stderr="",
            duration_ms=0,
        ),
    )
    inverse = EnsureDefaultShellRollbackStateChanger(
        EnsureDefaultShellParameters(user="alice", shell=Path("/bin/zsh")),
        pre_shell=Path("/bin/bash"),
        process_runner=pr,
        file_system=fs,
        env=ScriptedEnv.linux(),
    )

    assess = inverse.assess_state()

    assert assess.state is ExistingState.ALREADY_APPLIED


def test_rollback_ready_when_current_shell_differs_from_pre_shell() -> None:
    fs = InMemoryFileSystem()
    fs.add_file(Path("/bin/bash"), mode=0o755)
    pr = ScriptedProcessRunner()
    pr.register_executable("getent")
    pr.register_executable("chsh")
    pr.register(
        ("getent", "passwd", "alice"),
        ProcessResult(
            exit_code=0,
            stdout="alice:x:1000:1000::/home/alice:/bin/zsh\n",
            stderr="",
            duration_ms=0,
        ),
    )
    inverse = EnsureDefaultShellRollbackStateChanger(
        EnsureDefaultShellParameters(user="alice", shell=Path("/bin/zsh")),
        pre_shell=Path("/bin/bash"),
        process_runner=pr,
        file_system=fs,
        env=ScriptedEnv.linux(),
    )

    assess = inverse.assess_state()

    assert assess.state is ExistingState.READY


def test_rollback_transition_invokes_chsh_with_pre_shell() -> None:
    forward, pr, _ = _forward_executed_linux()
    inverse = forward.rollback()
    pr.register(
        ("getent", "passwd", "alice"),
        ProcessResult(
            exit_code=0,
            stdout="alice:x:1000:1000::/home/alice:/bin/zsh\n",
            stderr="",
            duration_ms=0,
        ),
    )
    pr.register(
        ("chsh", "-s", "/bin/bash", "alice"),
        ProcessResult(exit_code=0, stdout="ok", stderr="", duration_ms=0),
    )

    result = inverse.transition()

    assert result.status is ResultStatus.SUCCESS
    assert result.details["pre_shell"] == "/bin/bash"
    assert ("chsh", "-s", "/bin/bash", "alice") in [c.argv for c in pr.calls]


def test_forward_rollback_propagates_pre_shell_after_successful_transition() -> None:
    forward, _, _ = _forward_executed_linux()
    inverse = forward.rollback()

    assert isinstance(inverse, EnsureDefaultShellRollbackStateChanger)
    assert inverse.pre_shell == Path("/bin/bash")
