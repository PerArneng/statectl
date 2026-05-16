from __future__ import annotations

from pathlib import Path

from statectl._interfaces.process import (
    ProcessDecodeError,
    ProcessLaunchError,
    ProcessNotFound,
    ProcessResult,
    ProcessTimeout,
)
from statectl._state_changer import ExistingState
from statectl._statechangers import (
    AptPackageParameters,
    AptPackageStateChanger,
)
from tests.fakes.failing_process_runner import FailingProcessRunner
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


def _inner() -> ScriptedProcessRunner:
    pr = ScriptedProcessRunner()
    for binary in ("apt-get", "dpkg", "apt-mark", "apt-cache", "dpkg-query"):
        pr.register_executable(binary)
    pr.register(
        ("dpkg", "-s", "curl"),
        ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=0),
    )
    return pr


def _fs() -> InMemoryFileSystem:
    fs = InMemoryFileSystem()
    fs.add_file(Path("/etc/debian_version"), content="12.0\n")
    return fs


def _changer(pr: FailingProcessRunner) -> AptPackageStateChanger:
    return AptPackageStateChanger(
        AptPackageParameters(name="curl"),
        file_system=_fs(),
        process_runner=pr,
    )


def test_assess_does_not_raise_on_process_not_found() -> None:
    pr = FailingProcessRunner(_inner())
    pr.fail("run", ProcessNotFound("missing", argv=("dpkg",)))

    assess = _changer(pr).assess_state()

    assert assess.state is ExistingState.INVALID
    assert any("not found" in i for i in assess.issues)


def test_assess_does_not_raise_on_process_timeout() -> None:
    pr = FailingProcessRunner(_inner())
    pr.fail("run", ProcessTimeout("timed out", argv=("dpkg",)))

    assess = _changer(pr).assess_state()

    assert assess.state is ExistingState.INVALID
    assert any("timed out" in i for i in assess.issues)


def test_assess_does_not_raise_on_process_decode_error() -> None:
    pr = FailingProcessRunner(_inner())
    pr.fail("run", ProcessDecodeError("decode", argv=("dpkg",)))

    assess = _changer(pr).assess_state()

    assert assess.state is ExistingState.INVALID
    assert any("decode" in i for i in assess.issues)


def test_assess_does_not_raise_on_process_launch_error() -> None:
    pr = FailingProcessRunner(_inner())
    pr.fail("run", ProcessLaunchError("launch", argv=("dpkg",)))

    assess = _changer(pr).assess_state()

    assert assess.state is ExistingState.INVALID
    assert any("launch" in i for i in assess.issues)
