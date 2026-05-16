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


def _fs_with_archive() -> InMemoryFileSystem:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(ARCHIVE, content="binary-archive")
    return fs


def _changer(
    fs: InMemoryFileSystem,
    *,
    create_dest: bool = True,
    strip_components: int = 0,
) -> ExtractArchiveStateChanger:
    return ExtractArchiveStateChanger(
        ExtractArchiveParameters(
            archive_path=ARCHIVE,
            dest_dir=DEST,
            format=ArchiveFormat.TAR_GZ,
            sentinel_path=SENTINEL,
            create_dest=create_dest,
            strip_components=strip_components,
        ),
        file_system=fs,
        archive=ScriptedArchive(),
    )


def test_archive_missing_is_invalid() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_dir(DEST)
    a = _changer(fs).assess_state()
    assert a.state is ExistingState.INVALID
    assert any("archive does not exist" in i for i in a.issues)


def test_archive_is_dir_is_invalid() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_dir(ARCHIVE)
    fs.add_dir(DEST)
    a = _changer(fs).assess_state()
    assert a.state is ExistingState.INVALID
    assert any("not a regular file" in i for i in a.issues)


def test_dest_exists_but_is_not_dir_is_invalid() -> None:
    fs = _fs_with_archive()
    fs.add_file(DEST, content="oops")
    a = _changer(fs).assess_state()
    assert a.state is ExistingState.INVALID
    assert any("not a directory" in i for i in a.issues)


def test_dest_missing_and_create_dest_false_is_invalid() -> None:
    fs = _fs_with_archive()
    a = _changer(fs, create_dest=False).assess_state()
    assert a.state is ExistingState.INVALID
    assert any("create_dest=False" in i for i in a.issues)


def test_dest_exists_not_writable_is_invalid() -> None:
    fs = _fs_with_archive()
    fs.add_dir(DEST, writable=False)
    a = _changer(fs).assess_state()
    assert a.state is ExistingState.INVALID
    assert any("not writable" in i for i in a.issues)


def test_negative_strip_components_is_invalid() -> None:
    fs = _fs_with_archive()
    fs.add_dir(DEST)
    a = _changer(fs, strip_components=-1).assess_state()
    assert a.state is ExistingState.INVALID
    assert any("strip_components" in i for i in a.issues)


def test_multi_issue_assessment_collects_all() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(DEST, content="not a dir")
    # archive missing AND dest is not a dir AND bad strip_components → 3 issues
    a = _changer(fs, strip_components=-2).assess_state()
    assert a.state is ExistingState.INVALID
    assert len(a.issues) >= 3
