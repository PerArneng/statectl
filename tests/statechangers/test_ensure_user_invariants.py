from __future__ import annotations

from pathlib import Path

import pytest

from statectl._state_changer import RollbackableStateChanger, StateChanger
from statectl._statechangers import (
    EnsureUserParameters,
    EnsureUserRollbackStateChanger,
    EnsureUserStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


def _changer() -> EnsureUserStateChanger:
    return EnsureUserStateChanger(
        EnsureUserParameters(username="alice"),
        process_runner=ScriptedProcessRunner(),
        file_system=InMemoryFileSystem(),
        env=ScriptedEnv.linux(),
    )


def test_is_rollbackable_state_changer() -> None:
    assert isinstance(_changer(), RollbackableStateChanger)


def test_rollback_returns_plain_state_changer() -> None:
    inverse = _changer().rollback()
    assert isinstance(inverse, StateChanger)
    assert not isinstance(inverse, RollbackableStateChanger)
    assert isinstance(inverse, EnsureUserRollbackStateChanger)


def test_parameters_are_frozen() -> None:
    params = EnsureUserParameters(username="alice")
    with pytest.raises(Exception):
        params.username = "bob"  # type: ignore[misc]


def test_name_encodes_username() -> None:
    assert _changer().name() == "ensure-user:alice"


def test_rollback_name_encodes_username() -> None:
    inverse = EnsureUserRollbackStateChanger(
        EnsureUserParameters(username="alice"),
        process_runner=ScriptedProcessRunner(),
        file_system=InMemoryFileSystem(),
        env=ScriptedEnv.linux(),
    )
    assert inverse.name() == "ensure-user-rollback:alice"


def test_parameters_defaults() -> None:
    params = EnsureUserParameters(username="alice")
    assert params.uid is None
    assert params.home is None
    assert params.shell is None
    assert params.primary_group is None
    assert params.supplementary_groups == ()
    assert params.system is False
    assert params.enforce_attributes is True


def test_parameters_accept_full_set() -> None:
    params = EnsureUserParameters(
        username="alice",
        uid=1500,
        home=Path("/home/alice"),
        shell=Path("/bin/zsh"),
        primary_group="alice",
        supplementary_groups=("sudo", "docker"),
        system=True,
        enforce_attributes=False,
    )
    assert params.supplementary_groups == ("sudo", "docker")
    assert params.system is True
