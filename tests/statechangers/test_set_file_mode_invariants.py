from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from statectl._state_changer import (
    Parameters,
    RollbackableStateChanger,
    StateChanger,
)
from statectl._statechangers import (
    SetFileModeParameters,
    SetFileModeRollbackStateChanger,
    SetFileModeStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem


def _changer(fs: InMemoryFileSystem) -> SetFileModeStateChanger:
    return SetFileModeStateChanger(
        SetFileModeParameters(path=Path("/work/x"), mode=0o644),
        file_system=fs,
    )


def test_parameters_is_frozen_parameters_subclass() -> None:
    params = SetFileModeParameters(path=Path("/x"), mode=0o644)
    assert isinstance(params, Parameters)
    with pytest.raises(FrozenInstanceError):
        params.mode = 0o755  # pyrefly: ignore  # noqa: F841


def test_is_rollbackable_state_changer() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/x"))
    ch = _changer(fs)
    assert isinstance(ch, StateChanger)
    assert isinstance(ch, RollbackableStateChanger)


def test_rollback_returns_plain_state_changer() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/x"), mode=0o600)
    rb = _changer(fs).rollback()
    assert isinstance(rb, StateChanger)
    assert not isinstance(rb, RollbackableStateChanger)
    assert isinstance(rb, SetFileModeRollbackStateChanger)


def test_name_contains_path() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/x"))
    assert str(Path("/work/x")) in _changer(fs).name()


def test_assess_state_does_not_mutate_filesystem() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/x"), mode=0o600)
    snapshot = {p: (n.mode, n.link_mode, n.content) for p, n in fs._nodes.items()}
    _changer(fs).assess_state()
    after = {p: (n.mode, n.link_mode, n.content) for p, n in fs._nodes.items()}
    assert after == snapshot
