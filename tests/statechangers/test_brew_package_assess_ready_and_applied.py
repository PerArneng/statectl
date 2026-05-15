from __future__ import annotations

from statectl._interfaces.process import ProcessResult
from statectl._state_changer import ExistingState
from statectl._statechangers import (
    BrewPackageParameters,
    BrewPackageStateChanger,
)
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


def _runner_with_brew() -> ScriptedProcessRunner:
    pr = ScriptedProcessRunner()
    pr.register_executable("brew")
    return pr


def _list_formula(pr: ScriptedProcessRunner, name: str, installed: bool) -> None:
    pr.register(
        ("brew", "list", "--formula", name),
        ProcessResult(
            exit_code=0 if installed else 1, stdout="", stderr="", duration_ms=0
        ),
    )


def _list_versions(pr: ScriptedProcessRunner, name: str, version: str) -> None:
    pr.register(
        ("brew", "list", "--versions", name),
        ProcessResult(
            exit_code=0,
            stdout=f"{name} {version}\n",
            stderr="",
            duration_ms=0,
        ),
    )


def _list_pinned(pr: ScriptedProcessRunner, pinned: list[str]) -> None:
    pr.register(
        ("brew", "list", "--pinned"),
        ProcessResult(
            exit_code=0,
            stdout="\n".join(pinned) + ("\n" if pinned else ""),
            stderr="",
            duration_ms=0,
        ),
    )


def _changer(
    pr: ScriptedProcessRunner,
    *,
    name: str = "ripgrep",
    version: str | None = None,
    pin: bool = False,
    tap: str | None = None,
) -> BrewPackageStateChanger:
    return BrewPackageStateChanger(
        BrewPackageParameters(name=name, version=version, pin=pin, tap=tap),
        process_runner=pr,
    )


def test_ready_when_not_installed() -> None:
    pr = _runner_with_brew()
    _list_formula(pr, "ripgrep", installed=False)
    changer = _changer(pr)

    assess = changer.assess_state()

    assert assess.state is ExistingState.READY


def test_already_applied_when_installed_and_no_version_no_pin() -> None:
    pr = _runner_with_brew()
    _list_formula(pr, "ripgrep", installed=True)
    changer = _changer(pr)

    assess = changer.assess_state()

    assert assess.state is ExistingState.ALREADY_APPLIED


def test_already_applied_when_installed_version_matches() -> None:
    pr = _runner_with_brew()
    _list_formula(pr, "ripgrep", installed=True)
    _list_versions(pr, "ripgrep", "14.1.0")
    changer = _changer(pr, version="14.1.0")

    assess = changer.assess_state()

    assert assess.state is ExistingState.ALREADY_APPLIED


def test_already_applied_when_installed_and_pinned() -> None:
    pr = _runner_with_brew()
    _list_formula(pr, "ripgrep", installed=True)
    _list_pinned(pr, ["ripgrep", "fd"])
    changer = _changer(pr, pin=True)

    assess = changer.assess_state()

    assert assess.state is ExistingState.ALREADY_APPLIED


def test_ready_when_installed_but_not_pinned_and_pin_requested() -> None:
    pr = _runner_with_brew()
    _list_formula(pr, "ripgrep", installed=True)
    _list_pinned(pr, ["fd"])
    changer = _changer(pr, pin=True)

    assess = changer.assess_state()

    assert assess.state is ExistingState.READY
    assert "ready to pin" in assess.description


def test_already_applied_when_installed_pin_false_pinned_anyway() -> None:
    pr = _runner_with_brew()
    _list_formula(pr, "ripgrep", installed=True)
    # pin=False so brew list --pinned should not be probed
    changer = _changer(pr, pin=False)

    assess = changer.assess_state()

    assert assess.state is ExistingState.ALREADY_APPLIED
    # Sanity: the pinned probe was not invoked
    assert not any(
        call.argv == ("brew", "list", "--pinned") for call in pr.calls
    )
