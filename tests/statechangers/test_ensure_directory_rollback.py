from __future__ import annotations

from pathlib import Path

from statectl._interfaces.fs import FsIoError, FsNotFound
from statectl._state_changer import ExistingState, ResultStatus
from statectl._statechangers import (
    EnsureDirectoryParameters,
    EnsureDirectoryStateChanger,
)
from tests.fakes.failing_file_system import FailingFileSystem
from tests.fakes.in_memory_file_system import InMemoryFileSystem


TARGET = Path("/work/data")


def _rollback(fs: InMemoryFileSystem | FailingFileSystem) -> object:
    return EnsureDirectoryStateChanger(
        EnsureDirectoryParameters(path=TARGET),
        file_system=fs,
    ).rollback()


def test_rollback_already_applied_when_path_absent() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))

    assert _rollback(fs).assess_state().state is ExistingState.ALREADY_APPLIED


def test_rollback_invalid_when_path_is_not_a_directory() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(TARGET, content="x")

    assessment = _rollback(fs).assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("no longer a directory" in i for i in assessment.issues)


def test_rollback_invalid_when_directory_not_empty() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_dir(TARGET)
    fs.add_file(TARGET / "child.txt", content="x")

    assessment = _rollback(fs).assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("not empty" in i for i in assessment.issues)


def test_rollback_ready_when_empty_directory_exists() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_dir(TARGET)

    assert _rollback(fs).assess_state().state is ExistingState.READY


def test_rollback_transition_removes_empty_directory() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_dir(TARGET)

    result = _rollback(fs).transition()

    assert result.status is ResultStatus.SUCCESS
    assert not fs.exists(TARGET)


def test_rollback_transition_skipped_when_directory_vanished() -> None:
    inner = InMemoryFileSystem()
    inner.add_dir(Path("/work"))
    inner.add_dir(TARGET)
    fs = FailingFileSystem(inner)
    fs.fail("delete_folder", FsNotFound("gone", path=TARGET), path=TARGET)

    result = _rollback(fs).transition()

    assert result.status is ResultStatus.SKIPPED


def test_rollback_transition_failure_maps_to_rmdir_failed() -> None:
    inner = InMemoryFileSystem()
    inner.add_dir(Path("/work"))
    inner.add_dir(TARGET)
    fs = FailingFileSystem(inner)
    fs.fail("delete_folder", FsIoError("busy", path=TARGET), path=TARGET)

    result = _rollback(fs).transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == "RMDIR_FAILED"
    assert "busy" in (result.message or "")
