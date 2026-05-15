from __future__ import annotations

import json

import pytest

from statectl._interfaces.process import ProcessResult
from statectl._state_changer import ExistingState
from statectl._statechangers import BrewTapParameters, BrewTapStateChanger
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


TAP = "homebrew/cask-fonts"
URL = "https://github.com/homebrew/cask-fonts"


def _pr_with_tap_list(stdout: str) -> ScriptedProcessRunner:
    pr = ScriptedProcessRunner()
    pr.register_executable("brew")
    pr.register(
        ("brew", "tap"),
        ProcessResult(exit_code=0, stdout=stdout, stderr="", duration_ms=1),
    )
    return pr


def _register_tap_info(pr: ScriptedProcessRunner, remote: str) -> None:
    pr.register(
        ("brew", "tap-info"),
        ProcessResult(
            exit_code=0,
            stdout=json.dumps([{"name": TAP, "remote": remote, "installed": []}]),
            stderr="",
            duration_ms=1,
        ),
    )


@pytest.mark.parametrize(
    "tap_state, url_param, expected",
    [
        ("not_tapped", None, ExistingState.READY),
        ("not_tapped", URL, ExistingState.READY),
        ("tapped_default_url", None, ExistingState.ALREADY_APPLIED),
        ("tapped_default_url", URL, ExistingState.ALREADY_APPLIED),
        ("tapped_different_url", None, ExistingState.ALREADY_APPLIED),
        ("tapped_different_url", URL, ExistingState.INVALID),
    ],
)
def test_truth_table(tap_state: str, url_param: str | None, expected: ExistingState) -> None:
    if tap_state == "not_tapped":
        pr = _pr_with_tap_list("other/tap\n")
    elif tap_state == "tapped_default_url":
        pr = _pr_with_tap_list(f"{TAP}\nother/tap\n")
        _register_tap_info(pr, remote=URL)
    elif tap_state == "tapped_different_url":
        pr = _pr_with_tap_list(f"{TAP}\n")
        _register_tap_info(pr, remote="https://other.example/fonts")
    else:
        raise AssertionError(tap_state)

    changer = BrewTapStateChanger(
        BrewTapParameters(name=TAP, url=url_param),
        process_runner=pr,
    )

    assert changer.assess_state().state is expected


def test_already_applied_ignores_url_when_param_url_is_none() -> None:
    """Even if remote differs, with url=None we don't run tap-info — ALREADY_APPLIED."""
    pr = _pr_with_tap_list(f"{TAP}\n")
    # Intentionally do NOT register tap-info: if assess called it, the
    # scripted runner would return the default zero-exit empty result and
    # JSON parsing would mark INVALID. We assert it stays ALREADY_APPLIED.
    changer = BrewTapStateChanger(
        BrewTapParameters(name=TAP, url=None),
        process_runner=pr,
    )

    assert changer.assess_state().state is ExistingState.ALREADY_APPLIED
    # Only `brew tap` was invoked.
    assert all(call.argv[:2] != ("brew", "tap-info") for call in pr.calls)
