from __future__ import annotations

import pytest

from statectl._interfaces.process import (
    ProcessDecodeError,
    ProcessLaunchError,
    ProcessNotFound,
    ProcessTimeout,
)
from statectl._state_changer import ResultStatus
from statectl._statechangers import BrewTapParameters, BrewTapStateChanger
from tests.fakes.failing_process_runner import FailingProcessRunner
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


TAP = "homebrew/cask-fonts"


@pytest.mark.parametrize(
    "error, expected_code",
    [
        (ProcessNotFound("gone"), "BREW_NOT_FOUND"),
        (ProcessTimeout("slow"), "PROCESS_TIMEOUT"),
        (ProcessDecodeError("bytes"), "PROCESS_DECODE_ERROR"),
        (ProcessLaunchError("eaccess"), "PROCESS_LAUNCH_ERROR"),
    ],
)
def test_transition_maps_typed_errors(error: Exception, expected_code: str) -> None:
    inner = ScriptedProcessRunner()
    inner.register_executable("brew")
    pr = FailingProcessRunner(inner)
    pr.fail("run", error)
    changer = BrewTapStateChanger(BrewTapParameters(name=TAP), process_runner=pr)

    result = changer.transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == expected_code


def test_transition_lets_unexpected_exceptions_propagate() -> None:
    inner = ScriptedProcessRunner()
    inner.register_executable("brew")
    pr = FailingProcessRunner(inner)
    pr.fail("run", RuntimeError("not our exception"))
    changer = BrewTapStateChanger(BrewTapParameters(name=TAP), process_runner=pr)

    with pytest.raises(RuntimeError):
        changer.transition()
