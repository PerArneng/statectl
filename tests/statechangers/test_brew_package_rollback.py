from __future__ import annotations

from statectl._interfaces.process import ProcessResult
from statectl._state_changer import ExistingState, ResultStatus
from statectl._statechangers import (
    BrewPackageParameters,
    BrewPackageRollbackStateChanger,
    BrewPackageStateChanger,
)
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


def _runner_with_brew() -> ScriptedProcessRunner:
    pr = ScriptedProcessRunner()
    pr.register_executable("brew")
    return pr


def _inverse(
    pr: ScriptedProcessRunner, *, name: str = "ripgrep"
) -> BrewPackageRollbackStateChanger:
    forward = BrewPackageStateChanger(
        BrewPackageParameters(name=name), process_runner=pr
    )
    inverse = forward.rollback()
    assert isinstance(inverse, BrewPackageRollbackStateChanger)
    return inverse


def test_rollback_already_applied_when_formula_not_installed() -> None:
    pr = _runner_with_brew()
    pr.register(
        ("brew", "list", "--formula", "ripgrep"),
        ProcessResult(exit_code=1, stdout="", stderr="", duration_ms=0),
    )

    assess = _inverse(pr).assess_state()

    assert assess.state is ExistingState.ALREADY_APPLIED


def test_rollback_ready_when_installed_and_not_pinned() -> None:
    pr = _runner_with_brew()
    pr.register(
        ("brew", "list", "--formula", "ripgrep"),
        ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=0),
    )
    pr.register(
        ("brew", "list", "--pinned"),
        ProcessResult(exit_code=0, stdout="fd\n", stderr="", duration_ms=0),
    )

    assess = _inverse(pr).assess_state()

    assert assess.state is ExistingState.READY


def test_rollback_invalid_when_installed_and_pinned() -> None:
    pr = _runner_with_brew()
    pr.register(
        ("brew", "list", "--formula", "ripgrep"),
        ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=0),
    )
    pr.register(
        ("brew", "list", "--pinned"),
        ProcessResult(
            exit_code=0, stdout="ripgrep\nfd\n", stderr="", duration_ms=0
        ),
    )

    assess = _inverse(pr).assess_state()

    assert assess.state is ExistingState.INVALID
    assert any("pinned" in i for i in assess.issues)


def test_rollback_transition_runs_brew_uninstall() -> None:
    pr = _runner_with_brew()
    pr.register(
        ("brew", "uninstall", "ripgrep"),
        ProcessResult(
            exit_code=0, stdout="Uninstalled", stderr="", duration_ms=3
        ),
    )

    result = _inverse(pr).transition()

    assert result.status is ResultStatus.SUCCESS
    assert pr.calls[-1].argv == ("brew", "uninstall", "ripgrep")


def test_rollback_transition_non_zero_returns_brew_uninstall_failed() -> None:
    pr = _runner_with_brew()
    pr.register(
        ("brew", "uninstall", "ripgrep"),
        ProcessResult(
            exit_code=1, stdout="", stderr="nope", duration_ms=0
        ),
    )

    result = _inverse(pr).transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == "BREW_UNINSTALL_FAILED"
    assert result.details["stderr"] == "nope"


def test_rollback_invalid_when_brew_not_on_path() -> None:
    pr = ScriptedProcessRunner()  # brew not registered

    assess = _inverse(pr).assess_state()

    assert assess.state is ExistingState.INVALID
    assert any("brew binary not on PATH" in i for i in assess.issues)
