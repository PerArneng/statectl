from __future__ import annotations

from pathlib import Path

import pytest

from statectl._interfaces.fs import FsError, FsIoError, FsPermissionDenied
from statectl._state_changer import ResultStatus
from statectl._statechangers import (
    AtEnd,
    EnsureLineInFileParameters,
    EnsureLineInFileStateChanger,
)
from tests.fakes.failing_file_system import FailingFileSystem
from tests.fakes.in_memory_file_system import InMemoryFileSystem


P = Path("/w/c.txt")


def _setup() -> tuple[FailingFileSystem, InMemoryFileSystem]:
    inner = InMemoryFileSystem()
    inner.add_dir(Path("/w"))
    inner.add_file(P, content="a\nb\n")
    return FailingFileSystem(inner), inner


def _changer(fs: FailingFileSystem) -> EnsureLineInFileStateChanger:
    return EnsureLineInFileStateChanger(
        EnsureLineInFileParameters(path=P, line="z", placement=AtEnd()),
        file_system=fs,
    )


@pytest.mark.parametrize(
    "error",
    [FsIoError("boom"), FsPermissionDenied("nope")],
)
def test_read_failure_maps_to_read_failed_code(error: FsError) -> None:
    fs, _ = _setup()
    fs.fail("read_text_file", error, path=P)
    result = _changer(fs).transition()
    assert result.status is ResultStatus.FAILURE
    assert result.code == "READ_FAILED"


@pytest.mark.parametrize(
    "error",
    [FsIoError("disk full"), FsPermissionDenied("no perm")],
)
def test_write_failure_maps_to_write_failed_code(error: FsError) -> None:
    fs, _ = _setup()
    fs.fail("write_text_file", error, path=P)
    result = _changer(fs).transition()
    assert result.status is ResultStatus.FAILURE
    assert result.code == "WRITE_FAILED"


def test_unexpected_exception_propagates() -> None:
    fs, _ = _setup()

    class _Boom(Exception):
        pass

    fs.fail("read_text_file", _Boom("unexpected"), path=P)  # type: ignore[arg-type]
    with pytest.raises(_Boom):
        _changer(fs).transition()
