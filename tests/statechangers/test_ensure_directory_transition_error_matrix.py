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
from statectl._state_changer import ResultStatus
from statectl._statechangers import (
    EnsureDirectoryParameters,
    EnsureDirectoryStateChanger,
)
from tests.fakes.failing_file_system import FailingFileSystem
from tests.fakes.in_memory_file_system import InMemoryFileSystem


TARGET = Path("/work/data")


def _ready_fs() -> FailingFileSystem:
    inner = InMemoryFileSystem()
    inner.add_dir(Path("/work"))
    return FailingFileSystem(inner)


def _changer(fs: FailingFileSystem, *, mode: int | None = None) -> EnsureDirectoryStateChanger:
    return EnsureDirectoryStateChanger(
        EnsureDirectoryParameters(path=TARGET, mode=mode),
        file_system=fs,
    )


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
def test_create_folder_failure_maps_to_mkdir_failed(error: FsError) -> None:
    fs = _ready_fs()
    fs.fail("create_folder", error, path=TARGET)

    result = _changer(fs).transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == "MKDIR_FAILED"
    assert error.message in (result.message or "")


def test_chmod_fs_not_found_maps_to_dir_vanished() -> None:
    fs = _ready_fs()
    fs.fail("chmod", FsNotFound("gone", path=TARGET), path=TARGET)

    result = _changer(fs, mode=0o755).transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == "DIR_VANISHED"


@pytest.mark.parametrize(
    "error",
    [e for e in ALL_FS_ERRORS if not isinstance(e, FsNotFound)],
    ids=lambda e: type(e).__name__,
)
def test_chmod_non_not_found_errors_map_to_chmod_failed(error: FsError) -> None:
    fs = _ready_fs()
    fs.fail("chmod", error, path=TARGET)

    result = _changer(fs, mode=0o755).transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == "CHMOD_FAILED"


def test_unexpected_exception_propagates() -> None:
    class _BrokenFS(InMemoryFileSystem):
        def create_folder(self, path: Path, parents: bool = False, exist_ok: bool = False) -> None:
            raise RuntimeError("boom")

    fs = _BrokenFS()
    fs.add_dir(Path("/work"))
    changer = EnsureDirectoryStateChanger(
        EnsureDirectoryParameters(path=TARGET),
        file_system=fs,
    )

    with pytest.raises(RuntimeError, match="boom"):
        changer.transition()
