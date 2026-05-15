from __future__ import annotations

import pytest

from statectl._state_changer import RollbackableStateChanger, StateChanger
from statectl._statechangers import (
    BrewTapParameters,
    BrewTapRollbackStateChanger,
    BrewTapStateChanger,
)
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


def _changer(
    *,
    name: str = "homebrew/cask-fonts",
    url: str | None = None,
    pr: ScriptedProcessRunner | None = None,
) -> BrewTapStateChanger:
    return BrewTapStateChanger(
        BrewTapParameters(name=name, url=url),
        process_runner=pr or ScriptedProcessRunner(),
    )


def test_is_rollbackable_state_changer() -> None:
    assert isinstance(_changer(), RollbackableStateChanger)


def test_rollback_returns_plain_state_changer() -> None:
    forward = _changer()
    rb = forward.rollback()

    assert isinstance(rb, StateChanger)
    assert not isinstance(rb, RollbackableStateChanger)
    assert isinstance(rb, BrewTapRollbackStateChanger)


def test_parameters_are_frozen() -> None:
    params = BrewTapParameters(name="homebrew/cask-fonts")

    with pytest.raises(Exception):
        params.name = "other/tap"  # type: ignore[misc]


def test_name_encodes_tap_name() -> None:
    forward = _changer(name="homebrew/cask-fonts")

    assert forward.name() == "brew-tap:homebrew/cask-fonts"


def test_rollback_name_encodes_tap_name() -> None:
    rb = _changer(name="homebrew/cask-fonts").rollback()

    assert rb.name() == "brew-tap-rollback:homebrew/cask-fonts"


def test_assess_state_does_not_mutate_process_runner_calls_on_invalid_name() -> None:
    pr = ScriptedProcessRunner()
    pr.register_executable("brew")
    changer = _changer(name="not-a-valid-name", pr=pr)

    changer.assess_state()

    assert pr.calls == []
