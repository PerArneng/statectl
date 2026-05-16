from __future__ import annotations

import pytest

from statectl._state_changer import RollbackableStateChanger, StateChanger
from statectl._statechangers import (
    EnsureLaunchdAgentParameters,
    EnsureLaunchdAgentRollbackStateChanger,
)
from tests.statechangers._launchd_helpers import (
    DEFAULT_LABEL,
    make_changer,
    make_plist,
)


def test_is_a_rollbackable_state_changer() -> None:
    changer = make_changer()
    assert isinstance(changer, RollbackableStateChanger)
    assert isinstance(changer, StateChanger)


def test_rollback_returns_plain_state_changer() -> None:
    rb = make_changer().rollback()
    assert isinstance(rb, StateChanger)
    assert not isinstance(rb, RollbackableStateChanger)
    assert isinstance(rb, EnsureLaunchdAgentRollbackStateChanger)


def test_parameters_are_frozen() -> None:
    params = EnsureLaunchdAgentParameters(
        label=DEFAULT_LABEL,
        plist_content=make_plist(),
        scope="user",
    )
    with pytest.raises(Exception):
        params.label = "other"  # type: ignore[misc]


def test_name_encodes_label() -> None:
    assert make_changer().name() == f"ensure-launchd-agent:{DEFAULT_LABEL}"


def test_rollback_name_encodes_label() -> None:
    assert (
        make_changer().rollback().name()
        == f"ensure-launchd-agent-rollback:{DEFAULT_LABEL}"
    )
