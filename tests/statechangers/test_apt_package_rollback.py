from __future__ import annotations

from pathlib import Path

from statectl._interfaces.process import ProcessResult
from statectl._state_changer import ExistingState, ResultStatus
from statectl._statechangers import (
    AptPackageParameters,
    AptPackageRollbackStateChanger,
    AptPackageStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


def _rig() -> tuple[InMemoryFileSystem, ScriptedProcessRunner]:
    fs = InMemoryFileSystem()
    fs.add_file(Path("/etc/debian_version"), content="12.0\n")
    pr = ScriptedProcessRunner()
    for binary in ("apt-get", "dpkg", "apt-mark"):
        pr.register_executable(binary)
    return fs, pr


def _inverse(
    fs: InMemoryFileSystem,
    pr: ScriptedProcessRunner,
    *,
    name: str = "curl",
) -> AptPackageRollbackStateChanger:
    forward = AptPackageStateChanger(
        AptPackageParameters(name=name), file_system=fs, process_runner=pr
    )
    inverse = forward.rollback()
    assert isinstance(inverse, AptPackageRollbackStateChanger)
    return inverse


def test_rollback_already_applied_when_not_installed() -> None:
    fs, pr = _rig()
    pr.register(
        ("dpkg", "-s", "curl"),
        ProcessResult(exit_code=1, stdout="", stderr="", duration_ms=0),
    )

    assess = _inverse(fs, pr).assess_state()

    assert assess.state is ExistingState.ALREADY_APPLIED


def test_rollback_ready_when_installed_and_not_held() -> None:
    fs, pr = _rig()
    pr.register(
        ("dpkg", "-s", "curl"),
        ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=0),
    )
    pr.register(
        ("apt-mark", "showhold"),
        ProcessResult(exit_code=0, stdout="wget\n", stderr="", duration_ms=0),
    )

    assess = _inverse(fs, pr).assess_state()

    assert assess.state is ExistingState.READY


def test_rollback_invalid_when_installed_and_held() -> None:
    fs, pr = _rig()
    pr.register(
        ("dpkg", "-s", "curl"),
        ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=0),
    )
    pr.register(
        ("apt-mark", "showhold"),
        ProcessResult(
            exit_code=0, stdout="curl\nwget\n", stderr="", duration_ms=0
        ),
    )

    assess = _inverse(fs, pr).assess_state()

    assert assess.state is ExistingState.INVALID
    assert any("held" in i for i in assess.issues)


def test_rollback_invalid_when_not_debian() -> None:
    fs = InMemoryFileSystem()  # no marker
    pr = ScriptedProcessRunner()
    for binary in ("apt-get", "dpkg", "apt-mark"):
        pr.register_executable(binary)

    assess = _inverse(fs, pr).assess_state()

    assert assess.state is ExistingState.INVALID
    assert any("Debian-family" in i for i in assess.issues)


def test_rollback_transition_runs_apt_remove() -> None:
    fs, pr = _rig()
    pr.register(
        ("apt-get", "-y", "remove", "curl"),
        ProcessResult(exit_code=0, stdout="removed", stderr="", duration_ms=2),
    )

    result = _inverse(fs, pr).transition()

    assert result.status is ResultStatus.SUCCESS
    last = pr.calls[-1]
    assert last.argv == ("apt-get", "-y", "remove", "curl")
    assert last.env is not None and last.env.get("DEBIAN_FRONTEND") == "noninteractive"


def test_rollback_transition_non_zero_returns_apt_remove_failed() -> None:
    fs, pr = _rig()
    pr.register(
        ("apt-get", "-y", "remove", "curl"),
        ProcessResult(exit_code=1, stdout="", stderr="nope", duration_ms=0),
    )

    result = _inverse(fs, pr).transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == "APT_REMOVE_FAILED"
    assert result.details["stderr"] == "nope"
