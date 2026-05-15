from __future__ import annotations

from pathlib import Path

import pytest

from statectl._interfaces.fs import FsError, FsIoError, FsPermissionDenied
from statectl._state_changer import ResultStatus
from statectl._statechangers import (
    LiteralMatch,
    ReplaceInFileParameters,
    ReplaceInFileStateChanger,
)
from tests.fakes.failing_file_system import FailingFileSystem
from tests.fakes.in_memory_file_system import InMemoryFileSystem


P = Path("/w/c.txt")


def _setup() -> FailingFileSystem:
    inner = InMemoryFileSystem()
    inner.add_dir(Path("/w"))
    inner.add_file(P, content="foo\n")
    return FailingFileSystem(inner)


def _changer(fs: FailingFileSystem) -> ReplaceInFileStateChanger:
    return ReplaceInFileStateChanger(
        ReplaceInFileParameters(
            path=P,
            match=LiteralMatch(needle="foo", expected_count=1, replacement="bar"),
        ),
        file_system=fs,
    )


@pytest.mark.parametrize(
    "error",
    [FsIoError("boom"), FsPermissionDenied("nope")],
)
def test_read_failure_maps_to_read_failed_code(error: FsError) -> None:
    fs = _setup()
    fs.fail("read_text_file", error, path=P)
    result = _changer(fs).transition()
    assert result.status is ResultStatus.FAILURE
    assert result.code == "READ_FAILED"


@pytest.mark.parametrize(
    "error",
    [FsIoError("disk full"), FsPermissionDenied("no perm")],
)
def test_write_failure_maps_to_write_failed_code(error: FsError) -> None:
    fs = _setup()
    fs.fail("write_text_file", error, path=P)
    result = _changer(fs).transition()
    assert result.status is ResultStatus.FAILURE
    assert result.code == "WRITE_FAILED"


def test_match_vanished_when_count_changes_between_assess_and_transition() -> None:
    inner = InMemoryFileSystem()
    inner.add_dir(Path("/w"))
    inner.add_file(P, content="foo\n")
    ch = ReplaceInFileStateChanger(
        ReplaceInFileParameters(
            path=P,
            match=LiteralMatch(needle="foo", expected_count=1, replacement="bar"),
        ),
        file_system=inner,
    )
    # Simulate concurrent mutation: file content changes so the count no
    # longer matches expected_count.
    inner.add_file(P, content="foo foo\n")
    result = ch.transition()
    assert result.status is ResultStatus.FAILURE
    assert result.code == "MATCH_VANISHED"


def test_unexpected_exception_propagates() -> None:
    fs = _setup()

    class _Boom(Exception):
        pass

    fs.fail("read_text_file", _Boom("unexpected"), path=P)  # type: ignore[arg-type]
    with pytest.raises(_Boom):
        _changer(fs).transition()
