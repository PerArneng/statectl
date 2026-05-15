from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from statectl._state_changer import Parameters, RollbackableStateChanger, StateChanger
from statectl._statechangers import DeletePathParameters, DeletePathStateChanger
from tests.fakes.in_memory_file_system import InMemoryFileSystem


def _changer(fs: InMemoryFileSystem, **kwargs: object) -> DeletePathStateChanger:
    params = DeletePathParameters(path=Path("/work/x"), kind="file", **kwargs)  # type: ignore[arg-type]
    return DeletePathStateChanger(params, file_system=fs)


def test_parameters_is_frozen_parameters_subclass() -> None:
    params = DeletePathParameters(path=Path("/x"), kind="file")
    assert isinstance(params, Parameters)
    with pytest.raises(FrozenInstanceError):
        params.path = Path("/y")  # pyrefly: ignore  # noqa: F841


def test_is_plain_state_changer_not_rollbackable() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/x"))
    ch = _changer(fs)
    assert isinstance(ch, StateChanger)
    assert not isinstance(ch, RollbackableStateChanger)


def test_name_contains_path() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/x"))
    assert str(Path("/work/x")) in _changer(fs).name()


def test_assess_state_does_not_mutate_filesystem() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/x"))
    snapshot = dict(fs._nodes)
    _changer(fs).assess_state()
    assert fs._nodes == snapshot
