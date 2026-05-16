from __future__ import annotations

from pathlib import Path

import pytest

from statectl._interfaces.process import (
    ProcessDecodeError,
    ProcessLaunchError,
    ProcessNotFound,
    ProcessResult,
    ProcessTimeout,
)
from statectl._state_changer import ResultStatus
from statectl._statechangers import (
    AptPackageParameters,
    AptPackageStateChanger,
)
from tests.fakes.failing_process_runner import FailingProcessRunner
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


def _fs() -> InMemoryFileSystem:
    fs = InMemoryFileSystem()
    fs.add_file(Path("/etc/debian_version"), content="12.0\n")
    return fs


def _inner_install_ok() -> ScriptedProcessRunner:
    pr = ScriptedProcessRunner()
    for binary in ("apt-get", "dpkg", "apt-mark", "apt-cache", "dpkg-query"):
        pr.register_executable(binary)
    pr.register(
        ("apt-get", "-y", "install", "curl"),
        ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=0),
    )
    return pr


def test_install_non_zero_exit_returns_apt_install_failed() -> None:
    fs = _fs()
    pr = ScriptedProcessRunner()
    for b in ("apt-get", "dpkg", "apt-mark", "apt-cache", "dpkg-query"):
        pr.register_executable(b)
    pr.register(
        ("apt-get", "-y", "install", "curl"),
        ProcessResult(exit_code=1, stdout="", stderr="boom", duration_ms=0),
    )
    changer = AptPackageStateChanger(
        AptPackageParameters(name="curl"), file_system=fs, process_runner=pr
    )

    result = changer.transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == "APT_INSTALL_FAILED"
    assert result.details["exit_code"] == "1"
    assert result.details["stderr"] == "boom"


def test_install_reports_package_not_found_from_stderr() -> None:
    fs = _fs()
    pr = ScriptedProcessRunner()
    for b in ("apt-get", "dpkg", "apt-mark", "apt-cache", "dpkg-query"):
        pr.register_executable(b)
    pr.register(
        ("apt-get", "-y", "install", "nope"),
        ProcessResult(
            exit_code=100,
            stdout="",
            stderr="E: Unable to locate package nope",
            duration_ms=0,
        ),
    )
    changer = AptPackageStateChanger(
        AptPackageParameters(name="nope"), file_system=fs, process_runner=pr
    )

    result = changer.transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == "PACKAGE_NOT_FOUND"


def test_hold_non_zero_exit_returns_apt_hold_failed() -> None:
    fs = _fs()
    pr = ScriptedProcessRunner()
    for b in ("apt-get", "dpkg", "apt-mark", "apt-cache", "dpkg-query"):
        pr.register_executable(b)
    pr.register(
        ("apt-get", "-y", "install", "curl"),
        ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=0),
    )
    pr.register(
        ("apt-mark", "hold", "curl"),
        ProcessResult(exit_code=2, stdout="", stderr="oops", duration_ms=0),
    )
    changer = AptPackageStateChanger(
        AptPackageParameters(name="curl", hold=True),
        file_system=fs,
        process_runner=pr,
    )

    result = changer.transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == "APT_HOLD_FAILED"
    assert result.details["install_exit_code"] == "0"
    assert result.details["exit_code"] == "2"


@pytest.mark.parametrize(
    "error, expected_code",
    [
        (ProcessNotFound("missing", argv=("apt-get",)), "APT_NOT_FOUND"),
        (ProcessTimeout("timed out", argv=("apt-get",)), "PROCESS_TIMEOUT"),
        (ProcessDecodeError("decode", argv=("apt-get",)), "PROCESS_DECODE_ERROR"),
        (ProcessLaunchError("launch", argv=("apt-get",)), "PROCESS_LAUNCH_ERROR"),
    ],
)
def test_install_typed_errors_map_to_codes(
    error: BaseException, expected_code: str
) -> None:
    fs = _fs()
    pr = FailingProcessRunner(_inner_install_ok())
    pr.fail("run", error)
    changer = AptPackageStateChanger(
        AptPackageParameters(name="curl"), file_system=fs, process_runner=pr
    )

    result = changer.transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == expected_code


def test_unexpected_exception_propagates() -> None:
    fs = _fs()
    pr = FailingProcessRunner(_inner_install_ok())
    pr.fail("run", RuntimeError("boom"))
    changer = AptPackageStateChanger(
        AptPackageParameters(name="curl"), file_system=fs, process_runner=pr
    )

    with pytest.raises(RuntimeError):
        changer.transition()
