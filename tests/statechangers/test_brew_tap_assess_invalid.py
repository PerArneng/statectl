from __future__ import annotations

import json

from statectl._interfaces.process import ProcessResult
from statectl._state_changer import ExistingState
from statectl._statechangers import BrewTapParameters, BrewTapStateChanger
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


def _pr(*, brew_on_path: bool = True) -> ScriptedProcessRunner:
    pr = ScriptedProcessRunner()
    if brew_on_path:
        pr.register_executable("brew")
    return pr


def _changer(
    *,
    name: str = "homebrew/cask-fonts",
    url: str | None = None,
    pr: ScriptedProcessRunner | None = None,
) -> BrewTapStateChanger:
    return BrewTapStateChanger(
        BrewTapParameters(name=name, url=url),
        process_runner=pr or _pr(),
    )


def test_invalid_when_name_does_not_match_pattern() -> None:
    changer = _changer(name="not-a-valid-name")

    assessment = changer.assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("invalid tap name" in i for i in assessment.issues)


def test_invalid_when_brew_not_on_path() -> None:
    changer = _changer(pr=_pr(brew_on_path=False))

    assessment = changer.assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("brew binary not on PATH" in i for i in assessment.issues)


def test_invalid_collects_both_name_and_path_in_one_pass() -> None:
    changer = _changer(name="bad name", pr=_pr(brew_on_path=False))

    assessment = changer.assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("invalid tap name" in i for i in assessment.issues)
    assert any("brew binary not on PATH" in i for i in assessment.issues)


def test_invalid_when_tap_exists_with_different_url() -> None:
    pr = _pr()
    pr.register(
        ("brew", "tap"),
        ProcessResult(exit_code=0, stdout="homebrew/cask-fonts\n", stderr="", duration_ms=1),
    )
    pr.register(
        ("brew", "tap-info"),
        ProcessResult(
            exit_code=0,
            stdout=json.dumps(
                [{"name": "homebrew/cask-fonts", "remote": "https://other.example/fonts"}]
            ),
            stderr="",
            duration_ms=1,
        ),
    )
    changer = _changer(url="https://github.com/homebrew/cask-fonts", pr=pr)

    assessment = changer.assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("different URL" in assessment.description or "different URL" in i
               for i in [assessment.description, *assessment.issues])


def test_invalid_when_brew_tap_exits_nonzero() -> None:
    pr = _pr()
    pr.register(
        ("brew", "tap"),
        ProcessResult(exit_code=1, stdout="", stderr="boom", duration_ms=1),
    )
    changer = _changer(pr=pr)

    assessment = changer.assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("exited 1" in i for i in assessment.issues)


def test_invalid_when_tap_info_returns_unparseable_json() -> None:
    pr = _pr()
    pr.register(
        ("brew", "tap"),
        ProcessResult(exit_code=0, stdout="homebrew/cask-fonts\n", stderr="", duration_ms=1),
    )
    pr.register(
        ("brew", "tap-info"),
        ProcessResult(exit_code=0, stdout="not json", stderr="", duration_ms=1),
    )
    changer = _changer(url="https://github.com/homebrew/cask-fonts", pr=pr)

    assessment = changer.assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("could not parse" in i for i in assessment.issues)
