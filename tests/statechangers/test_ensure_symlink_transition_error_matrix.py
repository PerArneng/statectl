from __future__ import annotations

from pathlib import Path

from statectl._interfaces.fs import FsIoError, FsPermissionDenied
from statectl._state_changer import ResultStatus
from statectl._statechangers import (
    EnsureSymlinkParameters,
    EnsureSymlinkStateChanger,
)
from tests.fakes.failing_file_system import FailingFileSystem
from tests.fakes.in_memory_file_system import InMemoryFileSystem


def _make(fs: FailingFileSystem) -> EnsureSymlinkStateChanger:
    return EnsureSymlinkStateChanger(
        EnsureSymlinkParameters(
            link_path=Path("/work/link"),
            target=Path("/work/target"),
        ),
        file_system=fs,
    )


def test_symlink_failed_when_create_symlink_raises() -> None:
    inner = InMemoryFileSystem()
    inner.add_dir(Path("/work"))
    fs = FailingFileSystem(inner)
    fs.fail("create_symlink", FsPermissionDenied("nope", path=Path("/work/link")))

    result = _make(fs).transition()
    assert result.status is ResultStatus.FAILURE
    assert result.code == "SYMLINK_FAILED"


def test_unlink_failed_when_replacing_symlink_fails() -> None:
    inner = InMemoryFileSystem()
    inner.add_dir(Path("/work"))
    inner.add_symlink(Path("/work/link"), target=Path("/work/other"))
    fs = FailingFileSystem(inner)
    fs.fail("delete_file", FsIoError("boom", path=Path("/work/link")))

    result = _make(fs).transition()
    assert result.status is ResultStatus.FAILURE
    assert result.code == "UNLINK_FAILED"
