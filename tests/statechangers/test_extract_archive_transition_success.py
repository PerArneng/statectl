from __future__ import annotations

from pathlib import Path

from statectl._interfaces.archive import ArchiveFormat
from statectl._state_changer import ResultStatus
from statectl._statechangers import (
    ExtractArchiveParameters,
    ExtractArchiveStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_archive import ScriptedArchive


def test_transition_extracts_and_creates_dest() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/pkg.tar.gz"), content="bytes")
    archive = ScriptedArchive(file_system=fs)
    archive.register_archive(
        Path("/pkg.tar.gz"),
        ArchiveFormat.TAR_GZ,
        entries={"bin/foo": "binary", "README": "docs"},
    )

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

    assert result.status is ResultStatus.SUCCESS
    assert fs.is_dir(Path("/work/out"))
    assert fs.is_file(Path("/work/out/bin/foo"))
    assert fs.read_text_file(Path("/work/out/bin/foo")) == "binary"
    assert len(archive.calls) == 1
    call = archive.calls[0]
    assert call.src == Path("/pkg.tar.gz")
    assert call.dest == Path("/work/out")
    assert call.format is ArchiveFormat.TAR_GZ
    assert call.strip_components == 0


def test_transition_threads_strip_components_to_archive() -> None:
    fs = InMemoryFileSystem()
    fs.add_file(Path("/pkg.tar.gz"), content="bytes")
    fs.add_dir(Path("/work/out"))
    archive = ScriptedArchive(file_system=fs)
    archive.register_archive(
        Path("/pkg.tar.gz"),
        ArchiveFormat.TAR_GZ,
        entries={"top/bin/foo": "binary", "top/README": "docs"},
    )

    changer = ExtractArchiveStateChanger(
        ExtractArchiveParameters(
            archive_path=Path("/pkg.tar.gz"),
            dest_dir=Path("/work/out"),
            format=ArchiveFormat.TAR_GZ,
            sentinel_path=Path("/work/out/bin/foo"),
            strip_components=1,
        ),
        file_system=fs,
        archive=archive,
    )

    result = changer.transition()

    assert result.status is ResultStatus.SUCCESS
    assert archive.calls[0].strip_components == 1
    assert fs.is_file(Path("/work/out/bin/foo"))


def test_transition_skips_mkdir_when_dest_exists() -> None:
    fs = InMemoryFileSystem()
    fs.add_file(Path("/pkg.tar.gz"), content="bytes")
    fs.add_dir(Path("/work/out"))
    archive = ScriptedArchive(file_system=fs)
    archive.register_archive(
        Path("/pkg.tar.gz"),
        ArchiveFormat.TAR_GZ,
        entries={"bin/foo": "x"},
    )

    changer = ExtractArchiveStateChanger(
        ExtractArchiveParameters(
            archive_path=Path("/pkg.tar.gz"),
            dest_dir=Path("/work/out"),
            format=ArchiveFormat.TAR_GZ,
            sentinel_path=Path("/work/out/bin/foo"),
            create_dest=False,
        ),
        file_system=fs,
        archive=archive,
    )

    result = changer.transition()
    assert result.status is ResultStatus.SUCCESS
