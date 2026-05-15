from __future__ import annotations

from pathlib import Path

from statectl._state_changer import ResultStatus
from statectl._statechangers import (
    EnsureSymlinkParameters,
    EnsureSymlinkStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem


def _make(
    fs: InMemoryFileSystem,
    *,
    overwrite_non_symlink: bool = False,
) -> EnsureSymlinkStateChanger:
    return EnsureSymlinkStateChanger(
        EnsureSymlinkParameters(
            link_path=Path("/work/link"),
            target=Path("/work/target"),
            overwrite_non_symlink=overwrite_non_symlink,
        ),
        file_system=fs,
    )


def test_creates_new_symlink() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))

    result = _make(fs).transition()

    assert result.status is ResultStatus.SUCCESS
    assert fs.is_symlink(Path("/work/link"))
    assert fs.read_symlink(Path("/work/link")) == Path("/work/target")


def test_replaces_existing_symlink_pointing_elsewhere() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_symlink(Path("/work/link"), target=Path("/work/other"))

    result = _make(fs).transition()

    assert result.status is ResultStatus.SUCCESS
    assert fs.read_symlink(Path("/work/link")) == Path("/work/target")


def test_overwrites_regular_file_when_allowed() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/link"), content="old")

    result = _make(fs, overwrite_non_symlink=True).transition()

    assert result.status is ResultStatus.SUCCESS
    assert fs.is_symlink(Path("/work/link"))
    assert fs.read_symlink(Path("/work/link")) == Path("/work/target")
