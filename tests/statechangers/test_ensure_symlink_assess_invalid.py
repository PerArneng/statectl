from __future__ import annotations

from pathlib import Path

from statectl._state_changer import ExistingState
from statectl._statechangers import (
    EnsureSymlinkParameters,
    EnsureSymlinkStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem


def _make(
    fs: InMemoryFileSystem,
    *,
    overwrite_non_symlink: bool = False,
    allow_dangling: bool = True,
    link_path: Path = Path("/work/link"),
    target: Path = Path("/work/target"),
) -> EnsureSymlinkStateChanger:
    return EnsureSymlinkStateChanger(
        EnsureSymlinkParameters(
            link_path=link_path,
            target=target,
            overwrite_non_symlink=overwrite_non_symlink,
            allow_dangling=allow_dangling,
        ),
        file_system=fs,
    )


def test_invalid_when_parent_missing() -> None:
    fs = InMemoryFileSystem()
    assessment = _make(fs).assess_state()
    assert assessment.state is ExistingState.INVALID
    assert any("parent missing" in i for i in assessment.issues)


def test_invalid_when_parent_not_writable() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"), writable=False)
    assessment = _make(fs).assess_state()
    assert assessment.state is ExistingState.INVALID
    assert any("parent not writable" in i for i in assessment.issues)


def test_invalid_when_link_path_is_regular_file_and_no_overwrite() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/link"), content="x")
    assessment = _make(fs).assess_state()
    assert assessment.state is ExistingState.INVALID
    assert any("not a symlink" in i for i in assessment.issues)


def test_invalid_when_link_path_is_directory_and_no_overwrite() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_dir(Path("/work/link"))
    assessment = _make(fs).assess_state()
    assert assessment.state is ExistingState.INVALID
    assert any("not a symlink" in i for i in assessment.issues)


def test_invalid_when_target_missing_and_dangling_disallowed() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    assessment = _make(fs, allow_dangling=False).assess_state()
    assert assessment.state is ExistingState.INVALID
    assert any("target does not exist" in i for i in assessment.issues)


def test_collects_all_issues_in_one_pass() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"), writable=False)
    fs.add_file(Path("/work/link"), content="x")
    assessment = _make(fs, allow_dangling=False).assess_state()
    assert assessment.state is ExistingState.INVALID
    # parent not writable, non-symlink present, target missing
    assert len(assessment.issues) == 3
