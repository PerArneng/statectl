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


def _make(
    fs: InMemoryFileSystem,
    *,
    archive_path: Path = Path("/pkg.tar.gz"),
    dest_dir: Path = Path("/work/out"),
    sentinel_path: Path = Path("/work/out/bin/foo"),
    create_dest: bool = True,
    strip_components: int = 0,
) -> ExtractArchiveStateChanger:
    return ExtractArchiveStateChanger(
        ExtractArchiveParameters(
            archive_path=archive_path,
            dest_dir=dest_dir,
            format=ArchiveFormat.TAR_GZ,
            sentinel_path=sentinel_path,
            create_dest=create_dest,
            strip_components=strip_components,
        ),
        file_system=fs,
        archive=ScriptedArchive(),
    )


def test_invalid_when_archive_missing() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    assessment = _make(fs).assess_state()
    assert assessment.state is ExistingState.INVALID
    assert any("does not exist" in i for i in assessment.issues)


def test_invalid_when_archive_is_directory() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_dir(Path("/pkg.tar.gz"))
    assessment = _make(fs).assess_state()
    assert assessment.state is ExistingState.INVALID
    assert any("not a regular file" in i for i in assessment.issues)


def test_invalid_when_dest_exists_and_is_not_directory() -> None:
    fs = InMemoryFileSystem()
    fs.add_file(Path("/pkg.tar.gz"), content="x")
    fs.add_file(Path("/work/out"), content="not-a-dir")
    assessment = _make(fs).assess_state()
    assert assessment.state is ExistingState.INVALID
    assert any("not a directory" in i for i in assessment.issues)


def test_invalid_when_dest_not_writable() -> None:
    fs = InMemoryFileSystem()
    fs.add_file(Path("/pkg.tar.gz"), content="x")
    fs.add_dir(Path("/work"))
    fs.add_dir(Path("/work/out"), writable=False)
    assessment = _make(fs).assess_state()
    assert assessment.state is ExistingState.INVALID
    assert any("not writable" in i for i in assessment.issues)


def test_invalid_when_dest_missing_and_create_dest_false() -> None:
    fs = InMemoryFileSystem()
    fs.add_file(Path("/pkg.tar.gz"), content="x")
    assessment = _make(fs, create_dest=False).assess_state()
    assert assessment.state is ExistingState.INVALID
    assert any("create_dest=False" in i for i in assessment.issues)


def test_invalid_when_strip_components_negative() -> None:
    fs = InMemoryFileSystem()
    fs.add_file(Path("/pkg.tar.gz"), content="x")
    fs.add_dir(Path("/work/out"))
    assessment = _make(fs, strip_components=-1).assess_state()
    assert assessment.state is ExistingState.INVALID
    assert any("strip_components" in i for i in assessment.issues)


def test_multiple_issues_collected_in_one_pass() -> None:
    fs = InMemoryFileSystem()
    # archive missing AND dest exists-and-non-dir AND strip<0
    fs.add_file(Path("/work/out"), content="not-a-dir")
    assessment = _make(fs, strip_components=-2).assess_state()
    assert assessment.state is ExistingState.INVALID
    msgs = " | ".join(assessment.issues)
    assert "does not exist" in msgs
    assert "not a directory" in msgs
    assert "strip_components" in msgs
