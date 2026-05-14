from __future__ import annotations

from pathlib import Path

import pytest

from statectl._interfaces.fs import (
    FsAlreadyExists,
    FsDecodeError,
    FsError,
    FsIoError,
    FsNotADirectory,
    FsNotAFile,
    FsNotFound,
    FsPermissionDenied,
)
from statectl._state_changer import ExistingState, ResultStatus, RollbackableStateChanger
from statectl._statechangers import (
    NewTextFileParameters,
    NewTextFileStateChanger,
)
from tests.fakes.failing_file_system import FailingFileSystem
from tests.fakes.in_memory_file_system import InMemoryFileSystem


TARGET = Path("/work/hello.txt")


def _changer(fs: FailingFileSystem | InMemoryFileSystem) -> RollbackableStateChanger:
    return NewTextFileStateChanger(
        NewTextFileParameters(path=TARGET, text="hi"),
        file_system=fs,
    )


def _ready_fs() -> tuple[FailingFileSystem, InMemoryFileSystem]:
    inner = InMemoryFileSystem()
    inner.add_dir(Path("/work"))
    return FailingFileSystem(inner), inner


def _populated_fs() -> tuple[FailingFileSystem, InMemoryFileSystem]:
    inner = InMemoryFileSystem()
    inner.add_dir(Path("/work"))
    inner.add_file(TARGET, content="hi")
    return FailingFileSystem(inner), inner


ALL_FS_ERRORS: list[FsError] = [
    FsIoError("io boom", path=TARGET),
    FsPermissionDenied("no perms", path=TARGET),
    FsNotFound("vanished", path=TARGET),
    FsNotADirectory("not a dir", path=TARGET),
    FsNotAFile("not a file", path=TARGET),
    FsAlreadyExists("already there", path=TARGET),
    FsDecodeError("bad bytes", path=TARGET),
]


@pytest.mark.parametrize("error", ALL_FS_ERRORS, ids=lambda e: type(e).__name__)
def test_transition_translates_every_fs_error_subclass_to_failure(error: FsError) -> None:
    fs, _ = _ready_fs()
    fs.fail("write_text_file", error, path=TARGET)
    changer = _changer(fs)

    result = changer.transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == "WRITE_FAILED"
    assert error.message in (result.message or "")


@pytest.mark.parametrize(
    "error",
    [e for e in ALL_FS_ERRORS if not isinstance(e, FsNotFound)],
    ids=lambda e: type(e).__name__,
)
def test_rollback_transition_non_not_found_fs_errors_become_failure(error: FsError) -> None:
    fs, _ = _populated_fs()
    fs.fail("delete_file", error, path=TARGET)
    rollback = _changer(fs).rollback()

    result = rollback.transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == "UNLINK_FAILED"
    assert error.message in (result.message or "")


def test_rollback_transition_fs_not_found_becomes_skipped() -> None:
    fs, _ = _populated_fs()
    fs.fail("delete_file", FsNotFound("gone", path=TARGET), path=TARGET)
    rollback = _changer(fs).rollback()

    result = rollback.transition()

    assert result.status is ResultStatus.SKIPPED


@pytest.mark.parametrize(
    "error",
    ALL_FS_ERRORS,
    ids=lambda e: type(e).__name__,
)
def test_assess_state_when_existing_file_read_raises_any_fs_error(error: FsError) -> None:
    fs, _ = _populated_fs()
    fs.fail("read_text_file", error, path=TARGET)
    changer = _changer(fs)

    assessment = changer.assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("cannot read existing file" in i for i in assessment.issues)
