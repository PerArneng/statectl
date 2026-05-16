from __future__ import annotations

from pathlib import Path

from statectl._interfaces.process import ProcessResult
from statectl._state_changer import ResultStatus
from statectl._statechangers import AptUpdateParameters, AptUpdateStateChanger
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_clock import ScriptedClock
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


_LISTS = Path("/var/lib/apt/lists")


def _rig() -> tuple[ScriptedProcessRunner, InMemoryFileSystem]:
    pr = ScriptedProcessRunner()
    pr.register_executable("apt-get")
    fs = InMemoryFileSystem()
    fs.add_dir(_LISTS)
    return pr, fs


def test_success_emits_ok_with_details() -> None:
    pr, fs = _rig()
    pr.register(
        ("apt-get", "update"),
        ProcessResult(exit_code=0, stdout="Hit:1 ...", stderr="", duration_ms=123),
    )
    changer = AptUpdateStateChanger(
        AptUpdateParameters(),
        process_runner=pr,
        file_system=fs,
        env=ScriptedEnv.linux(),
        clock=ScriptedClock(),
    )

    result = changer.transition()

    assert result.status is ResultStatus.SUCCESS
    assert result.code == "OK"
    assert result.details["exit_code"] == "0"
    assert result.details["stdout"] == "Hit:1 ..."
    assert result.details["duration_ms"] == "123"
    assert pr.calls[0].argv == ("apt-get", "update")


def test_success_with_allow_releaseinfo_change_passes_flag() -> None:
    pr, fs = _rig()
    pr.register(
        ("apt-get", "update"),
        ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=0),
    )
    changer = AptUpdateStateChanger(
        AptUpdateParameters(allow_releaseinfo_change=True),
        process_runner=pr,
        file_system=fs,
        env=ScriptedEnv.linux(),
        clock=ScriptedClock(),
    )

    result = changer.transition()

    assert result.status is ResultStatus.SUCCESS
    assert pr.calls[0].argv == (
        "apt-get",
        "update",
        "-o",
        "Acquire::AllowReleaseInfoChange=true",
    )


def test_failure_on_nonzero_exit_returns_apt_update_failed() -> None:
    pr, fs = _rig()
    pr.register(
        ("apt-get", "update"),
        ProcessResult(exit_code=100, stdout="", stderr="W: GPG error", duration_ms=10),
    )
    changer = AptUpdateStateChanger(
        AptUpdateParameters(),
        process_runner=pr,
        file_system=fs,
        env=ScriptedEnv.linux(),
        clock=ScriptedClock(),
    )

    result = changer.transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == "APT_UPDATE_FAILED"
    assert result.details["exit_code"] == "100"
    assert result.details["stderr"] == "W: GPG error"
