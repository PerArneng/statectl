from __future__ import annotations

from pathlib import Path

from statectl._interfaces.archive import ArchiveFormat
from statectl._state_changer import ExistingState
from statectl._statechangers import (
    ExtractArchiveParameters,
    ExtractArchiveStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_archive import ScriptedArchive


def _make(fs: InMemoryFileSystem) -> ExtractArchiveStateChanger:
    return ExtractArchiveStateChanger(
        ExtractArchiveParameters(
            archive_path=Path("/pkg.tar.gz"),
            dest_dir=Path("/work/out"),
            format=ArchiveFormat.TAR_GZ,
            sentinel_path=Path("/work/out/bin/foo"),
        ),
        file_system=fs,
        archive=ScriptedArchive(),
    )


def test_ready_when_archive_exists_dest_writable_and_no_sentinel() -> None:
    fs = InMemoryFileSystem()
    fs.add_file(Path("/pkg.tar.gz"), content="x")
    fs.add_dir(Path("/work"))
    fs.add_dir(Path("/work/out"))
    assessment = _make(fs).assess_state()
    assert assessment.state is ExistingState.READY


def test_ready_when_dest_missing_and_create_dest_default_true() -> None:
    fs = InMemoryFileSystem()
    fs.add_file(Path("/pkg.tar.gz"), content="x")
    assessment = _make(fs).assess_state()
    assert assessment.state is ExistingState.READY


def test_already_applied_when_sentinel_exists() -> None:
    fs = InMemoryFileSystem()
    fs.add_file(Path("/pkg.tar.gz"), content="x")
    fs.add_dir(Path("/work/out"))
    fs.add_dir(Path("/work/out/bin"))
    fs.add_file(Path("/work/out/bin/foo"), content="binary")
    assessment = _make(fs).assess_state()
    assert assessment.state is ExistingState.ALREADY_APPLIED
    assert assessment.issues == []
