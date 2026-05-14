from __future__ import annotations

from pathlib import Path

from statectl._interfaces.process import ProcessResult
from statectl._state_changer import ResultStatus
from statectl._statechangers import (
    RunCommandParameters,
    RunCommandStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


def _rig() -> tuple[ScriptedProcessRunner, InMemoryFileSystem]:
    pr = ScriptedProcessRunner()
    pr.register_executable("echo")
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    return pr, fs


def test_success_with_default_expected_exit_zero() -> None:
    pr, fs = _rig()
    pr.register(("echo",), ProcessResult(exit_code=0, stdout="hi\n", stderr="", duration_ms=50))
    changer = RunCommandStateChanger(
        RunCommandParameters(argv=("echo", "hi")),
        process_runner=pr,
        file_system=fs,
    )

    result = changer.transition()

    assert result.status is ResultStatus.SUCCESS
    assert result.code == "OK"
    assert result.details["exit_code"] == "0"
    assert result.details["stdout"] == "hi\n"
    assert result.details["stderr"] == ""
    assert "duration_ms" in result.details


def test_success_with_custom_expected_exit_set_accepting_nonzero() -> None:
    pr, fs = _rig()
    pr.register(("echo",), ProcessResult(exit_code=2, stdout="", stderr="", duration_ms=0))
    changer = RunCommandStateChanger(
        RunCommandParameters(argv=("echo",), expected_exit_codes=frozenset({0, 2})),
        process_runner=pr,
        file_system=fs,
    )

    result = changer.transition()

    assert result.status is ResultStatus.SUCCESS
    assert result.details["exit_code"] == "2"


def test_transition_records_a_single_call_with_correct_params() -> None:
    pr, fs = _rig()
    pr.register(("echo",), ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=0))
    changer = RunCommandStateChanger(
        RunCommandParameters(
            argv=("echo", "hi"),
            cwd=Path("/work"),
            env={"K": "V"},
            timeout=5.0,
        ),
        process_runner=pr,
        file_system=fs,
    )

    changer.transition()

    assert len(pr.calls) == 1
    call = pr.calls[0]
    assert call.argv == ("echo", "hi")
    assert call.cwd == Path("/work")
    assert call.env == {"K": "V"}
    assert call.timeout == 5.0


def test_long_stdout_is_truncated_in_details() -> None:
    pr, fs = _rig()
    huge = "x" * 100_000
    pr.register(("echo",), ProcessResult(exit_code=0, stdout=huge, stderr="", duration_ms=0))
    changer = RunCommandStateChanger(
        RunCommandParameters(argv=("echo",)),
        process_runner=pr,
        file_system=fs,
    )

    result = changer.transition()

    assert len(result.details["stdout"]) < len(huge)
    assert "truncated" in result.details["stdout"]
