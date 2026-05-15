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
from statectl._state_changer import ExistingState, ResultStatus
from statectl._statechangers import (
    BrewCaskParameters,
    BrewCaskRollbackStateChanger,
    BrewCaskStateChanger,
)
from tests.fakes.failing_process_runner import FailingProcessRunner
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


def _changer(pr: ScriptedProcessRunner) -> BrewCaskRollbackStateChanger:
    forward = BrewCaskStateChanger(
        BrewCaskParameters(name="google-chrome"),
        process_runner=pr,
    )
    rb = forward.rollback()
    assert isinstance(rb, BrewCaskRollbackStateChanger)
    return rb


def _pr() -> ScriptedProcessRunner:
    pr = ScriptedProcessRunner()
    pr.register_executable("brew")
    return pr


def test_rollback_invalid_when_brew_missing() -> None:
    pr = ScriptedProcessRunner()
    assessment = _changer(pr).assess_state()

    assert assessment.state is ExistingState.INVALID


def test_rollback_already_applied_when_cask_not_installed() -> None:
    pr = _pr()
    pr.register(
        ("brew", "list"),
        ProcessResult(exit_code=1, stdout="", stderr="", duration_ms=0),
    )
    assessment = _changer(pr).assess_state()

    assert assessment.state is ExistingState.ALREADY_APPLIED


def test_rollback_ready_when_cask_installed() -> None:
    pr = _pr()
    pr.register(
        ("brew", "list"),
        ProcessResult(
            exit_code=0,
            stdout="google-chrome 1.2.3\n",
            stderr="",
            duration_ms=0,
        ),
    )
    assessment = _changer(pr).assess_state()

    assert assessment.state is ExistingState.READY


def test_rollback_transition_success() -> None:
    pr = _pr()
    pr.register(
        ("brew", "uninstall"),
        ProcessResult(exit_code=0, stdout="Uninstalling", stderr="", duration_ms=10),
    )
    result = _changer(pr).transition()

    assert result.status is ResultStatus.SUCCESS
    uninstall_calls = [c for c in pr.calls if c.argv[:2] == ("brew", "uninstall")]
    assert uninstall_calls[0].argv == ("brew", "uninstall", "--cask", "google-chrome")


def test_rollback_transition_failure_on_non_zero_exit() -> None:
    pr = _pr()
    pr.register(
        ("brew", "uninstall"),
        ProcessResult(exit_code=1, stdout="", stderr="nope", duration_ms=0),
    )
    result = _changer(pr).transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == "BREW_CASK_UNINSTALL_FAILED"


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
def test_rollback_each_process_error_maps_to_specific_code(
    error: ProcessError, code: str
) -> None:
    inner = _pr()
    pr = FailingProcessRunner(inner)
    pr.fail("run", error)

    forward = BrewCaskStateChanger(
        BrewCaskParameters(name="google-chrome"),
        process_runner=pr,  # type: ignore[arg-type]
    )
    rb = forward.rollback()
    result = rb.transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == code
