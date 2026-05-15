from __future__ import annotations

from pathlib import Path

from statectl._state_changer import RollbackableStateChanger, StateChanger
from statectl._statechangers import (
    AtEnd,
    EnsureLineInFileParameters,
    EnsureLineInFileRollbackStateChanger,
    EnsureLineInFileStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem


def _params(path: Path) -> EnsureLineInFileParameters:
    return EnsureLineInFileParameters(path=path, line="newline", placement=AtEnd())


def test_extends_rollbackable_state_changer() -> None:
    fs = InMemoryFileSystem()
    ch = EnsureLineInFileStateChanger(_params(Path("/x")), file_system=fs)
    assert isinstance(ch, RollbackableStateChanger)


def test_rollback_is_plain_state_changer() -> None:
    fs = InMemoryFileSystem()
    ch = EnsureLineInFileStateChanger(_params(Path("/x")), file_system=fs)
    rollback = ch.rollback()
    assert isinstance(rollback, StateChanger)
    assert not isinstance(rollback, RollbackableStateChanger)


def test_name_includes_target_path_for_both_directions() -> None:
    fs = InMemoryFileSystem()
    p = Path("/work/conf.txt")
    ch = EnsureLineInFileStateChanger(_params(p), file_system=fs)
    rollback = EnsureLineInFileRollbackStateChanger(_params(p), file_system=fs)
    assert str(p) in ch.name()
    assert str(p) in rollback.name()
    assert ch.name() != rollback.name()


def test_assess_state_does_not_mutate_filesystem() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/c.txt"), content="a\nb\n")
    snapshot = dict(fs._nodes)
    ch = EnsureLineInFileStateChanger(
        EnsureLineInFileParameters(path=Path("/work/c.txt"), line="c", placement=AtEnd()),
        file_system=fs,
    )
    ch.assess_state()
    assert fs._nodes == snapshot
