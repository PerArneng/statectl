from __future__ import annotations

import pytest

from statectl._state_changer import RollbackableStateChanger, StateChanger
from statectl._statechangers import (
    EnsureSystemdUnitParameters,
    EnsureSystemdUnitRollbackStateChanger,
)
from tests.statechangers._systemd_helpers import (
    DEFAULT_UNIT,
    make_changer,
    make_unit_content,
)


def test_is_a_rollbackable_state_changer() -> None:
    changer = make_changer()
    assert isinstance(changer, RollbackableStateChanger)
    assert isinstance(changer, StateChanger)


def test_rollback_returns_plain_state_changer() -> None:
    rb = make_changer().rollback()
    assert isinstance(rb, StateChanger)
    assert not isinstance(rb, RollbackableStateChanger)
    assert isinstance(rb, EnsureSystemdUnitRollbackStateChanger)


def test_parameters_are_frozen() -> None:
    params = EnsureSystemdUnitParameters(
        unit_name=DEFAULT_UNIT,
        unit_content=make_unit_content(),
        scope="user",
    )
    with pytest.raises(Exception):
        params.unit_name = "other"  # type: ignore[misc]


def test_name_encodes_unit_name() -> None:
    assert make_changer().name() == f"ensure-systemd-unit:{DEFAULT_UNIT}"


def test_rollback_name_encodes_unit_name() -> None:
    assert (
        make_changer().rollback().name()
        == f"ensure-systemd-unit-rollback:{DEFAULT_UNIT}"
    )
