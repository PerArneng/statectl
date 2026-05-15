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
    CopyFileParameters,
    CopyFileRollbackStateChanger,
    CopyFileStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem


SRC = Path("/work/a")
DEST = Path("/work/b")


def _fs() -> InMemoryFileSystem:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(SRC, content="hello\n")
    return fs


def _changer(fs: InMemoryFileSystem) -> CopyFileStateChanger:
    return CopyFileStateChanger(
        CopyFileParameters(src=SRC, dest=DEST),
        file_system=fs,
    )


def test_parameters_is_frozen_parameters_subclass() -> None:
    params = CopyFileParameters(src=SRC, dest=DEST)
    assert isinstance(params, Parameters)
    with pytest.raises(FrozenInstanceError):
        params.mode = 0o644  # pyrefly: ignore  # noqa: F841


def test_parameters_defaults() -> None:
    params = CopyFileParameters(src=SRC, dest=DEST)
    assert params.mode is None
    assert params.overwrite is False
    assert params.preserve_mtime is False


def test_is_rollbackable_state_changer() -> None:
    ch = _changer(_fs())
    assert isinstance(ch, StateChanger)
    assert isinstance(ch, RollbackableStateChanger)


def test_rollback_returns_plain_state_changer() -> None:
    rb = _changer(_fs()).rollback()
    assert isinstance(rb, StateChanger)
    assert not isinstance(rb, RollbackableStateChanger)
    assert isinstance(rb, CopyFileRollbackStateChanger)


def test_name_contains_src_and_dest() -> None:
    n = _changer(_fs()).name()
    assert str(SRC) in n
    assert str(DEST) in n


def test_assess_state_does_not_mutate_filesystem() -> None:
    fs = _fs()
    fs.add_file(DEST, content="other\n")
    snapshot = {
        p: (n.is_dir, n.content, n.binary_content, n.mode)
        for p, n in fs._nodes.items()
    }
    _changer(fs).assess_state()
    after = {
        p: (n.is_dir, n.content, n.binary_content, n.mode)
        for p, n in fs._nodes.items()
    }
    assert after == snapshot
