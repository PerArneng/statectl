from __future__ import annotations

from statectl._interfaces.process import ProcessResult
from statectl._state_changer import ExistingState
from statectl._statechangers import BrewCaskParameters, BrewCaskStateChanger
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


def _changer(
    pr: ScriptedProcessRunner,
    *,
    name: str = "google-chrome",
    version: str | None = None,
    tap: str | None = None,
) -> BrewCaskStateChanger:
    return BrewCaskStateChanger(
        BrewCaskParameters(name=name, version=version, tap=tap),
        process_runner=pr,
    )


def test_invalid_when_brew_not_on_path() -> None:
    pr = ScriptedProcessRunner()
    assessment = _changer(pr).assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("brew binary not on PATH" in i for i in assessment.issues)


def test_invalid_when_name_has_shell_metacharacters() -> None:
    pr = ScriptedProcessRunner()
    pr.register_executable("brew")
    assessment = _changer(pr, name="evil; rm -rf /").assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("shell metacharacters" in i for i in assessment.issues)


def test_invalid_when_cask_not_found_in_taps() -> None:
    pr = ScriptedProcessRunner()
    pr.register_executable("brew")
    # not installed
    pr.register(
        ("brew", "list"),
        ProcessResult(exit_code=1, stdout="", stderr="", duration_ms=0),
    )
    # brew info exits non-zero → unknown cask
    pr.register(
        ("brew", "info"),
        ProcessResult(exit_code=1, stdout="", stderr="Error: No available cask", duration_ms=0),
    )
    assessment = _changer(pr, name="no-such-cask").assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("cask not found: no-such-cask" in i for i in assessment.issues)


def test_invalid_when_installed_version_does_not_match_requested() -> None:
    pr = ScriptedProcessRunner()
    pr.register_executable("brew")
    pr.register(
        ("brew", "list"),
        ProcessResult(
            exit_code=0,
            stdout="google-chrome 121.0.6167.85\n",
            stderr="",
            duration_ms=0,
        ),
    )
    assessment = _changer(pr, name="google-chrome", version="120.0.0").assess_state()

    assert assessment.state is ExistingState.INVALID
    joined = " ".join(assessment.issues)
    assert "installed version 121.0.6167.85" in joined
    assert "requested 120.0.0" in joined


def test_invalid_collects_multiple_issues_at_once() -> None:
    pr = ScriptedProcessRunner()
    # brew missing AND shell metacharacters
    assessment = _changer(pr, name="bad;name").assess_state()

    assert assessment.state is ExistingState.INVALID
    assert len(assessment.issues) >= 2
    assert any("brew binary not on PATH" in i for i in assessment.issues)
    assert any("shell metacharacters" in i for i in assessment.issues)


def test_invalid_uses_tap_qualified_ref_for_cask_not_found() -> None:
    pr = ScriptedProcessRunner()
    pr.register_executable("brew")
    pr.register(
        ("brew", "list"),
        ProcessResult(exit_code=1, stdout="", stderr="", duration_ms=0),
    )
    pr.register(
        ("brew", "info"),
        ProcessResult(exit_code=1, stdout="", stderr="", duration_ms=0),
    )
    assessment = _changer(pr, name="thing", tap="acme/private").assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("cask not found: acme/private/thing" in i for i in assessment.issues)
