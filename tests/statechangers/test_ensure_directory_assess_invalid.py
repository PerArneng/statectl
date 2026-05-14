from __future__ import annotations

from pathlib import Path

from statectl._state_changer import ExistingState
from statectl._statechangers import (
    EnsureDirectoryParameters,
    EnsureDirectoryStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem


def _changer(
    fs: InMemoryFileSystem,
    path: Path,
    *,
    mode: int | None = None,
    parents: bool = True,
) -> EnsureDirectoryStateChanger:
    return EnsureDirectoryStateChanger(
        EnsureDirectoryParameters(path=path, mode=mode, parents=parents),
        file_system=fs,
    )


def test_invalid_when_path_exists_as_file() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/data"), content="x")

    assessment = _changer(fs, Path("/work/data")).assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("not a directory" in i for i in assessment.issues)


def test_invalid_when_parent_missing_and_parents_false() -> None:
    fs = InMemoryFileSystem()
    assessment = _changer(fs, Path("/missing/data"), parents=False).assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("parent does not exist" in i for i in assessment.issues)


def test_invalid_when_parent_exists_but_not_writable() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"), writable=False)

    assessment = _changer(fs, Path("/work/data")).assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("not writable" in i for i in assessment.issues)


def test_invalid_when_first_existing_ancestor_not_writable_with_parents_true() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"), writable=False)

    assessment = _changer(fs, Path("/work/a/b/data"), parents=True).assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("not writable" in i for i in assessment.issues)


def test_invalid_when_mode_out_of_range_high() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))

    assessment = _changer(fs, Path("/work/data"), mode=0o10000).assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("mode out of range" in i for i in assessment.issues)


def test_invalid_when_mode_out_of_range_negative() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))

    assessment = _changer(fs, Path("/work/data"), mode=-1).assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("mode out of range" in i for i in assessment.issues)


def test_collects_multiple_issues_in_one_pass() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"), writable=False)
    fs.add_file(Path("/work/data"), content="x")

    assessment = _changer(fs, Path("/work/data"), mode=0o10000).assess_state()

    assert assessment.state is ExistingState.INVALID
    # mode out of range + path-is-file. Parent-writable is skipped because
    # the path already exists (no creation needed).
    assert len(assessment.issues) == 2
    assert any("mode out of range" in i for i in assessment.issues)
    assert any("not a directory" in i for i in assessment.issues)
