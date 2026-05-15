from __future__ import annotations

from statectl._interfaces.process import (
    ProcessLaunchError,
    ProcessNotFound,
    ProcessTimeout,
)
from statectl._state_changer import ExistingState
from statectl._statechangers import BrewTapParameters, BrewTapStateChanger
from tests.fakes.failing_process_runner import FailingProcessRunner
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


TAP = "homebrew/cask-fonts"


def _build_with_failure(error: BaseException) -> BrewTapStateChanger:
    inner = ScriptedProcessRunner()
    inner.register_executable("brew")
    pr = FailingProcessRunner(inner)
    pr.fail("run", error)
    return BrewTapStateChanger(
        BrewTapParameters(name=TAP),
        process_runner=pr,
    )


def test_assess_translates_process_not_found_to_invalid() -> None:
    changer = _build_with_failure(ProcessNotFound("vanished"))

    assessment = changer.assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("brew not found" in i for i in assessment.issues)


def test_assess_translates_process_timeout_to_invalid() -> None:
    changer = _build_with_failure(ProcessTimeout("too slow"))

    assessment = changer.assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("timed out" in i for i in assessment.issues)


def test_assess_translates_process_launch_error_to_invalid() -> None:
    changer = _build_with_failure(ProcessLaunchError("eaccess"))

    assessment = changer.assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("launch error" in i for i in assessment.issues)
