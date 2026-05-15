from __future__ import annotations

import pytest

from statectl._interfaces.process import (
    ProcessDecodeError,
    ProcessError,
    ProcessLaunchError,
    ProcessNotFound,
    ProcessResult,
    ProcessTimeout,
)
from statectl._state_changer import ResultStatus
from statectl._statechangers import BrewCaskParameters, BrewCaskStateChanger
from tests.fakes.failing_process_runner import FailingProcessRunner
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


def _pr() -> tuple[ScriptedProcessRunner, FailingProcessRunner]:
    inner = ScriptedProcessRunner()
    inner.register_executable("brew")
    return inner, FailingProcessRunner(inner)


def _changer(pr: FailingProcessRunner | ScriptedProcessRunner) -> BrewCaskStateChanger:
    return BrewCaskStateChanger(
        BrewCaskParameters(name="google-chrome"),
        process_runner=pr,  # type: ignore[arg-type]
    )


PROCESS_MATRIX: list[tuple[ProcessError, str]] = [
    (ProcessNotFound("brew missing"), "BREW_NOT_FOUND"),
    (ProcessTimeout("too long"), "PROCESS_TIMEOUT"),
    (ProcessDecodeError("bad bytes"), "PROCESS_DECODE_ERROR"),
    (ProcessLaunchError("os boom"), "PROCESS_LAUNCH_ERROR"),
]


@pytest.mark.parametrize(
    "error, code",
    PROCESS_MATRIX,
    ids=[type(e).__name__ for e, _ in PROCESS_MATRIX],
)
def test_each_process_error_maps_to_specific_failure_code(
    error: ProcessError, code: str
) -> None:
    _, pr = _pr()
    pr.fail("run", error)

    result = _changer(pr).transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == code


def test_non_zero_exit_maps_to_install_failed() -> None:
    inner, _ = _pr()
    inner.register(
        ("brew", "install"),
        ProcessResult(exit_code=1, stdout="", stderr="something broke", duration_ms=10),
    )

    result = _changer(inner).transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == "BREW_CASK_INSTALL_FAILED"
    assert result.details["exit_code"] == "1"


def test_cask_not_found_marker_maps_to_cask_not_found_code() -> None:
    inner, _ = _pr()
    inner.register(
        ("brew", "install"),
        ProcessResult(
            exit_code=1,
            stdout="",
            stderr="Error: No available cask with the name 'no-such'",
            duration_ms=10,
        ),
    )

    result = _changer(inner).transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == "CASK_NOT_FOUND"


def test_unexpected_runtime_error_propagates() -> None:
    _, pr = _pr()
    pr.fail("run", RuntimeError("unexpected"))

    with pytest.raises(RuntimeError, match="unexpected"):
        _changer(pr).transition()
