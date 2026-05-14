from __future__ import annotations

from pathlib import Path

import pytest

from statectl.interfaces.process import ProcessResult
from statectl import ResultStatus
from statectl.statechangers import (
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


@pytest.mark.parametrize(
    "scripted_exit, expected_set, should_fail",
    [
        (0, frozenset({0}), False),
        (1, frozenset({0}), True),
        (0, frozenset({1, 2}), True),  # success exit is NOT implicitly allowed
        (2, frozenset({0, 2}), False),
        (137, frozenset({0}), True),
    ],
)
def test_exit_code_policy(
    scripted_exit: int, expected_set: frozenset[int], should_fail: bool
) -> None:
    pr, fs = _rig()
    pr.register(
        ("echo",),
        ProcessResult(exit_code=scripted_exit, stdout="", stderr="boom", duration_ms=0),
    )
    changer = RunCommandStateChanger(
        RunCommandParameters(argv=("echo",), expected_exit_codes=expected_set),
        process_runner=pr,
        file_system=fs,
    )

    result = changer.transition()

    if should_fail:
        assert result.status is ResultStatus.FAILURE
        assert result.code == "UNEXPECTED_EXIT"
        assert str(scripted_exit) in (result.message or "")
        assert result.details["stderr"] == "boom"
        assert result.details["exit_code"] == str(scripted_exit)
    else:
        assert result.status is ResultStatus.SUCCESS
