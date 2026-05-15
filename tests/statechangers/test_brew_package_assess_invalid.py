from __future__ import annotations

from statectl._interfaces.process import ProcessResult
from statectl._state_changer import ExistingState
from statectl._statechangers import (
    BrewPackageParameters,
    BrewPackageStateChanger,
)
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


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


def test_invalid_when_brew_not_on_path() -> None:
    pr = ScriptedProcessRunner()  # no brew registered
    changer = _changer(pr)

    assess = changer.assess_state()

    assert assess.state is ExistingState.INVALID
    assert any("brew binary not on PATH" in i for i in assess.issues)


def test_invalid_when_name_has_shell_metacharacters() -> None:
    pr = ScriptedProcessRunner()
    pr.register_executable("brew")
    changer = _changer(pr, name="ripgrep; rm -rf /")

    assess = changer.assess_state()

    assert assess.state is ExistingState.INVALID
    assert any("invalid formula name" in i for i in assess.issues)


def test_invalid_when_tap_malformed() -> None:
    pr = ScriptedProcessRunner()
    pr.register_executable("brew")
    changer = _changer(pr, tap="not-a-tap")

    assess = changer.assess_state()

    assert assess.state is ExistingState.INVALID
    assert any("invalid tap" in i for i in assess.issues)


def test_invalid_collects_all_input_issues_in_one_pass() -> None:
    pr = ScriptedProcessRunner()  # brew not on PATH
    changer = _changer(pr, name="bad name", tap="oops")

    assess = changer.assess_state()

    assert assess.state is ExistingState.INVALID
    joined = "\n".join(assess.issues)
    assert "brew binary not on PATH" in joined
    assert "invalid formula name" in joined
    assert "invalid tap" in joined


def test_invalid_when_installed_version_mismatches() -> None:
    pr = ScriptedProcessRunner()
    pr.register_executable("brew")
    pr.register(
        ("brew", "list", "--formula", "ripgrep"),
        ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=0),
    )
    pr.register(
        ("brew", "list", "--versions", "ripgrep"),
        ProcessResult(
            exit_code=0, stdout="ripgrep 14.0.0\n", stderr="", duration_ms=0
        ),
    )
    changer = _changer(pr, version="14.1.0")

    assess = changer.assess_state()

    assert assess.state is ExistingState.INVALID
    assert any(
        "installed version" in i and "14.0.0" in i and "14.1.0" in i
        for i in assess.issues
    )
