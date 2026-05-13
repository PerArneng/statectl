from __future__ import annotations

from pathlib import Path

from statectl.state_changer import ExistingState, ResultStatus, RollbackableStateChanger
from statectl.statechangers.new_text_file import (
    NewTextFileParameters,
    NewTextFileStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem


def _changer(fs: InMemoryFileSystem, path: Path, text: str) -> RollbackableStateChanger:
    return NewTextFileStateChanger(
        NewTextFileParameters(path=path, text=text),
        file_system=fs,
    )


def test_apply_then_rollback_leaves_filesystem_unchanged() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    target = Path("/work/hello.txt")
    changer = _changer(fs, target, "hi")

    assert changer.assess_state().state is ExistingState.READY
    assert changer.transition().status is ResultStatus.SUCCESS
    assert fs.is_file(target)

    rollback = changer.rollback()
    assert rollback.assess_state().state is ExistingState.READY
    assert rollback.transition().status is ResultStatus.SUCCESS
    assert not fs.exists(target)


def test_rolling_back_twice_is_idempotent() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    target = Path("/work/hello.txt")
    changer = _changer(fs, target, "hi")

    changer.transition()
    first = changer.rollback()
    assert first.transition().status is ResultStatus.SUCCESS

    second = changer.rollback()
    assert second.assess_state().state is ExistingState.ALREADY_APPLIED


def test_apply_is_idempotent_when_run_twice() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    target = Path("/work/hello.txt")
    changer = _changer(fs, target, "hi")

    changer.transition()
    assert changer.assess_state().state is ExistingState.ALREADY_APPLIED
