from __future__ import annotations

from pathlib import Path

import pytest

from statectl._interfaces.process import (
    ProcessDecodeError,
    ProcessError,
    ProcessLaunchError,
    ProcessNotFound,
    ProcessTimeout,
)
from statectl._state_changer import ResultStatus
from statectl._statechangers import (
    RunCommandParameters,
    RunCommandStateChanger,
)
from tests.fakes.failing_process_runner import FailingProcessRunner
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


ARGV = ("echo", "hi")


def _failing_rig() -> tuple[FailingProcessRunner, InMemoryFileSystem]:
    inner = ScriptedProcessRunner()
    inner.register_executable("echo")
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    return FailingProcessRunner(inner), fs


def _changer(pr: FailingProcessRunner, fs: InMemoryFileSystem) -> RunCommandStateChanger:
    return RunCommandStateChanger(
        RunCommandParameters(argv=ARGV),
        process_runner=pr,
        file_system=fs,
    )


ERROR_MATRIX: list[tuple[ProcessError, str]] = [
    (ProcessNotFound("missing", argv=ARGV), "PROCESS_NOT_FOUND"),
    (ProcessTimeout("ran too long", argv=ARGV), "PROCESS_TIMEOUT"),
    (ProcessLaunchError("os boom", argv=ARGV), "PROCESS_LAUNCH_ERROR"),
    (ProcessDecodeError("bad bytes", argv=ARGV), "PROCESS_DECODE_ERROR"),
]


@pytest.mark.parametrize(
    "error, code",
    ERROR_MATRIX,
    ids=[type(e).__name__ for e, _ in ERROR_MATRIX],
)
def test_each_process_error_subclass_maps_to_specific_failure_code(
    error: ProcessError, code: str
) -> None:
    pr, fs = _failing_rig()
    pr.fail("run", error)
    changer = _changer(pr, fs)

    result = changer.transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == code
    assert error.message in (result.message or "")


def test_non_process_error_exception_is_not_caught() -> None:
    """transition() catches only narrow ProcessError subclasses — a stray
    RuntimeError from a misbehaving runner must propagate so bugs are not
    masked as transition failures.
    """
    pr, fs = _failing_rig()
    pr.fail("run", RuntimeError("unexpected"))
    changer = _changer(pr, fs)

    with pytest.raises(RuntimeError, match="unexpected"):
        changer.transition()
