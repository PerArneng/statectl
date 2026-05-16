from __future__ import annotations

from pathlib import Path

import pytest

from statectl._interfaces.process import ProcessResult
from statectl._state_changer import ExistingState
from statectl._statechangers import (
    EnsureDefaultShellParameters,
    EnsureDefaultShellStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


def _linux_runner(current_shell: Path) -> ScriptedProcessRunner:
    pr = ScriptedProcessRunner()
    pr.register_executable("getent")
    pr.register_executable("chsh")
    pr.register(
        ("getent", "passwd", "alice"),
        ProcessResult(
            exit_code=0,
            stdout=f"alice:x:1000:1000::/home/alice:{current_shell}\n",
            stderr="",
            duration_ms=0,
        ),
    )
    return pr


def _darwin_runner(current_shell: Path) -> ScriptedProcessRunner:
    pr = ScriptedProcessRunner()
    pr.register_executable("dscl")
    pr.register_executable("chsh")
    pr.register(
        ("dscl", ".", "-read", "/Users/alice", "UserShell"),
        ProcessResult(
            exit_code=0,
            stdout=f"UserShell: {current_shell}\n",
            stderr="",
            duration_ms=0,
        ),
    )
    return pr


def _fs_with_shells(shell: Path, etc_shells: str = "/bin/bash\n/bin/zsh\n") -> InMemoryFileSystem:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/bin"))
    fs.add_dir(Path("/etc"))
    fs.add_file(shell, mode=0o755)
    fs.add_file(Path("/bin/bash"), mode=0o755)
    fs.add_file(Path("/etc/shells"), content=etc_shells)
    return fs


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_already_applied_when_current_shell_matches(platform: str) -> None:
    shell = Path("/bin/zsh")
    pr = _linux_runner(shell) if platform == "linux" else _darwin_runner(shell)
    fs = _fs_with_shells(shell)
    env = ScriptedEnv.linux() if platform == "linux" else ScriptedEnv.darwin()
    changer = EnsureDefaultShellStateChanger(
        EnsureDefaultShellParameters(user="alice", shell=shell),
        process_runner=pr,
        file_system=fs,
        env=env,
    )

    assess = changer.assess_state()

    assert assess.state is ExistingState.ALREADY_APPLIED


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_ready_when_current_shell_differs(platform: str) -> None:
    shell = Path("/bin/zsh")
    pr = (
        _linux_runner(Path("/bin/bash"))
        if platform == "linux"
        else _darwin_runner(Path("/bin/bash"))
    )
    fs = _fs_with_shells(shell)
    env = ScriptedEnv.linux() if platform == "linux" else ScriptedEnv.darwin()
    changer = EnsureDefaultShellStateChanger(
        EnsureDefaultShellParameters(user="alice", shell=shell),
        process_runner=pr,
        file_system=fs,
        env=env,
    )

    assess = changer.assess_state()

    assert assess.state is ExistingState.READY


def test_ready_when_shell_not_in_etc_shells_but_register_in_etc_shells_is_true() -> None:
    shell = Path("/opt/custom/bin/fish")
    pr = _linux_runner(Path("/bin/bash"))
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/bin"))
    fs.add_dir(Path("/etc"))
    fs.add_dir(Path("/opt"))
    fs.add_dir(Path("/opt/custom"))
    fs.add_dir(Path("/opt/custom/bin"))
    fs.add_file(shell, mode=0o755)
    fs.add_file(Path("/etc/shells"), content="/bin/bash\n")
    changer = EnsureDefaultShellStateChanger(
        EnsureDefaultShellParameters(
            user="alice", shell=shell, register_in_etc_shells=True
        ),
        process_runner=pr,
        file_system=fs,
        env=ScriptedEnv.linux(),
    )

    assess = changer.assess_state()

    assert assess.state is ExistingState.READY


def test_already_applied_short_circuits_shell_file_check() -> None:
    # Even if the shell file is missing, if the user already has it as their
    # login shell, we report ALREADY_APPLIED — no transition will run, so
    # shell-file preconditions are irrelevant.
    shell = Path("/bin/zsh")
    pr = _linux_runner(shell)
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/etc"))
    fs.add_file(Path("/etc/shells"), content="/bin/zsh\n")
    changer = EnsureDefaultShellStateChanger(
        EnsureDefaultShellParameters(user="alice", shell=shell),
        process_runner=pr,
        file_system=fs,
        env=ScriptedEnv.linux(),
    )

    assess = changer.assess_state()

    assert assess.state is ExistingState.ALREADY_APPLIED
