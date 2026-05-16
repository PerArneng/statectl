from __future__ import annotations

from pathlib import Path

from statectl._interfaces.process import ProcessResult
from statectl._state_changer import ResultStatus
from statectl._statechangers import (
    EnsureDefaultShellParameters,
    EnsureDefaultShellStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


def _linux_rig(
    current_shell: Path = Path("/bin/bash"),
    etc_shells: str = "/bin/bash\n/bin/zsh\n",
    chsh_exit: int = 0,
) -> tuple[EnsureDefaultShellStateChanger, ScriptedProcessRunner, InMemoryFileSystem]:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/bin"))
    fs.add_dir(Path("/etc"))
    fs.add_file(Path("/bin/zsh"), mode=0o755)
    fs.add_file(Path("/etc/shells"), content=etc_shells)
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
    pr.register(
        ("chsh", "-s", "/bin/zsh", "alice"),
        ProcessResult(
            exit_code=chsh_exit,
            stdout="changed",
            stderr="",
            duration_ms=5,
        ),
    )
    changer = EnsureDefaultShellStateChanger(
        EnsureDefaultShellParameters(user="alice", shell=Path("/bin/zsh")),
        process_runner=pr,
        file_system=fs,
        env=ScriptedEnv.linux(),
    )
    return changer, pr, fs


def test_transition_runs_chsh_on_linux_and_captures_pre_shell() -> None:
    changer, pr, _ = _linux_rig()

    result = changer.transition()

    assert result.status is ResultStatus.SUCCESS
    assert result.code == "OK"
    assert result.details["pre_shell"] == "/bin/bash"
    assert result.details["exit_code"] == "0"
    assert ("chsh", "-s", "/bin/zsh", "alice") in [c.argv for c in pr.calls]


def test_transition_on_darwin_uses_dscl_change() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/bin"))
    fs.add_dir(Path("/etc"))
    fs.add_file(Path("/bin/zsh"), mode=0o755)
    fs.add_file(Path("/etc/shells"), content="/bin/bash\n/bin/zsh\n")
    pr = ScriptedProcessRunner()
    pr.register_executable("dscl")
    pr.register_executable("chsh")
    pr.register(
        ("dscl", ".", "-read", "/Users/alice", "UserShell"),
        ProcessResult(
            exit_code=0,
            stdout="UserShell: /bin/bash\n",
            stderr="",
            duration_ms=0,
        ),
    )
    pr.register(
        (
            "dscl",
            ".",
            "-change",
            "/Users/alice",
            "UserShell",
            "/bin/bash",
            "/bin/zsh",
        ),
        ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=0),
    )
    changer = EnsureDefaultShellStateChanger(
        EnsureDefaultShellParameters(user="alice", shell=Path("/bin/zsh")),
        process_runner=pr,
        file_system=fs,
        env=ScriptedEnv.darwin(),
    )

    result = changer.transition()

    assert result.status is ResultStatus.SUCCESS
    assert result.details["pre_shell"] == "/bin/bash"
    argvs = [c.argv for c in pr.calls]
    assert (
        "dscl",
        ".",
        "-change",
        "/Users/alice",
        "UserShell",
        "/bin/bash",
        "/bin/zsh",
    ) in argvs


def test_transition_appends_to_etc_shells_when_registration_requested() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/bin"))
    fs.add_dir(Path("/etc"))
    fs.add_dir(Path("/opt"))
    fs.add_dir(Path("/opt/custom"))
    fs.add_dir(Path("/opt/custom/bin"))
    fs.add_file(Path("/opt/custom/bin/fish"), mode=0o755)
    fs.add_file(Path("/etc/shells"), content="/bin/bash\n")
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
        ("chsh", "-s", "/opt/custom/bin/fish", "alice"),
        ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=0),
    )
    changer = EnsureDefaultShellStateChanger(
        EnsureDefaultShellParameters(
            user="alice",
            shell=Path("/opt/custom/bin/fish"),
            register_in_etc_shells=True,
        ),
        process_runner=pr,
        file_system=fs,
        env=ScriptedEnv.linux(),
    )

    result = changer.transition()

    assert result.status is ResultStatus.SUCCESS
    contents = fs.read_text_file(Path("/etc/shells"))
    assert "/opt/custom/bin/fish" in contents
    assert "/bin/bash" in contents


def test_transition_fails_with_shell_vanished_when_shell_disappears() -> None:
    changer, _, fs = _linux_rig()
    fs.delete_file(Path("/bin/zsh"))

    result = changer.transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == "SHELL_VANISHED"


def test_transition_fails_with_chsh_failed_on_nonzero_exit() -> None:
    changer, _, _ = _linux_rig(chsh_exit=1)

    result = changer.transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == "CHSH_FAILED"
    assert result.details["exit_code"] == "1"
