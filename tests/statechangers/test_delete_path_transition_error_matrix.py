from __future__ import annotations

from pathlib import Path

import pytest

from statectl._interfaces.fs import (
    FsError,
    FsIoError,
    FsNotADirectory,
    FsNotAFile,
    FsPermissionDenied,
)
from statectl._state_changer import ResultStatus
from statectl._statechangers import DeletePathParameters, DeletePathStateChanger
from tests.fakes.failing_file_system import FailingFileSystem
from tests.fakes.in_memory_file_system import InMemoryFileSystem


def _fs_with_file() -> tuple[FailingFileSystem, Path]:
    inner = InMemoryFileSystem()
    inner.add_dir(Path("/work"))
    inner.add_file(Path("/work/f"))
    return FailingFileSystem(inner), Path("/work/f")


def _fs_with_dir() -> tuple[FailingFileSystem, Path]:
    inner = InMemoryFileSystem()
    inner.add_dir(Path("/work"))
    inner.add_dir(Path("/work/d"))
    return FailingFileSystem(inner), Path("/work/d")


@pytest.mark.parametrize(
    "err",
    [
        FsIoError("io"),
        FsNotAFile("not file"),
        FsPermissionDenied("denied"),
    ],
)
def test_unlink_failure_maps_to_unlink_failed(err: FsError) -> None:
    fs, path = _fs_with_file()
    fs.fail("delete_file", err, path=path)
    r = DeletePathStateChanger(
        DeletePathParameters(path=path, kind="file"),
        file_system=fs,
    ).transition()
    assert r.status is ResultStatus.FAILURE
    assert r.code == "UNLINK_FAILED"


@pytest.mark.parametrize(
    "err",
    [
        FsIoError("io"),
        FsNotADirectory("nope"),
        FsPermissionDenied("denied"),
    ],
)
def test_rmdir_failure_maps_to_rmdir_failed(err: FsError) -> None:
    fs, path = _fs_with_dir()
    fs.fail("delete_folder", err, path=path)
    r = DeletePathStateChanger(
        DeletePathParameters(path=path, kind="dir"),
        file_system=fs,
    ).transition()
    assert r.status is ResultStatus.FAILURE
    assert r.code == "RMDIR_FAILED"


def test_unexpected_exception_propagates() -> None:
    class _Boom(FailingFileSystem):
        def delete_file(self, path: Path) -> None:
            raise RuntimeError("unexpected")

    inner = InMemoryFileSystem()
    inner.add_dir(Path("/work"))
    inner.add_file(Path("/work/f"))
    fs = _Boom(inner)
    ch = DeletePathStateChanger(
        DeletePathParameters(path=Path("/work/f"), kind="file"),
        file_system=fs,
    )
    with pytest.raises(RuntimeError):
        ch.transition()
