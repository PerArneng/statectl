from __future__ import annotations

from pathlib import Path

import pytest

from statectl._interfaces.archive import (
    ArchiveCorrupt,
    ArchiveError,
    ArchiveFormat,
    ArchiveIoError,
    ArchiveNotFound,
    ArchiveUnsafeEntry,
    ArchiveUnsupportedFormat,
)
from statectl._state_changer import ResultStatus
from statectl._statechangers import (
    ExtractArchiveParameters,
    ExtractArchiveStateChanger,
)
from statectl._interfaces.fs import FsIoError
from tests.fakes.failing_archive import FailingArchive
from tests.fakes.failing_file_system import FailingFileSystem
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_archive import ScriptedArchive


def _build(
    archive_inner: ScriptedArchive,
) -> tuple[ExtractArchiveStateChanger, FailingArchive, InMemoryFileSystem]:
    fs = InMemoryFileSystem()
    fs.add_file(Path("/pkg.tar.gz"), content="x")
    fs.add_dir(Path("/work/out"))
    archive_inner.register_archive(Path("/pkg.tar.gz"), ArchiveFormat.TAR_GZ)
    failing = FailingArchive(archive_inner)
    changer = ExtractArchiveStateChanger(
        ExtractArchiveParameters(
            archive_path=Path("/pkg.tar.gz"),
            dest_dir=Path("/work/out"),
            format=ArchiveFormat.TAR_GZ,
            sentinel_path=Path("/work/out/bin/foo"),
        ),
        file_system=fs,
        archive=failing,
    )
    return changer, failing, fs


@pytest.mark.parametrize(
    "error,expected_code",
    [
        (ArchiveNotFound("gone", path=Path("/pkg.tar.gz")), "ARCHIVE_VANISHED"),
        (ArchiveCorrupt("bad bytes", path=Path("/pkg.tar.gz")), "ARCHIVE_MALFORMED"),
        (
            ArchiveUnsafeEntry("/etc/passwd", path=Path("/pkg.tar.gz")),
            "EXTRACT_FAILED",
        ),
        (
            ArchiveUnsupportedFormat("unknown", path=Path("/pkg.tar.gz")),
            "EXTRACT_FAILED",
        ),
        (ArchiveIoError("disk full", path=Path("/pkg.tar.gz")), "EXTRACT_FAILED"),
    ],
)
def test_archive_errors_map_to_specific_codes(
    error: ArchiveError, expected_code: str
) -> None:
    changer, failing, _ = _build(ScriptedArchive())
    failing.fail("extract", error, path=Path("/pkg.tar.gz"))

    result = changer.transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == expected_code


def test_unexpected_exception_propagates() -> None:
    inner = ScriptedArchive()
    fs = InMemoryFileSystem()
    fs.add_file(Path("/pkg.tar.gz"), content="x")
    fs.add_dir(Path("/work/out"))

    class _Boom(ScriptedArchive):
        def extract(  # type: ignore[override]
            self,
            src: Path,
            dest: Path,
            format: ArchiveFormat,
            strip_components: int = 0,
        ) -> None:
            raise RuntimeError("kaboom")

    changer = ExtractArchiveStateChanger(
        ExtractArchiveParameters(
            archive_path=Path("/pkg.tar.gz"),
            dest_dir=Path("/work/out"),
            format=ArchiveFormat.TAR_GZ,
            sentinel_path=Path("/work/out/bin/foo"),
        ),
        file_system=fs,
        archive=_Boom(),
    )

    with pytest.raises(RuntimeError, match="kaboom"):
        changer.transition()


def test_mkdir_failure_maps_to_mkdir_failed() -> None:
    inner_fs = InMemoryFileSystem()
    inner_fs.add_dir(Path("/work"))
    inner_fs.add_file(Path("/pkg.tar.gz"), content="x")
    fs = FailingFileSystem(inner_fs)
    fs.fail(
        "create_folder",
        FsIoError("disk full", path=Path("/work/out")),
        path=Path("/work/out"),
    )
    archive = ScriptedArchive()
    archive.register_archive(Path("/pkg.tar.gz"), ArchiveFormat.TAR_GZ)

    changer = ExtractArchiveStateChanger(
        ExtractArchiveParameters(
            archive_path=Path("/pkg.tar.gz"),
            dest_dir=Path("/work/out"),
            format=ArchiveFormat.TAR_GZ,
            sentinel_path=Path("/work/out/bin/foo"),
        ),
        file_system=fs,
        archive=archive,
    )

    result = changer.transition()
    assert result.status is ResultStatus.FAILURE
    assert result.code == "MKDIR_FAILED"
