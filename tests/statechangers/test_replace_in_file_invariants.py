from __future__ import annotations

from pathlib import Path

from statectl._state_changer import RollbackableStateChanger, StateChanger
from statectl._statechangers import (
    LiteralMatch,
    ReplaceInFileParameters,
    ReplaceInFileRollbackStateChanger,
    ReplaceInFileStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem


def _params(path: Path) -> ReplaceInFileParameters:
    return ReplaceInFileParameters(
        path=path,
        match=LiteralMatch(needle="foo", expected_count=1, replacement="bar"),
    )


def test_extends_rollbackable_state_changer() -> None:
    fs = InMemoryFileSystem()
    ch = ReplaceInFileStateChanger(_params(Path("/x")), file_system=fs)
    assert isinstance(ch, RollbackableStateChanger)


def test_rollback_is_plain_state_changer() -> None:
    fs = InMemoryFileSystem()
    ch = ReplaceInFileStateChanger(_params(Path("/x")), file_system=fs)
    rollback = ch.rollback()
    assert isinstance(rollback, StateChanger)
    assert not isinstance(rollback, RollbackableStateChanger)


def test_name_includes_target_path_for_both_directions() -> None:
    fs = InMemoryFileSystem()
    p = Path("/work/conf.txt")
    ch = ReplaceInFileStateChanger(_params(p), file_system=fs)
    rollback = ReplaceInFileRollbackStateChanger(_params(p), file_system=fs)
    assert str(p) in ch.name()
    assert str(p) in rollback.name()
    assert ch.name() != rollback.name()


def test_assess_state_does_not_mutate_filesystem() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/c.txt"), content="foo bar\n")
    snapshot = dict(fs._nodes)
    ch = ReplaceInFileStateChanger(_params(Path("/work/c.txt")), file_system=fs)
    ch.assess_state()
    assert fs._nodes == snapshot
