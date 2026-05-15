from __future__ import annotations

import pytest

from statectl._state_changer import RollbackableStateChanger, StateChanger
from statectl._statechangers import (
    BrewPackageParameters,
    BrewPackageRollbackStateChanger,
    BrewPackageStateChanger,
)
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


def _rig() -> ScriptedProcessRunner:
    pr = ScriptedProcessRunner()
    pr.register_executable("brew")
    return pr


def test_is_rollbackable_state_changer() -> None:
    pr = _rig()
    changer = BrewPackageStateChanger(
        BrewPackageParameters(name="ripgrep"), process_runner=pr
    )

    assert isinstance(changer, RollbackableStateChanger)


def test_rollback_returns_plain_state_changer() -> None:
    pr = _rig()
    changer = BrewPackageStateChanger(
        BrewPackageParameters(name="ripgrep"), process_runner=pr
    )

    inverse = changer.rollback()

    assert isinstance(inverse, StateChanger)
    assert not isinstance(inverse, RollbackableStateChanger)
    assert isinstance(inverse, BrewPackageRollbackStateChanger)


def test_parameters_are_frozen() -> None:
    params = BrewPackageParameters(name="ripgrep")

    with pytest.raises(Exception):
        params.name = "fd"  # type: ignore[misc]


def test_name_encodes_install_target_plain() -> None:
    pr = _rig()
    changer = BrewPackageStateChanger(
        BrewPackageParameters(name="ripgrep"), process_runner=pr
    )

    assert changer.name() == "brew-package:ripgrep"


def test_name_encodes_install_target_with_version_and_tap() -> None:
    pr = _rig()
    changer = BrewPackageStateChanger(
        BrewPackageParameters(
            name="python", version="3.11", tap="user/repo"
        ),
        process_runner=pr,
    )

    assert changer.name() == "brew-package:user/repo/python@3.11"


def test_rollback_name_encodes_formula() -> None:
    pr = _rig()
    inverse = BrewPackageRollbackStateChanger(
        BrewPackageParameters(name="ripgrep"), process_runner=pr
    )

    assert inverse.name() == "brew-package-rollback:ripgrep"
