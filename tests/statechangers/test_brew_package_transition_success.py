from __future__ import annotations

from statectl._interfaces.process import ProcessResult
from statectl._state_changer import ResultStatus
from statectl._statechangers import (
    BrewPackageParameters,
    BrewPackageStateChanger,
)
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


def _runner_with_brew() -> ScriptedProcessRunner:
    pr = ScriptedProcessRunner()
    pr.register_executable("brew")
    return pr


def test_transition_runs_brew_install_and_returns_success() -> None:
    pr = _runner_with_brew()
    pr.register(
        ("brew", "install", "ripgrep"),
        ProcessResult(
            exit_code=0, stdout="Installed", stderr="", duration_ms=12
        ),
    )
    changer = BrewPackageStateChanger(
        BrewPackageParameters(name="ripgrep"), process_runner=pr
    )

    result = changer.transition()

    assert result.status is ResultStatus.SUCCESS
    assert result.code == "OK"
    assert result.details["install_exit_code"] == "0"
    assert result.details["install_stdout"] == "Installed"
    assert pr.calls[-1].argv == ("brew", "install", "ripgrep")


def test_transition_uses_versioned_install_target() -> None:
    pr = _runner_with_brew()
    pr.register(
        ("brew", "install", "python@3.11"),
        ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=0),
    )
    changer = BrewPackageStateChanger(
        BrewPackageParameters(name="python", version="3.11"),
        process_runner=pr,
    )

    result = changer.transition()

    assert result.status is ResultStatus.SUCCESS
    assert pr.calls[-1].argv == ("brew", "install", "python@3.11")


def test_transition_uses_tap_qualified_install_target() -> None:
    pr = _runner_with_brew()
    pr.register(
        ("brew", "install", "user/repo/widget"),
        ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=0),
    )
    changer = BrewPackageStateChanger(
        BrewPackageParameters(name="widget", tap="user/repo"),
        process_runner=pr,
    )

    result = changer.transition()

    assert result.status is ResultStatus.SUCCESS
    assert pr.calls[-1].argv == ("brew", "install", "user/repo/widget")


def test_transition_pins_when_requested() -> None:
    pr = _runner_with_brew()
    pr.register(
        ("brew", "install", "ripgrep"),
        ProcessResult(exit_code=0, stdout="ok", stderr="", duration_ms=0),
    )
    pr.register(
        ("brew", "pin", "ripgrep"),
        ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=0),
    )
    changer = BrewPackageStateChanger(
        BrewPackageParameters(name="ripgrep", pin=True),
        process_runner=pr,
    )

    result = changer.transition()

    assert result.status is ResultStatus.SUCCESS
    assert result.details["pin_exit_code"] == "0"
    argvs = [c.argv for c in pr.calls]
    assert ("brew", "install", "ripgrep") in argvs
    assert ("brew", "pin", "ripgrep") in argvs


def test_transition_does_not_pin_when_not_requested() -> None:
    pr = _runner_with_brew()
    pr.register(
        ("brew", "install", "ripgrep"),
        ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=0),
    )
    changer = BrewPackageStateChanger(
        BrewPackageParameters(name="ripgrep", pin=False),
        process_runner=pr,
    )

    result = changer.transition()

    assert result.status is ResultStatus.SUCCESS
    assert "pin_exit_code" not in result.details
    assert not any(c.argv[:2] == ("brew", "pin") for c in pr.calls)
