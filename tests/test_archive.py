from __future__ import annotations

from pathlib import Path

import pytest

from statectl._interfaces.archive import (
    ArchiveFormat,
    ArchiveIoError,
    ArchiveNotFound,
)
from tests.fakes.failing_archive import FailingArchive
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_archive import RecordedExtract, ScriptedArchive


def test_scripted_detect_format_returns_registered_format() -> None:
    archive = ScriptedArchive()
    src = Path("/pkg.tar.gz")
    archive.register_archive(src, ArchiveFormat.TAR_GZ)
    assert archive.detect_format(src) is ArchiveFormat.TAR_GZ


def test_scripted_detect_format_unregistered_returns_none() -> None:
    archive = ScriptedArchive()
    assert archive.detect_format(Path("/missing.tar.gz")) is None


def test_scripted_extract_records_call_and_writes_to_filesystem() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/tmp"))
    archive = ScriptedArchive(file_system=fs)
    src = Path("/pkg.zip")
    dest = Path("/tmp/out")
    archive.register_archive(
        src,
        ArchiveFormat.ZIP,
        entries={"hello.txt": "hi", "nested/inner.txt": "deep"},
    )

    archive.extract(src, dest, ArchiveFormat.ZIP)

    assert archive.calls == [RecordedExtract(src=src, dest=dest, format=ArchiveFormat.ZIP)]
    assert fs.read_text_file(dest / "hello.txt") == "hi"
    assert fs.read_text_file(dest / "nested" / "inner.txt") == "deep"


def test_scripted_extract_without_filesystem_only_records() -> None:
    archive = ScriptedArchive()
    src = Path("/pkg.tar")
    archive.register_archive(src, ArchiveFormat.TAR, entries={"a.txt": "x"})

    archive.extract(src, Path("/out"), ArchiveFormat.TAR)

    assert len(archive.calls) == 1


def test_scripted_extract_unregistered_raises_not_found() -> None:
    archive = ScriptedArchive()
    with pytest.raises(ArchiveNotFound):
        archive.extract(Path("/missing.tar"), Path("/out"), ArchiveFormat.TAR)


def test_failing_archive_injects_one_shot_failure() -> None:
    inner = ScriptedArchive()
    src = Path("/pkg.tar")
    inner.register_archive(src, ArchiveFormat.TAR)
    wrapper = FailingArchive(inner)
    wrapper.fail("extract", ArchiveIoError("disk full", path=src), path=src)

    with pytest.raises(ArchiveIoError):
        wrapper.extract(src, Path("/out"), ArchiveFormat.TAR)

    wrapper.extract(src, Path("/out"), ArchiveFormat.TAR)
    assert len(inner.calls) == 1


def test_failing_archive_passes_through_detect_format() -> None:
    inner = ScriptedArchive()
    src = Path("/pkg.zip")
    inner.register_archive(src, ArchiveFormat.ZIP)
    wrapper = FailingArchive(inner)

    assert wrapper.detect_format(src) is ArchiveFormat.ZIP
    assert wrapper.detect_format(Path("/no.zip")) is None
