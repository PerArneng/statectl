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


ARCHIVE = Path("/work/pkg.tar.gz")
DEST = Path("/work/out")
SENTINEL = Path("/work/out/bin/foo")


def _fs() -> InMemoryFileSystem:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(ARCHIVE, content="ar")
    return fs


def _changer(
    fs: InMemoryFileSystem, *, create_dest: bool = True
) -> ExtractArchiveStateChanger:
    return ExtractArchiveStateChanger(
        ExtractArchiveParameters(
            archive_path=ARCHIVE,
            dest_dir=DEST,
            format=ArchiveFormat.TAR_GZ,
            sentinel_path=SENTINEL,
            create_dest=create_dest,
        ),
        file_system=fs,
        archive=ScriptedArchive(),
    )


def test_ready_when_dest_exists_and_no_sentinel() -> None:
    fs = _fs()
    fs.add_dir(DEST)
    a = _changer(fs).assess_state()
    assert a.state is ExistingState.READY


def test_ready_when_dest_missing_and_create_dest_true() -> None:
    fs = _fs()
    a = _changer(fs).assess_state()
    assert a.state is ExistingState.READY


def test_already_applied_when_sentinel_exists() -> None:
    fs = _fs()
    fs.add_dir(DEST)
    fs.add_dir(DEST / "bin")
    fs.add_file(SENTINEL, content="payload")
    a = _changer(fs).assess_state()
    assert a.state is ExistingState.ALREADY_APPLIED
