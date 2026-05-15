from __future__ import annotations

from pathlib import Path

from statectl._state_changer import ExistingState, ResultStatus
from statectl._statechangers import (
    EnsureSymlinkParameters,
    EnsureSymlinkStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem


def _forward(fs: InMemoryFileSystem) -> EnsureSymlinkStateChanger:
    return EnsureSymlinkStateChanger(
        EnsureSymlinkParameters(link_path=Path("/work/link"), target=Path("/work/target")),
        file_system=fs,
    )


def test_rollback_already_applied_when_link_absent() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    rollback = _forward(fs).rollback()
    assert rollback.assess_state().state is ExistingState.ALREADY_APPLIED


def test_rollback_ready_when_our_symlink_present() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_symlink(Path("/work/link"), target=Path("/work/target"))
    rollback = _forward(fs).rollback()
    assert rollback.assess_state().state is ExistingState.READY


def test_rollback_invalid_when_symlink_points_elsewhere() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_symlink(Path("/work/link"), target=Path("/work/other"))
    rollback = _forward(fs).rollback()
    assert rollback.assess_state().state is ExistingState.INVALID


def test_rollback_invalid_when_path_is_not_a_symlink() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/link"), content="x")
    rollback = _forward(fs).rollback()
    assert rollback.assess_state().state is ExistingState.INVALID


def test_rollback_transition_removes_symlink() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_symlink(Path("/work/link"), target=Path("/work/target"))
    rollback = _forward(fs).rollback()

    result = rollback.transition()
    assert result.status is ResultStatus.SUCCESS
    assert not fs.exists(Path("/work/link"))


def test_rollback_transition_skipped_if_already_gone() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    rollback = _forward(fs).rollback()
    # remove the underlying state without re-instantiating
    result = rollback.transition()
    assert result.status is ResultStatus.SKIPPED
