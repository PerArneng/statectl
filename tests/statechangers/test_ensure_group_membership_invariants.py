from __future__ import annotations

import pytest

from statectl._state_changer import RollbackableStateChanger, StateChanger
from statectl._statechangers import (
    EnsureGroupMembershipParameters,
    EnsureGroupMembershipRollbackStateChanger,
    EnsureGroupMembershipStateChanger,
)
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


def _params() -> EnsureGroupMembershipParameters:
    return EnsureGroupMembershipParameters(user="alice", group="docker")


def _changer() -> EnsureGroupMembershipStateChanger:
    return EnsureGroupMembershipStateChanger(
        _params(),
        process_runner=ScriptedProcessRunner(),
        env=ScriptedEnv.linux(),
    )


def test_is_rollbackable_state_changer() -> None:
    assert isinstance(_changer(), RollbackableStateChanger)


def test_rollback_returns_plain_state_changer() -> None:
    inverse = _changer().rollback()
    assert isinstance(inverse, StateChanger)
    assert not isinstance(inverse, RollbackableStateChanger)
    assert isinstance(inverse, EnsureGroupMembershipRollbackStateChanger)


def test_parameters_are_frozen() -> None:
    params = _params()
    with pytest.raises(Exception):
        params.user = "bob"  # type: ignore[misc]


def test_name_encodes_user_and_group() -> None:
    assert _changer().name() == "ensure-group-membership:alice:docker"


def test_rollback_name_encodes_user_and_group() -> None:
    inverse = EnsureGroupMembershipRollbackStateChanger(
        _params(),
        process_runner=ScriptedProcessRunner(),
        env=ScriptedEnv.linux(),
    )
    assert inverse.name() == "ensure-group-membership-rollback:alice:docker"


def test_default_create_group_if_missing_is_false() -> None:
    assert _params().create_group_if_missing is False
