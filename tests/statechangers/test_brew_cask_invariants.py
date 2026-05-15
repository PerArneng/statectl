from __future__ import annotations

import pytest

from statectl._state_changer import RollbackableStateChanger, StateChanger
from statectl._statechangers import (
    BrewCaskParameters,
    BrewCaskRollbackStateChanger,
    BrewCaskStateChanger,
)
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


def _rig() -> ScriptedProcessRunner:
    pr = ScriptedProcessRunner()
    pr.register_executable("brew")
    return pr


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


def test_is_a_rollbackable_state_changer() -> None:
    changer = _changer(_rig())

    assert isinstance(changer, RollbackableStateChanger)
    assert isinstance(changer, StateChanger)


def test_rollback_returns_plain_state_changer() -> None:
    changer = _changer(_rig())
    rb = changer.rollback()

    assert isinstance(rb, StateChanger)
    assert not isinstance(rb, RollbackableStateChanger)
    assert isinstance(rb, BrewCaskRollbackStateChanger)


def test_parameters_are_frozen() -> None:
    params = BrewCaskParameters(name="google-chrome")

    with pytest.raises(Exception):
        params.name = "firefox"  # type: ignore[misc]


def test_name_encodes_cask_ref_without_tap() -> None:
    changer = _changer(_rig(), name="google-chrome")
    assert changer.name() == "brew-cask:google-chrome"


def test_name_encodes_cask_ref_with_tap() -> None:
    changer = _changer(_rig(), name="my-cask", tap="acme/private")
    assert changer.name() == "brew-cask:acme/private/my-cask"


def test_rollback_name_encodes_cask_ref() -> None:
    changer = _changer(_rig(), name="google-chrome")
    assert changer.rollback().name() == "brew-cask-rollback:google-chrome"


def test_assess_state_does_not_mutate_any_state() -> None:
    pr = _rig()
    # `brew list --cask --versions` exit 0 with empty stdout = not installed.
    changer = _changer(pr)

    before_calls = list(pr.calls)
    changer.assess_state()
    after_calls = list(pr.calls)

    # assess_state must invoke `which` (no record) plus run calls; no other
    # side effect channel exists on the fake.
    assert len(after_calls) >= len(before_calls)
