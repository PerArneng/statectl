from __future__ import annotations

import json

from statectl._interfaces.process import ProcessResult
from statectl._state_changer import ExistingState, ResultStatus
from statectl._statechangers import BrewTapParameters, BrewTapStateChanger
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


TAP = "homebrew/cask-fonts"


def _pr_with_taps(stdout: str) -> ScriptedProcessRunner:
    pr = ScriptedProcessRunner()
    pr.register_executable("brew")
    pr.register(
        ("brew", "tap"),
        ProcessResult(exit_code=0, stdout=stdout, stderr="", duration_ms=1),
    )
    return pr


def _register_tap_info(
    pr: ScriptedProcessRunner, *, installed: list[dict[str, str]] | None = None
) -> None:
    pr.register(
        ("brew", "tap-info"),
        ProcessResult(
            exit_code=0,
            stdout=json.dumps([{"name": TAP, "installed": installed or []}]),
            stderr="",
            duration_ms=1,
        ),
    )


def _rollback(pr: ScriptedProcessRunner):
    forward = BrewTapStateChanger(BrewTapParameters(name=TAP), process_runner=pr)
    return forward.rollback()


def test_rollback_already_applied_when_tap_absent() -> None:
    pr = _pr_with_taps("other/tap\n")

    assert _rollback(pr).assess_state().state is ExistingState.ALREADY_APPLIED


def test_rollback_ready_when_tap_present_and_no_installed_formulae() -> None:
    pr = _pr_with_taps(f"{TAP}\n")
    _register_tap_info(pr, installed=[])

    assert _rollback(pr).assess_state().state is ExistingState.READY


def test_rollback_invalid_when_tap_has_installed_formulae() -> None:
    pr = _pr_with_taps(f"{TAP}\n")
    _register_tap_info(pr, installed=[{"name": "some-formula"}])

    assessment = _rollback(pr).assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("installed formulae" in i for i in assessment.issues)


def test_rollback_invalid_when_brew_not_on_path() -> None:
    pr = ScriptedProcessRunner()  # no brew registered

    assessment = _rollback(pr).assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("brew binary not on PATH" in i for i in assessment.issues)


def test_rollback_transition_runs_brew_untap() -> None:
    pr = _pr_with_taps(f"{TAP}\n")
    pr.register(
        ("brew", "untap", TAP),
        ProcessResult(exit_code=0, stdout="Untapped", stderr="", duration_ms=5),
    )
    rb = _rollback(pr)

    result = rb.transition()

    assert result.status is ResultStatus.SUCCESS
    assert any(call.argv == ("brew", "untap", TAP) for call in pr.calls)


def test_rollback_transition_failure_on_nonzero_exit() -> None:
    pr = _pr_with_taps(f"{TAP}\n")
    pr.register(
        ("brew", "untap", TAP),
        ProcessResult(exit_code=1, stdout="", stderr="busy", duration_ms=5),
    )
    rb = _rollback(pr)

    result = rb.transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == "BREW_UNTAP_FAILED"
