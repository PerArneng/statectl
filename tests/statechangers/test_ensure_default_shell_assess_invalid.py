from __future__ import annotations

from pathlib import Path
from typing import override

from statectl._interfaces.process import ProcessResult
from statectl._state_changer import ExistingState
from statectl._statechangers import (
    EnsureDefaultShellParameters,
    EnsureDefaultShellStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


_GETENT_LINE = "alice:x:1000:1000::/home/alice:/bin/bash\n"


def _linux_rig(
    *,
    shell: Path = Path("/bin/zsh"),
    user_exists: bool = True,
    current_shell: Path | None = Path("/bin/bash"),
    shell_present: bool = True,
    shell_mode: int = 0o755,
    etc_shells_contents: str | None = "/bin/bash\n/bin/zsh\n",
    chsh_on_path: bool = True,
) -> EnsureDefaultShellStateChanger:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/bin"))
    fs.add_dir(Path("/etc"))
    if shell_present:
        fs.add_file(shell, mode=shell_mode)
    if etc_shells_contents is not None:
        fs.add_file(Path("/etc/shells"), content=etc_shells_contents)
    pr = ScriptedProcessRunner()
    pr.register_executable("getent")
    if chsh_on_path:
        pr.register_executable("chsh")
    if user_exists and current_shell is not None:
        pr.register(
            ("getent", "passwd", "alice"),
            ProcessResult(
                exit_code=0,
                stdout=f"alice:x:1000:1000::/home/alice:{current_shell}\n",
                stderr="",
                duration_ms=0,
            ),
        )
    else:
        pr.register(
            ("getent", "passwd", "alice"),
            ProcessResult(exit_code=2, stdout="", stderr="", duration_ms=0),
        )
    return EnsureDefaultShellStateChanger(
        EnsureDefaultShellParameters(user="alice", shell=shell),
        process_runner=pr,
        file_system=fs,
        env=ScriptedEnv.linux(),
    )


def test_invalid_when_user_name_has_metacharacters() -> None:
    pr = ScriptedProcessRunner()
    pr.register_executable("getent")
    pr.register_executable("chsh")
    fs = InMemoryFileSystem()
    fs.add_file(Path("/bin/zsh"), mode=0o755)
    fs.add_file(Path("/etc/shells"), content="/bin/zsh\n")
    changer = EnsureDefaultShellStateChanger(
        EnsureDefaultShellParameters(
            user="alice; rm -rf /", shell=Path("/bin/zsh")
        ),
        process_runner=pr,
        file_system=fs,
        env=ScriptedEnv.linux(),
    )

    assess = changer.assess_state()

    assert assess.state is ExistingState.INVALID
    assert any("invalid user name" in i for i in assess.issues)


def test_invalid_when_shell_path_has_metacharacters() -> None:
    pr = ScriptedProcessRunner()
    pr.register_executable("getent")
    fs = InMemoryFileSystem()
    changer = EnsureDefaultShellStateChanger(
        EnsureDefaultShellParameters(
            user="alice", shell=Path("/bin/zsh; rm -rf /")
        ),
        process_runner=pr,
        file_system=fs,
        env=ScriptedEnv.linux(),
    )

    assess = changer.assess_state()

    assert assess.state is ExistingState.INVALID
    assert any("invalid characters" in i for i in assess.issues)


def test_invalid_when_user_does_not_exist() -> None:
    changer = _linux_rig(user_exists=False)

    assess = changer.assess_state()

    assert assess.state is ExistingState.INVALID
    assert any("user does not exist" in i for i in assess.issues)


def test_invalid_when_shell_does_not_exist() -> None:
    changer = _linux_rig(shell_present=False)

    assess = changer.assess_state()

    assert assess.state is ExistingState.INVALID
    assert any("shell does not exist" in i for i in assess.issues)


def test_invalid_when_shell_is_not_executable() -> None:
    changer = _linux_rig(shell_mode=0o644)

    assess = changer.assess_state()

    assert assess.state is ExistingState.INVALID
    assert any("not executable" in i for i in assess.issues)


def test_invalid_when_shell_not_in_etc_shells_and_register_false() -> None:
    changer = _linux_rig(etc_shells_contents="/bin/bash\n")

    assess = changer.assess_state()

    assert assess.state is ExistingState.INVALID
    assert any("/etc/shells" in i for i in assess.issues)


def test_invalid_when_chsh_not_on_path() -> None:
    changer = _linux_rig(chsh_on_path=False)

    assess = changer.assess_state()

    assert assess.state is ExistingState.INVALID
    assert any("chsh not on PATH" in i for i in assess.issues)


class _RunnerWithMissingTool(ScriptedProcessRunner):
    """ScriptedProcessRunner where one binary is runnable but missing from
    `which` — used to isolate the precondition that the changer requires
    the right platform tool on PATH (chsh on linux, dscl on darwin)."""

    def __init__(self, hidden_from_which: str) -> None:
        super().__init__()
        self._hidden = hidden_from_which

    @override
    def which(self, name: str) -> Path | None:
        if name == self._hidden:
            return None
        return super().which(name)


def test_invalid_when_dscl_not_on_path_on_darwin() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/bin"))
    fs.add_dir(Path("/etc"))
    fs.add_file(Path("/bin/zsh"), mode=0o755)
    fs.add_file(Path("/etc/shells"), content="/bin/bash\n/bin/zsh\n")
    pr = _RunnerWithMissingTool("dscl")
    pr.register_executable("dscl")
    pr.register(
        ("dscl", ".", "-read", "/Users/alice", "UserShell"),
        ProcessResult(
            exit_code=0,
            stdout="UserShell: /bin/bash\n",
            stderr="",
            duration_ms=0,
        ),
    )
    changer = EnsureDefaultShellStateChanger(
        EnsureDefaultShellParameters(user="alice", shell=Path("/bin/zsh")),
        process_runner=pr,
        file_system=fs,
        env=ScriptedEnv.darwin(),
    )

    assess = changer.assess_state()

    assert assess.state is ExistingState.INVALID
    assert any("dscl not on PATH" in i for i in assess.issues)


def test_chsh_not_required_on_darwin() -> None:
    # Regression guard: on darwin, chsh-on-PATH must not be a precondition.
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/bin"))
    fs.add_dir(Path("/etc"))
    fs.add_file(Path("/bin/zsh"), mode=0o755)
    fs.add_file(Path("/etc/shells"), content="/bin/bash\n/bin/zsh\n")
    pr = ScriptedProcessRunner()
    pr.register_executable("dscl")  # darwin's tool only — no chsh
    pr.register(
        ("dscl", ".", "-read", "/Users/alice", "UserShell"),
        ProcessResult(
            exit_code=0,
            stdout="UserShell: /bin/bash\n",
            stderr="",
            duration_ms=0,
        ),
    )
    changer = EnsureDefaultShellStateChanger(
        EnsureDefaultShellParameters(user="alice", shell=Path("/bin/zsh")),
        process_runner=pr,
        file_system=fs,
        env=ScriptedEnv.darwin(),
    )

    assess = changer.assess_state()

    assert assess.state is ExistingState.READY


def test_invalid_collects_multiple_issues_in_one_pass() -> None:
    changer = _linux_rig(
        shell_present=False,
        etc_shells_contents="/bin/bash\n",
        chsh_on_path=False,
    )

    assess = changer.assess_state()

    assert assess.state is ExistingState.INVALID
    joined = "\n".join(assess.issues)
    assert "shell does not exist" in joined
    assert "/etc/shells" in joined
    assert "chsh not on PATH" in joined
