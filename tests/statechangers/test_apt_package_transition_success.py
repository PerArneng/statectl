from __future__ import annotations

from pathlib import Path

from statectl._interfaces.process import ProcessResult
from statectl._state_changer import ResultStatus
from statectl._statechangers import (
    AptPackageParameters,
    AptPackageStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


def _rig() -> tuple[InMemoryFileSystem, ScriptedProcessRunner]:
    fs = InMemoryFileSystem()
    fs.add_file(Path("/etc/debian_version"), content="12.0\n")
    pr = ScriptedProcessRunner()
    for binary in ("apt-get", "dpkg", "apt-mark", "apt-cache", "dpkg-query"):
        pr.register_executable(binary)
    return fs, pr


def test_transition_runs_apt_install_and_returns_success() -> None:
    fs, pr = _rig()
    pr.register(
        ("apt-get", "-y", "install", "curl"),
        ProcessResult(exit_code=0, stdout="installed", stderr="", duration_ms=10),
    )
    changer = AptPackageStateChanger(
        AptPackageParameters(name="curl"),
        file_system=fs,
        process_runner=pr,
    )

    result = changer.transition()

    assert result.status is ResultStatus.SUCCESS
    assert result.code == "OK"
    assert result.details["install_exit_code"] == "0"
    assert result.details["install_stdout"] == "installed"
    last = pr.calls[-1]
    assert last.argv == ("apt-get", "-y", "install", "curl")
    assert last.env is not None and last.env.get("DEBIAN_FRONTEND") == "noninteractive"


def test_transition_uses_versioned_install_target() -> None:
    fs, pr = _rig()
    pr.register(
        ("apt-get", "-y", "install", "curl=7.88.1"),
        ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=0),
    )
    changer = AptPackageStateChanger(
        AptPackageParameters(name="curl", version="7.88.1"),
        file_system=fs,
        process_runner=pr,
    )

    result = changer.transition()

    assert result.status is ResultStatus.SUCCESS
    assert pr.calls[-1].argv == ("apt-get", "-y", "install", "curl=7.88.1")


def test_transition_holds_when_requested() -> None:
    fs, pr = _rig()
    pr.register(
        ("apt-get", "-y", "install", "curl"),
        ProcessResult(exit_code=0, stdout="ok", stderr="", duration_ms=0),
    )
    pr.register(
        ("apt-mark", "hold", "curl"),
        ProcessResult(exit_code=0, stdout="curl set on hold.", stderr="", duration_ms=0),
    )
    changer = AptPackageStateChanger(
        AptPackageParameters(name="curl", hold=True),
        file_system=fs,
        process_runner=pr,
    )

    result = changer.transition()

    assert result.status is ResultStatus.SUCCESS
    assert result.details["hold_exit_code"] == "0"
    argvs = [c.argv for c in pr.calls]
    assert ("apt-get", "-y", "install", "curl") in argvs
    assert ("apt-mark", "hold", "curl") in argvs


def test_transition_does_not_hold_when_not_requested() -> None:
    fs, pr = _rig()
    pr.register(
        ("apt-get", "-y", "install", "curl"),
        ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=0),
    )
    changer = AptPackageStateChanger(
        AptPackageParameters(name="curl"),
        file_system=fs,
        process_runner=pr,
    )

    result = changer.transition()

    assert result.status is ResultStatus.SUCCESS
    assert "hold_exit_code" not in result.details
    assert not any(c.argv[:2] == ("apt-mark", "hold") for c in pr.calls)
