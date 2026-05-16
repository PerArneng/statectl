from __future__ import annotations

from pathlib import Path

import pytest

from statectl._state_changer import RollbackableStateChanger, StateChanger
from statectl._statechangers import (
    EnsureDefaultShellParameters,
    EnsureDefaultShellRollbackStateChanger,
    EnsureDefaultShellStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


def _params() -> EnsureDefaultShellParameters:
    return EnsureDefaultShellParameters(
        user="alice", shell=Path("/bin/zsh")
    )


def _changer() -> EnsureDefaultShellStateChanger:
    return EnsureDefaultShellStateChanger(
        _params(),
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
    assert isinstance(inverse, EnsureDefaultShellRollbackStateChanger)


def test_parameters_are_frozen() -> None:
    params = _params()
    with pytest.raises(Exception):
        params.user = "bob"  # type: ignore[misc]


def test_name_encodes_user_and_shell() -> None:
    assert _changer().name() == "ensure-default-shell:alice:/bin/zsh"


def test_rollback_name_encodes_user() -> None:
    inverse = EnsureDefaultShellRollbackStateChanger(
        _params(),
        pre_shell=Path("/bin/bash"),
        process_runner=ScriptedProcessRunner(),
        file_system=InMemoryFileSystem(),
        env=ScriptedEnv.linux(),
    )
    assert inverse.name() == "ensure-default-shell-rollback:alice"
