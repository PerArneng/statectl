from __future__ import annotations

from pathlib import Path
from typing import override

import pytest

from statectl._interfaces.archive import (
    ArchiveCorrupt,
    ArchiveError,
    ArchiveIoError,
    ArchiveNotFound,
    ArchiveFormat,
    ArchiveUnsafeEntry,
    ArchiveUnsupportedFormat,
)
from statectl._state_changer import ResultStatus
from statectl._statechangers import (
    ExtractArchiveParameters,
    ExtractArchiveStateChanger,
)
from tests.fakes.failing_archive import FailingArchive
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_archive import ScriptedArchive


ARCHIVE = Path("/work/pkg.tar.gz")
DEST = Path("/work/out")
SENTINEL = Path("/work/out/bin/foo")


def _make(archive_capability: FailingArchive) -> ExtractArchiveStateChanger:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(ARCHIVE, content="ar")
    fs.add_dir(DEST)
    return ExtractArchiveStateChanger(
        ExtractArchiveParameters(
            archive_path=ARCHIVE,
            dest_dir=DEST,
            format=ArchiveFormat.TAR_GZ,
            sentinel_path=SENTINEL,
        ),
        file_system=fs,
        archive=archive_capability,
    )


def _wrap(err: ArchiveError) -> FailingArchive:
    inner = ScriptedArchive()
    inner.register_archive(ARCHIVE, ArchiveFormat.TAR_GZ)
    wrapper = FailingArchive(inner)
    wrapper.fail("extract", err)
    return wrapper


@pytest.mark.parametrize(
    "error,expected_code",
    [
        (ArchiveNotFound("gone", path=ARCHIVE), "ARCHIVE_VANISHED"),
        (ArchiveCorrupt("bad bytes", path=ARCHIVE), "ARCHIVE_MALFORMED"),
        (ArchiveIoError("disk full", path=ARCHIVE), "EXTRACT_FAILED"),
        (ArchiveUnsafeEntry("path traversal", path=ARCHIVE), "EXTRACT_FAILED"),
        (ArchiveUnsupportedFormat("nope", path=ARCHIVE), "EXTRACT_FAILED"),
    ],
)
def test_archive_errors_map_to_failure_codes(
    error: ArchiveError, expected_code: str
) -> None:
    changer = _make(_wrap(error))
    result = changer.transition()
    assert result.status is ResultStatus.FAILURE
    assert result.code == expected_code


def test_archive_vanished_before_transition_returns_failure() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_dir(DEST)  # archive was never created (or removed)
    changer = ExtractArchiveStateChanger(
        ExtractArchiveParameters(
            archive_path=ARCHIVE,
            dest_dir=DEST,
            format=ArchiveFormat.TAR_GZ,
            sentinel_path=SENTINEL,
        ),
        file_system=fs,
        archive=ScriptedArchive(),
    )
    result = changer.transition()
    assert result.status is ResultStatus.FAILURE
    assert result.code == "ARCHIVE_VANISHED"


def test_unexpected_exception_propagates() -> None:
    class _Boom(ScriptedArchive):
        @override
        def extract(
            self,
            src: Path,
            dest: Path,
            format: ArchiveFormat,
            strip_components: int = 0,
        ) -> None:
            raise RuntimeError("unexpected")

    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(ARCHIVE, content="ar")
    fs.add_dir(DEST)
    changer = ExtractArchiveStateChanger(
        ExtractArchiveParameters(
            archive_path=ARCHIVE,
            dest_dir=DEST,
            format=ArchiveFormat.TAR_GZ,
            sentinel_path=SENTINEL,
        ),
        file_system=fs,
        archive=_Boom(),
    )
    with pytest.raises(RuntimeError):
        changer.transition()
