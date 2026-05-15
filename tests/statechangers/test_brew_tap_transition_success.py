from __future__ import annotations

from statectl._interfaces.process import ProcessResult
from statectl._state_changer import ResultStatus
from statectl._statechangers import BrewTapParameters, BrewTapStateChanger
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


TAP = "homebrew/cask-fonts"
URL = "https://github.com/homebrew/cask-fonts"


def _pr() -> ScriptedProcessRunner:
    pr = ScriptedProcessRunner()
    pr.register_executable("brew")
    return pr


def test_transition_runs_brew_tap_without_url() -> None:
    pr = _pr()
    pr.register(
        ("brew", "tap", TAP),
        ProcessResult(exit_code=0, stdout="Tapped!", stderr="", duration_ms=10),
    )
    changer = BrewTapStateChanger(BrewTapParameters(name=TAP), process_runner=pr)

    result = changer.transition()

    assert result.status is ResultStatus.SUCCESS
    assert result.code == "OK"
    assert result.details["exit_code"] == "0"
    assert any(call.argv == ("brew", "tap", TAP) for call in pr.calls)


def test_transition_runs_brew_tap_with_url() -> None:
    pr = _pr()
    pr.register(
        ("brew", "tap", TAP, URL),
        ProcessResult(exit_code=0, stdout="Tapped!", stderr="", duration_ms=10),
    )
    changer = BrewTapStateChanger(
        BrewTapParameters(name=TAP, url=URL), process_runner=pr
    )

    result = changer.transition()

    assert result.status is ResultStatus.SUCCESS
    assert any(call.argv == ("brew", "tap", TAP, URL) for call in pr.calls)


def test_transition_failure_on_nonzero_exit() -> None:
    pr = _pr()
    pr.register(
        ("brew", "tap", TAP),
        ProcessResult(exit_code=1, stdout="", stderr="nope", duration_ms=5),
    )
    changer = BrewTapStateChanger(BrewTapParameters(name=TAP), process_runner=pr)

    result = changer.transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == "BREW_TAP_FAILED"
    assert result.details["exit_code"] == "1"
