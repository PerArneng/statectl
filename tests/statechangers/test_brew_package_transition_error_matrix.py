from __future__ import annotations

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
    BrewPackageParameters,
    BrewPackageStateChanger,
)
from tests.fakes.failing_process_runner import FailingProcessRunner
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


def _inner_install_ok() -> ScriptedProcessRunner:
    pr = ScriptedProcessRunner()
    pr.register_executable("brew")
    pr.register(
        ("brew", "install", "ripgrep"),
        ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=0),
    )
    return pr


def test_install_non_zero_exit_returns_brew_install_failed() -> None:
    pr = ScriptedProcessRunner()
    pr.register_executable("brew")
    pr.register(
        ("brew", "install", "ripgrep"),
        ProcessResult(
            exit_code=1, stdout="", stderr="boom", duration_ms=5
        ),
    )
    changer = BrewPackageStateChanger(
        BrewPackageParameters(name="ripgrep"), process_runner=pr
    )

    result = changer.transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == "BREW_INSTALL_FAILED"
    assert result.details["exit_code"] == "1"
    assert result.details["stderr"] == "boom"


def test_pin_non_zero_exit_returns_brew_pin_failed() -> None:
    pr = ScriptedProcessRunner()
    pr.register_executable("brew")
    pr.register(
        ("brew", "install", "ripgrep"),
        ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=0),
    )
    pr.register(
        ("brew", "pin", "ripgrep"),
        ProcessResult(
            exit_code=2, stdout="", stderr="pin error", duration_ms=0
        ),
    )
    changer = BrewPackageStateChanger(
        BrewPackageParameters(name="ripgrep", pin=True),
        process_runner=pr,
    )

    result = changer.transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == "BREW_PIN_FAILED"
    # Earlier install details preserved on the failure
    assert result.details["install_exit_code"] == "0"
    assert result.details["exit_code"] == "2"


@pytest.mark.parametrize(
    "error, expected_code",
    [
        (ProcessNotFound("missing", argv=("brew",)), "BREW_NOT_FOUND"),
        (ProcessTimeout("timed out", argv=("brew",)), "PROCESS_TIMEOUT"),
        (ProcessDecodeError("decode", argv=("brew",)), "PROCESS_DECODE_ERROR"),
        (ProcessLaunchError("launch", argv=("brew",)), "PROCESS_LAUNCH_ERROR"),
    ],
)
def test_install_typed_errors_map_to_codes(
    error: BaseException, expected_code: str
) -> None:
    pr = FailingProcessRunner(_inner_install_ok())
    pr.fail("run", error)
    changer = BrewPackageStateChanger(
        BrewPackageParameters(name="ripgrep"), process_runner=pr
    )

    result = changer.transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == expected_code


def test_unexpected_exception_propagates() -> None:
    pr = FailingProcessRunner(_inner_install_ok())
    pr.fail("run", RuntimeError("boom"))
    changer = BrewPackageStateChanger(
        BrewPackageParameters(name="ripgrep"), process_runner=pr
    )

    with pytest.raises(RuntimeError):
        changer.transition()
